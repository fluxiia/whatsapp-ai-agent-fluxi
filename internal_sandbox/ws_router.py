"""
WebSocket router do sandbox interno.
- /ws/internal-sandbox/terminal/{session_id} → streaming do terminal (xterm.js)
- /ws/internal-sandbox/browser/{agente_id}   → streaming de screenshots do browser
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from internal_sandbox.shell_service import ShellService
from internal_sandbox.browser_service import InternalBrowserService

router = APIRouter(prefix="/ws/internal-sandbox", tags=["internal-sandbox-ws"])


# ─── Terminal WebSocket ───────────────────────────────────────────

@router.websocket("/terminal/{session_id}")
async def ws_terminal(websocket: WebSocket, session_id: str):
    """
    Stream bidirecional de terminal.
    - Servidor → cliente: chunks de output (texto)
    - Cliente → servidor: JSON {"type": "input", "data": "texto\n"}
                          JSON {"type": "kill"}
    """
    await websocket.accept()
    session = ShellService.get_session(session_id)

    if not session:
        await websocket.send_json({"type": "error", "data": f"Sessão '{session_id}' não encontrada"})
        await websocket.close()
        return

    queue = session.subscribe()

    async def _send_output():
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=1.0)
                    await websocket.send_json({"type": "output", "data": chunk})
                except asyncio.TimeoutError:
                    # Enviar heartbeat e verificar se sessão terminou
                    if session.status in ("done", "killed", "error"):
                        await websocket.send_json({
                            "type": "exit",
                            "exit_code": session.exit_code,
                            "status": session.status,
                        })
                        return
        except Exception:
            pass

    send_task = asyncio.create_task(_send_output())

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "input":
                    data = msg.get("data", "")
                    await ShellService.write_to_session(session_id, data, press_enter=False)

                elif msg_type == "kill":
                    await ShellService.kill_session(session_id)
                    await websocket.send_json({"type": "exit", "exit_code": -9, "status": "killed"})
                    break

                elif msg_type == "resize":
                    pass

            except asyncio.TimeoutError:
                if session.status in ("done", "killed", "error"):
                    break
            except WebSocketDisconnect:
                break

    finally:
        send_task.cancel()
        session.unsubscribe(queue)


# ─── Browser Screenshot Stream WebSocket ─────────────────────────

@router.websocket("/browser/{agente_id}")
async def ws_browser(websocket: WebSocket, agente_id: int):
    """
    Stream de screenshots do browser (polling a cada 500ms).
    - Servidor → cliente: JSON {"type": "screenshot", "data": "<base64 PNG>", "url": "...", "title": "..."}
    - Cliente → servidor: JSON com ações do browser:
        {"type": "navigate", "url": "https://..."}
        {"type": "click", "x": 100, "y": 200}
        {"type": "scroll", "direction": "down"}
        {"type": "keypress", "key": "Enter"}
        {"type": "fill", "selector": "input", "text": "valor"}
    """
    await websocket.accept()
    bsvc = InternalBrowserService.obter_instancia(agente_id)
    last_url = ""
    last_title = ""
    screenshot_interval = 0.5  # segundos entre screenshots

    async def _send_screenshots():
        nonlocal last_url, last_title
        while True:
            try:
                await asyncio.sleep(screenshot_interval)
                try:
                    img_bytes = await asyncio.wait_for(bsvc.screenshot(), timeout=3.0)
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    page = await bsvc._page_atual()
                    cur_url = page.url
                    cur_title = await page.title()
                    await websocket.send_json({
                        "type": "screenshot",
                        "data": b64,
                        "url": cur_url,
                        "title": cur_title,
                        "changed": cur_url != last_url or cur_title != last_title,
                    })
                    last_url = cur_url
                    last_title = cur_title
                except Exception as e:
                    await websocket.send_json({"type": "error", "data": str(e)})
            except asyncio.CancelledError:
                return
            except Exception:
                return

    screenshot_task = asyncio.create_task(_send_screenshots())

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                msg = json.loads(raw)
                msg_type = msg.get("type")

                result: Any = {"success": True}

                if msg_type == "navigate":
                    result = await bsvc.navigate(url=msg["url"])

                elif msg_type == "click":
                    result = await bsvc.click(x=msg.get("x"), y=msg.get("y"), selector=msg.get("selector"))

                elif msg_type == "scroll":
                    result = await bsvc.scroll(direction=msg.get("direction", "down"), amount=msg.get("amount", 3))

                elif msg_type == "keypress":
                    result = await bsvc.press_key(key=msg.get("key", "Enter"))

                elif msg_type == "fill":
                    result = await bsvc.fill(text=msg.get("text", ""), selector=msg.get("selector"))

                elif msg_type == "get_page_state":
                    result = await bsvc.get_page_state()

                elif msg_type == "set_interval":
                    screenshot_interval = max(0.2, float(msg.get("interval", 0.5)))
                    result = {"success": True, "interval": screenshot_interval}

                await websocket.send_json({"type": "action_result", "action": msg_type, "result": result})

            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
            except WebSocketDisconnect:
                break

    finally:
        screenshot_task.cancel()
