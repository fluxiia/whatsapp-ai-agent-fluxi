"""
ShellService — Execução de comandos shell internamente (sem AIO Sandbox).
Gerencia sessões de shell usando asyncio.subprocess com streaming de output.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ShellSession:
    """Representa uma sessão shell ativa."""

    def __init__(self, session_id: str, command: str, cwd: str):
        self.id = session_id
        self.command = command
        self.cwd = cwd
        self.process: Optional[asyncio.subprocess.Process] = None
        self._output_chunks: List[str] = []
        self.exit_code: Optional[int] = None
        self.status: str = "running"
        self.started_at: float = time.time()
        self._output_task: Optional[asyncio.Task] = None
        self._ws_queues: List[asyncio.Queue] = []

    def _push(self, text: str):
        self._output_chunks.append(text)
        for q in list(self._ws_queues):
            try:
                q.put_nowait(text)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._ws_queues.append(q)
        for chunk in self._output_chunks:
            try:
                q.put_nowait(chunk)
            except asyncio.QueueFull:
                break
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._ws_queues.remove(q)
        except ValueError:
            pass

    def get_output(self) -> str:
        return "".join(self._output_chunks)


class ShellService:
    """Gerencia sessões shell internas via asyncio.subprocess."""

    _sessions: Dict[str, ShellSession] = {}

    DEFAULT_CWD: str = os.environ.get(
        "INTERNAL_SANDBOX_CWD",
        os.path.join(os.path.expanduser("~"), "fluxi_sandbox"),
    )

    @classmethod
    def _ensure_cwd(cls, cwd: str) -> str:
        os.makedirs(cwd, exist_ok=True)
        return cwd

    @classmethod
    def get_session(cls, session_id: str) -> Optional[ShellSession]:
        return cls._sessions.get(session_id)

    @classmethod
    def list_sessions(cls) -> List[Dict[str, Any]]:
        return [
            {
                "id": s.id,
                "command": s.command,
                "status": s.status,
                "exit_code": s.exit_code,
                "output_lines": s.get_output().count("\n"),
                "cwd": s.cwd,
                "age_s": round(time.time() - s.started_at, 1),
            }
            for s in cls._sessions.values()
        ]

    @classmethod
    async def exec_command(
        cls,
        command: str,
        exec_dir: Optional[str] = None,
        timeout: Optional[float] = None,
        background: bool = False,
    ) -> Dict[str, Any]:
        """
        Executa um comando shell.
        """
        session_id = uuid.uuid4().hex[:8]
        cwd = cls._ensure_cwd(exec_dir or cls.DEFAULT_CWD)
        logger.debug("[SHELL %s] cmd=%s cwd=%s bg=%s", session_id[:8], command[:80], cwd, background)

        session = ShellSession(session_id=session_id, command=command, cwd=cwd)
        cls._sessions[session_id] = session

        try:
            actual_command = command
            env = {**os.environ, "TERM": "xterm-256color", "PYTHONUNBUFFERED": "1"}

            try:
                process = await asyncio.create_subprocess_shell(
                    actual_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                )
                logger.info("[SHELL %s] Processo %s iniciado: %s", session_id[:8], process.pid, command[:80])
            except Exception as e:
                logger.warning("[SHELL %s] Falha no spawn direto: %s", session_id[:8], e)
                if sys.platform == "win32":
                    process = await asyncio.create_subprocess_shell(
                        f'cmd /c "{actual_command}"',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        stdin=asyncio.subprocess.PIPE,
                        cwd=cwd,
                        env=env,
                    )
                    logger.info("[SHELL %s] Fallback cmd /c iniciado", session_id[:8])
                else:
                    raise e

            session.process = process

            async def _read_output():
                """Lê output do processo com timeout por chunk — evita zumbi infinito."""
                assert process.stdout
                # Contador de timeouts consecutivos sem dados
                idle_ticks = 0
                # Cada tick = 30s; após 10 ticks sem dados E processo não terminou → mata
                _MAX_IDLE_TICKS = 10
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            process.stdout.read(4096), timeout=30.0
                        )
                        if not chunk:
                            break
                        idle_ticks = 0
                        session._push(chunk.decode("utf-8", errors="replace"))
                    except asyncio.TimeoutError:
                        # Sem dados por 30s — verifica se processo ainda vive
                        if process.returncode is not None:
                            break  # processo já terminou
                        idle_ticks += 1
                        if idle_ticks >= _MAX_IDLE_TICKS:
                            logger.warning(
                                "[SHELL %s] Processo sem output por %ds — interrompendo",
                                session_id[:8], idle_ticks * 30,
                            )
                            try:
                                process.kill()
                            except Exception:
                                pass
                            session._push(
                                f"\n[SHELL] Processo encerrado por inatividade ({idle_ticks * 30}s sem output)\n"
                            )
                            break
                    except Exception:
                        break

            output_task = asyncio.create_task(_read_output())
            session._output_task = output_task

            if background:
                asyncio.create_task(_finalize(session, output_task))
                return {
                    "session_id": session_id,
                    "status": "running",
                    "message": (
                        f"Processo iniciado em background. "
                        f"Use sandbox_shell_view com id='{session_id}' para ver o output."
                    ),
                }

            try:
                if timeout:
                    await asyncio.wait_for(process.wait(), timeout=timeout)
                else:
                    await process.wait()

                await output_task
                session.exit_code = process.returncode
                session.status = "done"

            except asyncio.TimeoutError:
                session.status = "running"
                return {
                    "session_id": session_id,
                    "status": "running",
                    "output": session.get_output(),
                    "message": (
                        f"Timeout de {timeout}s atingido. Processo ainda em execução. "
                        f"Use sandbox_shell_view com id='{session_id}' para acompanhar."
                    ),
                }

            return {
                "output": session.get_output(),
                "exit_code": session.exit_code,
                "status": session.status,
                "session_id": session_id,
            }

        except Exception as e:
            import traceback
            error_details = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            logger.exception("[SHELL %s] Erro crítico no spawn: %s", session_id[:8], e)
            session.status = "error"
            session.exit_code = -1
            return {
                "output": f"Erro ao iniciar shell: {type(e).__name__}: {str(e)[:300]}",
                "exit_code": -1,
                "status": "error",
                "session_id": session_id,
            }

    @classmethod
    def view_session(cls, session_id: str) -> Dict[str, Any]:
        session = cls.get_session(session_id)
        if not session:
            return {"error": f"Sessão '{session_id}' não encontrada"}
        return {
            "output": session.get_output(),
            "status": session.status,
            "exit_code": session.exit_code,
            "session_id": session_id,
        }

    @classmethod
    async def write_to_session(
        cls, session_id: str, input_text: str, press_enter: bool = True
    ) -> Dict[str, Any]:
        session = cls.get_session(session_id)
        if not session or not session.process:
            return {"success": False, "error": f"Sessão '{session_id}' não encontrada ou encerrada"}
        try:
            text = input_text + ("\n" if press_enter else "")
            assert session.process.stdin
            session.process.stdin.write(text.encode())
            await session.process.stdin.drain()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    async def kill_session(cls, session_id: str) -> Dict[str, Any]:
        session = cls.get_session(session_id)
        if not session:
            return {"success": False, "error": f"Sessão '{session_id}' não encontrada"}
        if session.process:
            try:
                session.process.kill()
            except Exception:
                pass
        session.status = "killed"
        session.exit_code = -9
        cls._sessions.pop(session_id, None)
        return {"success": True, "message": f"Processo {session_id} terminado"}

    @classmethod
    async def wait_session(
        cls, session_id: str, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        session = cls.get_session(session_id)
        if not session:
            return {"error": f"Sessão '{session_id}' não encontrada"}
        if session.status == "done":
            return {
                "output": session.get_output(),
                "exit_code": session.exit_code,
                "status": session.status,
            }
        if not session.process:
            return {"error": "Processo não iniciado"}
        try:
            if timeout:
                await asyncio.wait_for(session.process.wait(), timeout=timeout)
            else:
                await session.process.wait()
            session.exit_code = session.process.returncode
            session.status = "done"
        except asyncio.TimeoutError:
            pass
        return {
            "output": session.get_output(),
            "exit_code": session.exit_code,
            "status": session.status,
        }


async def _finalize(session: ShellSession, output_task: asyncio.Task):
    """Aguarda processo terminar em background e atualiza status."""
    try:
        await output_task
        if session.process:
            await session.process.wait()
            session.exit_code = session.process.returncode
        session.status = "done"
    except Exception:
        session.status = "error"
