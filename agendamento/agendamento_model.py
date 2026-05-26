"""
Modelo de dados para tarefas agendadas (heartbeat / lembretes / verificações).
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.sql import func
from database import Base
from enum import Enum


class TipoAgendamento(str, Enum):
    """Como o disparo é calculado."""
    ONCE = "once"          # uma vez, em data/hora absoluta
    INTERVAL = "interval"  # repete a cada N segundos
    CRON = "cron"          # expressão cron


class AcaoAgendamento(str, Enum):
    """O que executar quando dispara."""
    ENVIAR_MENSAGEM = "enviar_mensagem"        # manda texto direto ao telefone
    RODAR_FERRAMENTA = "rodar_ferramenta"      # executa ferramenta cadastrada
    CALLBACK_AGENTE = "callback_agente"        # re-injeta um prompt no agente


class StatusAgendamento(str, Enum):
    PENDENTE = "pendente"
    EXECUTANDO = "executando"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"
    CANCELADA = "cancelada"


class TarefaAgendada(Base):
    """Tarefa que o scheduler (APScheduler) vai disparar no momento certo."""
    __tablename__ = "tarefas_agendadas"

    id = Column(Integer, primary_key=True, index=True)

    titulo = Column(String(200), nullable=False, default="Tarefa agendada")
    descricao = Column(Text, nullable=True)

    sessao_id = Column(Integer, ForeignKey("sessoes.id", ondelete="SET NULL"), nullable=True, index=True)
    agente_id = Column(Integer, ForeignKey("agentes.id", ondelete="SET NULL"), nullable=True, index=True)
    telefone_destino = Column(String(50), nullable=True, index=True)

    tipo = Column(SQLEnum(TipoAgendamento), nullable=False, default=TipoAgendamento.ONCE)
    # ONCE: ISO timestamp (ex: "2026-05-27T09:00:00")
    # INTERVAL: segundos (ex: "300")
    # CRON: expressão (ex: "0 9 * * *")
    quando = Column(String(200), nullable=False)

    acao = Column(SQLEnum(AcaoAgendamento), nullable=False)
    # JSON com parâmetros da ação:
    #   enviar_mensagem: {"texto": "..."}
    #   rodar_ferramenta: {"nome_ferramenta": "...", "argumentos": {...}}
    #   callback_agente: {"prompt": "..."}
    payload_json = Column(Text, nullable=True)

    status = Column(SQLEnum(StatusAgendamento), nullable=False, default=StatusAgendamento.PENDENTE)
    resultado = Column(Text, nullable=True)
    erro = Column(Text, nullable=True)

    proxima_execucao = Column(DateTime(timezone=True), nullable=True)
    ultima_execucao = Column(DateTime(timezone=True), nullable=True)
    total_execucoes = Column(Integer, nullable=False, default=0)
    max_execucoes = Column(Integer, nullable=True)  # None = ilimitado (para interval/cron)

    job_id = Column(String(100), nullable=True, unique=True)  # ID no APScheduler

    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<TarefaAgendada(id={self.id}, titulo='{self.titulo}', tipo={self.tipo}, status={self.status})>"
