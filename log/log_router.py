"""
Rotas da API REST para o sistema de logging.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from log.log_service import LogService
from log.log_schema import LogFilterParams

router = APIRouter(prefix="/api/logs", tags=["Logs"])


@router.get("/")
def listar_logs(
    module: Optional[str] = Query(None),
    sub_module: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    session_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Lista entradas de log com filtros e paginação."""
    filtros = LogFilterParams(
        module=module,
        sub_module=sub_module,
        level=level,
        search=search,
        session_id=session_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        per_page=per_page,
    )
    entries, total = LogService.listar(db, filtros)
    pages = (total + per_page - 1) // per_page if per_page > 0 else 1

    return {
        "entries": [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "level": e.level,
                "module": e.module,
                "sub_module": e.sub_module,
                "message": e.message,
                "extra_json": e.extra_json,
                "traceback": e.traceback,
                "session_id": e.session_id,
                "request_id": e.request_id,
            }
            for e in entries
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


@router.get("/stats")
def obter_stats(db: Session = Depends(get_db)):
    """Estatísticas globais de logs."""
    return LogService.obter_stats(db)


@router.get("/stats/{module}")
def obter_stats_modulo(module: str, db: Session = Depends(get_db)):
    """Estatísticas de um módulo específico."""
    return LogService.obter_stats_por_modulo(db, module)


@router.get("/sub-modules/{module}")
def obter_sub_modulos(module: str, db: Session = Depends(get_db)):
    """Lista sub-módulos distintos de um módulo."""
    return LogService.obter_sub_modulos(db, module)


@router.delete("/limpar")
def limpar_logs(dias: int = Query(30, ge=1), db: Session = Depends(get_db)):
    """Remove logs mais antigos que N dias."""
    count = LogService.limpar_antigos(db, dias)
    return {"removidos": count, "dias": dias}
