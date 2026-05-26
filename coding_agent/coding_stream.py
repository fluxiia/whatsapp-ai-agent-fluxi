"""
Bridge em memória entre o loop LLM (streaming) e o WebSocket /ws/coding/task/{id}.

Cada task_id tem uma fila asyncio; o produtor (background task) envia deltas de texto;
o consumidor (handler WebSocket) encaminha ao browser como JSON {type, text}.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_queues: Dict[int, asyncio.Queue] = {}
_queue_ts: Dict[int, float] = {}   # timestamp de criação/último uso

# Tamanho máximo da fila — aumentado para evitar drops em rafagas
_QUEUE_MAXSIZE = 1024
# TTL: queues sem acesso por mais de 2h são removidas pelo garbage collector
_QUEUE_TTL = 7200.0


def ensure_queue(task_id: int) -> asyncio.Queue:
    if task_id not in _queues:
        _queues[task_id] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _queue_ts[task_id] = time.monotonic()
    return _queues[task_id]


def _gc_old_queues() -> None:
    """Remove filas inativas há mais de _QUEUE_TTL segundos."""
    now = time.monotonic()
    stale = [tid for tid, ts in list(_queue_ts.items()) if now - ts > _QUEUE_TTL]
    for tid in stale:
        _queues.pop(tid, None)
        _queue_ts.pop(tid, None)
    if stale:
        logger.debug("[STREAM] GC removeu %d queues inativas", len(stale))


def _put_dropping_oldest(q: asyncio.Queue, item: dict) -> None:
    """Coloca item na fila; se cheia, descarta o item mais antigo para dar espaço."""
    try:
        q.put_nowait(item)
    except asyncio.QueueFull:
        try:
            q.get_nowait()  # descarta o mais antigo
            q.put_nowait(item)
        except Exception:
            logger.warning("[STREAM] QueueFull persistente — item descartado: type=%s", item.get("type"))


async def emit_llm_delta(task_id: int, text: str) -> None:
    if not text:
        return
    q = _queues.get(task_id)
    if not q:
        return
    _put_dropping_oldest(q, {"type": "llm_delta", "text": text})


async def emit_llm_stream_start(task_id: int) -> None:
    """Novo turno de geração (ex.: após tool calls) — o cliente cria novo bubble."""
    q = _queues.get(task_id)
    if not q:
        return
    _put_dropping_oldest(q, {"type": "llm_stream_start"})


async def emit_tool_start(task_id: int, tool_name: str, args: dict) -> None:
    q = _queues.get(task_id)
    if not q:
        return
    _put_dropping_oldest(q, {"type": "tool_start", "tool_name": tool_name, "args": args})


async def emit_tool_result(task_id: int, tool_name: str, result: str) -> None:
    q = _queues.get(task_id)
    if not q:
        return
    # Imagens (screenshots) precisam do base64 completo — não truncar
    import json as _json
    is_image = False
    try:
        parsed = _json.loads(result)
        is_image = isinstance(parsed, dict) and parsed.get("type") == "image"
    except Exception:
        pass
    payload = result if is_image else result[:8000]
    _put_dropping_oldest(q, {"type": "tool_result", "tool_name": tool_name, "result": payload})


async def emit_shell_chunk(task_id: int, session_id: str, text: str) -> None:
    """Encaminha chunk de output de shell background para o feed da tarefa."""
    if not text:
        return
    q = _queues.get(task_id)
    if not q:
        return
    _put_dropping_oldest(q, {"type": "shell_chunk", "session_id": session_id, "text": text})


async def emit_reasoning(task_id: int, reasoning: str) -> None:
    """Emite reasoning/thinking do modelo para o frontend."""
    if not reasoning:
        return
    q = _queues.get(task_id)
    if not q:
        logger.warning("[STREAM] emit_reasoning: sem queue para task_id=%d (reasoning=%d chars)", task_id, len(reasoning))
        return
    logger.info("[STREAM] emit_reasoning: task=%d, %d chars", task_id, len(reasoning))
    _put_dropping_oldest(q, {"type": "reasoning", "text": reasoning})


async def emit_status(task_id: int, message: str) -> None:
    """Mensagem de status/progresso genérica (ex: 'iteração 3/30')."""
    q = _queues.get(task_id)
    if not q:
        return
    _put_dropping_oldest(q, {"type": "status", "message": message})


def cleanup_queue(task_id: int) -> None:
    _queues.pop(task_id, None)
    _queue_ts.pop(task_id, None)
    # Aproveita o cleanup para remover filas antigas (GC oportunístico)
    _gc_old_queues()
