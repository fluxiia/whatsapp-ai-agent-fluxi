"""
Frontend router do sandbox interno.
Fornece a interface web com terminal (xterm.js) e visualizador de browser.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from internal_sandbox.shell_service import ShellService
from internal_sandbox.browser_service import InternalBrowserService
from internal_sandbox import code_service as CodeService

router = APIRouter(prefix="/internal-sandbox", tags=["internal-sandbox"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "internal_sandbox/index.html",
        {"request": request, "titulo": "Sandbox Interno"},
    )


# ── API: Shell ─────────────────────────────────────────────────────

@router.get("/api/sessions")
async def list_sessions():
    return {"sessions": ShellService.list_sessions()}


@router.post("/api/shell/exec")
async def shell_exec(request: Request):
    body = await request.json()
    result = await ShellService.exec_command(
        command=body["command"],
        exec_dir=body.get("exec_dir"),
        timeout=body.get("timeout"),
        background=body.get("background", True),
    )
    return result


@router.get("/api/shell/{session_id}")
async def shell_view(session_id: str):
    return ShellService.view_session(session_id)


@router.post("/api/shell/{session_id}/write")
async def shell_write(session_id: str, request: Request):
    body = await request.json()
    return await ShellService.write_to_session(
        session_id=session_id,
        input_text=body.get("input", ""),
        press_enter=body.get("press_enter", True),
    )


@router.delete("/api/shell/{session_id}")
async def shell_kill(session_id: str):
    return await ShellService.kill_session(session_id)


# ── API: Browser ───────────────────────────────────────────────────

@router.get("/api/browser/{agente_id}/info")
async def browser_info(agente_id: int):
    try:
        bsvc = InternalBrowserService.obter_instancia(agente_id)
        await bsvc._ensure_connected()
        page = await bsvc._page_atual()
        return {
            "connected": True,
            "url": page.url,
            "title": await page.title(),
            "headless": bsvc._headless,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.post("/api/browser/{agente_id}/navigate")
async def browser_navigate(agente_id: int, request: Request):
    body = await request.json()
    bsvc = InternalBrowserService.obter_instancia(agente_id)
    return await bsvc.navigate(url=body["url"])


@router.post("/api/browser/{agente_id}/close")
async def browser_close(agente_id: int):
    InternalBrowserService.remover_instancia(agente_id)
    return {"success": True, "message": f"Browser do agente {agente_id} fechado"}


# ── API: Jupyter sessions ──────────────────────────────────────────

@router.get("/api/jupyter/sessions")
async def jupyter_sessions():
    return {"sessions": CodeService.list_python_sessions()}


@router.delete("/api/jupyter/{session_id}")
async def jupyter_delete(session_id: str):
    deleted = CodeService.delete_python_session(session_id)
    return {"success": deleted}
