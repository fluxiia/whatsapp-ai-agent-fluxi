"""
Router frontend para tarefas agendadas.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from agendamento.agendamento_model import AcaoAgendamento, TipoAgendamento
from agendamento.agendamento_schema import TarefaAgendadaCriar
from agendamento.agendamento_service import AgendamentoService
from sessao.sessao_service import SessaoService

router = APIRouter(tags=["Agendamentos Frontend"])
templates = Jinja2Templates(directory="templates")


@router.get("/agendamentos", response_class=HTMLResponse)
def listar_agendamentos_page(request: Request, db: Session = Depends(get_db)):
    tarefas = AgendamentoService.listar(db)
    return templates.TemplateResponse(
        "agendamento/lista.html",
        {"request": request, "tarefas": tarefas, "titulo": "Agendamentos"},
    )


@router.get("/agendamentos/novo", response_class=HTMLResponse)
def novo_agendamento_page(request: Request, db: Session = Depends(get_db)):
    sessoes = SessaoService.listar_todas(db)
    return templates.TemplateResponse(
        "agendamento/form.html",
        {"request": request, "sessoes": sessoes, "titulo": "Novo agendamento"},
    )


@router.post("/agendamentos/criar")
def criar_agendamento_form(
    titulo: str = Form(...),
    descricao: Optional[str] = Form(None),
    sessao_id: Optional[int] = Form(None),
    telefone_destino: Optional[str] = Form(None),
    agente_id: Optional[int] = Form(None),
    tipo: str = Form("once"),
    quando: str = Form(...),
    acao: str = Form(...),
    payload_json: Optional[str] = Form(None),
    max_execucoes: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        payload = None
        if payload_json and payload_json.strip():
            payload = json.loads(payload_json)
        dados = TarefaAgendadaCriar(
            titulo=titulo.strip(),
            descricao=(descricao or None),
            sessao_id=sessao_id or None,
            agente_id=agente_id or None,
            telefone_destino=(telefone_destino or None),
            tipo=TipoAgendamento(tipo),
            quando=quando.strip(),
            acao=AcaoAgendamento(acao),
            payload=payload,
            max_execucoes=max_execucoes or None,
        )
        AgendamentoService.criar(db, dados)
        return RedirectResponse(url="/agendamentos?sucesso=Tarefa agendada", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/agendamentos/novo?erro={e}", status_code=303)


@router.post("/agendamentos/{tarefa_id}/cancelar")
def cancelar_agendamento_form(tarefa_id: int, db: Session = Depends(get_db)):
    AgendamentoService.cancelar(db, tarefa_id)
    return RedirectResponse(url="/agendamentos?sucesso=Tarefa cancelada", status_code=303)


@router.post("/agendamentos/{tarefa_id}/deletar")
def deletar_agendamento_form(tarefa_id: int, db: Session = Depends(get_db)):
    AgendamentoService.deletar(db, tarefa_id)
    return RedirectResponse(url="/agendamentos?sucesso=Tarefa removida", status_code=303)


@router.post("/agendamentos/{tarefa_id}/disparar")
async def disparar_agendamento_form(tarefa_id: int, db: Session = Depends(get_db)):
    resultado = await AgendamentoService.disparar_agora(db, tarefa_id)
    msg = "Tarefa disparada" if resultado.get("executada") else f"Falha: {resultado.get('erro', 'desconhecida')}"
    return RedirectResponse(url=f"/agendamentos?sucesso={msg}", status_code=303)
