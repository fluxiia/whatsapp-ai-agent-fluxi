"""
Frontend routes do Coding Agent.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from coding_agent.coding_service import CodingService
from coding_agent.coding_memory import CodingMemoryService
from sessao.sessao_service import SessaoService

router = APIRouter(prefix="/coding", tags=["Frontend - Coding"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def pagina_coding_index(request: Request, db: Session = Depends(get_db)):
    """Lista todas as coding sessions com resumo de tarefas."""
    sessoes_wa = SessaoService.listar_todas(db)
    coding_sessions = CodingService.listar_sessoes(db)

    # Montar resumo por coding_session
    resumos = []
    for cs in coding_sessions:
        tarefas = CodingService.listar_tarefas(db, cs.id, limit=100)
        resumos.append({
            "cs": cs,
            "total": len(tarefas),
            "running": sum(1 for t in tarefas if t.status == "running"),
            "completed": sum(1 for t in tarefas if t.status == "completed"),
            "failed": sum(1 for t in tarefas if t.status == "failed"),
        })

    return templates.TemplateResponse("coding/index.html", {
        "request": request,
        "titulo": "Coding Agent",
        "sessoes_wa": sessoes_wa,
        "resumos": resumos,
        "breadcrumbs": [
            {"label": "Dashboard", "url": "/"},
            {"label": "Coding Agent"},
        ],
    })


@router.get("/sessao/{session_id}", response_class=HTMLResponse)
def pagina_coding_sessao(session_id: int, request: Request, db: Session = Depends(get_db)):
    """Detalhe de uma coding session: tarefas + editor de memória."""
    cs = CodingService.obter_sessao(db, session_id)
    if not cs:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": "Sessão de coding não encontrada",
            "titulo": "Erro",
        })

    tarefas = CodingService.listar_tarefas(db, session_id, limit=50)
    memoria = CodingMemoryService.ler(db, session_id)

    return templates.TemplateResponse("coding/sessao.html", {
        "request": request,
        "titulo": f"Coding — {cs.agente.nome if cs.agente else session_id}",
        "cs": cs,
        "tarefas": tarefas,
        "memoria": memoria,
        "breadcrumbs": [
            {"label": "Dashboard", "url": "/"},
            {"label": "Coding Agent", "url": "/coding"},
            {"label": cs.agente.nome if cs.agente else f"Sessão {session_id}"},
        ],
    })


@router.get("/chat/{session_id}", response_class=HTMLResponse)
def pagina_coding_chat(session_id: int, request: Request, db: Session = Depends(get_db)):
    cs = CodingService.obter_sessao(db, session_id)
    if not cs:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": "Sessão de coding não encontrada",
            "titulo": "Erro",
        })

    tarefas = CodingService.listar_tarefas(db, session_id, limit=50)

    return templates.TemplateResponse("coding/chat.html", {
        "request": request,
        "titulo": f"Chat — {cs.agente.nome if cs.agente else session_id}",
        "cs": cs,
        "tarefas": tarefas,
        "breadcrumbs": [
            {"label": "Dashboard", "url": "/"},
            {"label": "Coding Agent", "url": "/coding"},
            {"label": cs.agente.nome if cs.agente else f"Sessão {session_id}", "url": f"/coding/sessao/{session_id}"},
            {"label": "Chat"},
        ],
    })


@router.get("/tarefa/{task_id}", response_class=HTMLResponse)
def pagina_coding_tarefa(task_id: int, request: Request, db: Session = Depends(get_db)):
    """Detalhe de uma tarefa com output em tempo real via WebSocket."""
    task = CodingService.obter_tarefa(db, task_id)
    if not task:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": "Tarefa não encontrada",
            "titulo": "Erro",
        })

    cs = CodingService.obter_sessao(db, task.coding_session_id)

    return templates.TemplateResponse("coding/tarefa.html", {
        "request": request,
        "titulo": f"Tarefa — {task.titulo}",
        "task": task,
        "cs": cs,
        "breadcrumbs": [
            {"label": "Dashboard", "url": "/"},
            {"label": "Coding Agent", "url": "/coding"},
            {"label": cs.agente.nome if cs and cs.agente else "Sessão", "url": f"/coding/sessao/{task.coding_session_id}"},
            {"label": task.titulo},
        ],
    })
