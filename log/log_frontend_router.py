"""
Rotas do frontend para o sistema de logging.
"""
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from log.log_service import LogService
from log.log_schema import LogFilterParams, LogModule

router = APIRouter(tags=["Frontend - Logs"])
templates = Jinja2Templates(directory="templates")

# Mapeamento módulo → ícone Font Awesome
MODULE_ICONS = {
    "agente": "fa-robot",
    "mensagem": "fa-envelope",
    "coding": "fa-code",
    "ferramenta": "fa-tools",
    "sessao": "fa-plug",
    "llm": "fa-brain",
    "rag": "fa-database",
    "mcp": "fa-server",
    "skill": "fa-magic",
    "sandbox": "fa-terminal",
    "sistema": "fa-cog",
}

# Lista ordenada de módulos para as abas
MODULES_ORDER = [
    "agente", "mensagem", "coding", "ferramenta", "sessao",
    "llm", "rag", "mcp", "skill", "sandbox", "sistema",
]


@router.get("/logs", response_class=HTMLResponse)
def pagina_logs(
    request: Request,
    module: Optional[str] = Query(None),
    sub_module: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    """Página principal de logs com abas por módulo."""
    filtros = LogFilterParams(
        module=module,
        sub_module=sub_module,
        level=level,
        search=search,
        page=page,
        per_page=50,
    )
    entries, total = LogService.listar(db, filtros)
    pages = (total + 50 - 1) // 50 if total > 0 else 1

    stats = LogService.obter_stats(db)

    # Sub-módulos do módulo ativo (para dropdown de filtro)
    sub_modules = []
    if module:
        sub_modules = LogService.obter_sub_modulos(db, module)

    return templates.TemplateResponse("log/lista.html", {
        "request": request,
        "entries": entries,
        "total": total,
        "page": page,
        "pages": pages,
        "stats": stats,
        "errors_by_module": stats.get("errors_by_module", {}),
        "module_ativo": module,
        "sub_module_ativo": sub_module,
        "level_ativo": level,
        "search_ativo": search or "",
        "sub_modules": sub_modules,
        "modules_order": MODULES_ORDER,
        "module_icons": MODULE_ICONS,
        "titulo": "Logs do Sistema",
    })
