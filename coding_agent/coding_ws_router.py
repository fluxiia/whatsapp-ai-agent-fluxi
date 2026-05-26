"""
WebSocket do Coding Agent — output em tempo real de tarefas e shell sessions.

Endpoints:
  WS /ws/coding/task/{task_id}           — acompanha progresso de uma tarefa
  WS /ws/coding/shell/{session_id}       — output em tempo real de um processo shell
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from database import SessionLocal
from coding_agent.coding_service import CodingService
from coding_agent.coding_stream import ensure_queue
from internal_sandbox.shell_service import ShellService

router = APIRouter(prefix="/ws/coding", tags=["coding-ws"])


# ══════════════════════════════════════════════════════════
# WebSocket: progresso de tarefa
# ══════════════════════════════════════════════════════════

@router.websocket("/task/{task_id}")
async def ws_task_progress(websocket: WebSocket, task_id: int):
    """
    Envia deltas de texto do LLM (streaming) e, em paralelo, o estado da tarefa
    a cada ~2s. Encerra quando a tarefa estiver completed, failed ou cancelled.
    """
    await websocket.accept()
    db: Session = SessionLocal()
    try:
        poll_interval = 2.0
        terminal_statuses = {"completed", "failed", "cancelled"}
        stream_q = ensure_queue(task_id)
        next_poll = time.monotonic()

        async def _poll_and_send() -> Optional[object]:
            db.expire_all()
            task = CodingService.obter_tarefa(db, task_id)
            if not task:
                await websocket.send_json({"error": f"Tarefa {task_id} não encontrada"})
                return None

            ultima_assistente: Optional[str] = None
            for msg in reversed(task.get_messages()):
                if msg.get("role") == "assistant" and msg.get("content"):
                    ultima_assistente = msg["content"]
                    if isinstance(ultima_assistente, list):
                        ultima_assistente = " ".join(
                            p.get("text", "") for p in ultima_assistente if isinstance(p, dict)
                        )
                    break

            shells_ativas = [
                sid for sid, info in (task.shell_sessions or {}).items()
                if info.get("status") == "running"
            ]

            payload = {
                "task_id": task.id,
                "status": task.status,
                "titulo": task.titulo,
                "iteracoes": task.iteracoes,
                "artifacts_count": len(task.artifacts or []),
                "shell_sessions_ativas": shells_ativas,
                "ultima_mensagem": ultima_assistente,
                "error": task.error,
            }

            await websocket.send_json(payload)
            return task

        while True:
            timeout = max(0.02, min(0.35, next_poll - time.monotonic()))
            try:
                item = await asyncio.wait_for(stream_q.get(), timeout=timeout)
                if isinstance(item, dict):
                    t = item.get("type") or ""
                    if t in (
                        "llm_stream_start",
                        "llm_delta",
                        "reasoning",
                        "tool_start",
                        "tool_result",
                        "shell_chunk",
                        "status",
                        "log",
                    ):
                        await websocket.send_json(item)
            except asyncio.TimeoutError:
                pass

            if time.monotonic() >= next_poll:
                task = await _poll_and_send()
                next_poll = time.monotonic() + poll_interval
                if task is None:
                    break
                if task.status in terminal_statuses:
                    # Drena TODOS os eventos pendentes na fila antes de encerrar
                    # (sem isso, eventos emitidos antes do break são perdidos)
                    while not stream_q.empty():
                        try:
                            pending = stream_q.get_nowait()
                            if isinstance(pending, dict):
                                pt = pending.get("type") or ""
                                if pt in (
                                    "llm_stream_start",
                                    "llm_delta",
                                    "reasoning",
                                    "tool_start",
                                    "tool_result",
                                    "shell_chunk",
                                    "status",
                                    "log",
                                ):
                                    await websocket.send_json(pending)
                        except asyncio.QueueEmpty:
                            break
                        except Exception:
                            break
                    # Envia snapshot final do estado da tarefa
                    await _poll_and_send()
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        db.close()
        try:
            await websocket.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════
# WebSocket: output de shell em tempo real
# ══════════════════════════════════════════════════════════

@router.websocket("/shell/{session_id}")
async def ws_shell_output(websocket: WebSocket, session_id: str):
    """
    Streama o output de um processo shell em background em tempo real.
    O cliente recebe cada chunk de output assim que é produzido.
    """
    await websocket.accept()
    try:
        shell_session = ShellService.get_session(session_id)
        if not shell_session:
            await websocket.send_json({
                "error": f"Sessão shell '{session_id}' não encontrada"
            })
            await websocket.close()
            return

        # Subscreve na fila de output
        queue = shell_session.subscribe()

        # Envia output já acumulado + novos chunks
        terminal_statuses = {"done", "error", "killed"}

        try:
            while True:
                try:
                    # Aguarda próximo chunk com timeout de 30s
                    chunk = await asyncio.wait_for(queue.get(), timeout=30.0)
                    await websocket.send_text(chunk)
                except asyncio.TimeoutError:
                    # Verifica se o processo ainda está rodando
                    if shell_session.status in terminal_statuses:
                        break
                    # Envia keepalive
                    await websocket.send_json({"keepalive": True, "status": shell_session.status})
                    continue

                # Verifica se terminou
                if shell_session.status in terminal_statuses and queue.empty():
                    # Envia status final
                    await websocket.send_json({
                        "done": True,
                        "status": shell_session.status,
                        "exit_code": shell_session.exit_code,
                    })
                    break

        finally:
            shell_session.unsubscribe(queue)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
