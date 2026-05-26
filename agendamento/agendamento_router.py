"""
Rotas da API para tarefas agendadas.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db
from agendamento.agendamento_schema import TarefaAgendadaCriar, TarefaAgendadaResposta
from agendamento.agendamento_service import AgendamentoService
from agendamento.agendamento_model import StatusAgendamento

router = APIRouter(prefix="/api/agendamentos", tags=["Agendamentos"])


@router.get("/", response_model=List[TarefaAgendadaResposta])
def listar(
    status: Optional[StatusAgendamento] = Query(None),
    telefone: Optional[str] = Query(None),
    sessao_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    return AgendamentoService.listar(db, status=status, telefone=telefone, sessao_id=sessao_id)


@router.get("/{tarefa_id}", response_model=TarefaAgendadaResposta)
def obter(tarefa_id: int, db: Session = Depends(get_db)):
    tarefa = AgendamentoService.obter_por_id(db, tarefa_id)
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return tarefa


@router.post("/", response_model=TarefaAgendadaResposta)
def criar(dados: TarefaAgendadaCriar, db: Session = Depends(get_db)):
    try:
        return AgendamentoService.criar(db, dados)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{tarefa_id}/cancelar")
def cancelar(tarefa_id: int, db: Session = Depends(get_db)):
    if not AgendamentoService.cancelar(db, tarefa_id):
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return {"mensagem": "Tarefa cancelada"}


@router.post("/{tarefa_id}/disparar")
async def disparar_agora(tarefa_id: int, db: Session = Depends(get_db)):
    """Força execução imediata da tarefa (útil pra teste sem esperar o horário)."""
    resultado = await AgendamentoService.disparar_agora(db, tarefa_id)
    if resultado.get("erro") == "Tarefa não encontrada":
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return resultado


@router.delete("/{tarefa_id}")
def deletar(tarefa_id: int, db: Session = Depends(get_db)):
    if not AgendamentoService.deletar(db, tarefa_id):
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return {"mensagem": "Tarefa removida"}
