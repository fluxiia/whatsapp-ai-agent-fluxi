"""
Schemas Pydantic para tarefas agendadas.
"""
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict
from datetime import datetime

from agendamento.agendamento_model import TipoAgendamento, AcaoAgendamento, StatusAgendamento


class TarefaAgendadaBase(BaseModel):
    titulo: str = Field(..., max_length=200)
    descricao: Optional[str] = None
    sessao_id: Optional[int] = None
    agente_id: Optional[int] = None
    telefone_destino: Optional[str] = None
    tipo: TipoAgendamento = TipoAgendamento.ONCE
    quando: str = Field(..., description="ISO timestamp para once, segundos para interval, expressão cron para cron")
    acao: AcaoAgendamento
    payload: Optional[Dict[str, Any]] = Field(None, description="Parâmetros da ação")
    max_execucoes: Optional[int] = None


class TarefaAgendadaCriar(TarefaAgendadaBase):
    pass


class TarefaAgendadaResposta(BaseModel):
    id: int
    titulo: str
    descricao: Optional[str] = None
    sessao_id: Optional[int] = None
    agente_id: Optional[int] = None
    telefone_destino: Optional[str] = None
    tipo: TipoAgendamento
    quando: str
    acao: AcaoAgendamento
    payload_json: Optional[str] = None
    status: StatusAgendamento
    resultado: Optional[str] = None
    erro: Optional[str] = None
    proxima_execucao: Optional[datetime] = None
    ultima_execucao: Optional[datetime] = None
    total_execucoes: int
    max_execucoes: Optional[int] = None
    job_id: Optional[str] = None
    criado_em: datetime
    atualizado_em: Optional[datetime] = None

    class Config:
        from_attributes = True
