"""Rotas: página HTML + endpoint JSON pro badge global."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from updates.updates_service import obter_release_remota, status

router = APIRouter(prefix="/atualizacoes", tags=["Atualizações"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def pagina_atualizacoes(request: Request):
    return templates.TemplateResponse(
        "updates/status.html",
        {
            "request": request,
            "status": status(),
            "titulo": "Atualizações",
        },
    )


@router.get("/api")
def api_status():
    """Lido pelo JS do header pra mostrar badge se há update."""
    return JSONResponse(status())


@router.post("/verificar")
def forcar_verificacao():
    """Ignora o cache e bate de novo no GitHub. Usado pelo botão da UI."""
    obter_release_remota(forcar=True)
    return JSONResponse(status())
