"""Models de audit imutavel.

Regra: linha nunca eh editada apos commit, exceto `resolvido_em` (admin
marca quando inspecionou). Sem `updated_at`. Sem hard delete (mesmo pra
testes, prefira filtrar). Sem soft delete (a tabela inteira eh o registro
historico).
"""
from __future__ import annotations

from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.sql import func

from database import Base


class TipoFalha(str, PyEnum):
    """Categoria semantica da falha. Driva politica de retry/alerta.

    Proveniencia: derivado da hierarquia FluxiError + categorias de tool.
    Revisar quando aparecer 5+ falhas no bucket `outros` em uma semana
    (sinal de que uma categoria nova deveria existir).
    """

    llm = "llm"             # chamada ao provedor falhou
    tool = "tool"           # ferramenta (sandbox/MCP/regular) falhou
    canal = "canal"         # neonize/telegram falhou no envio/recebimento
    pipeline = "pipeline"   # erro no orquestrador (db, parsing, validacao)
    outros = "outros"       # nao classificado — devera virar categoria nova


class AgentFailure(Base):
    """Audit imutavel de falha no pipeline de IA.

    Toda excecao que chega ao supervisor do MensagemFallbackService grava
    aqui. Eh a fonte de verdade pro diagnostico de "o agente nao respondeu"
    — sem isso, falhas viram log perdido.
    """

    __tablename__ = "agent_failures"
    __table_args__ = (
        Index("ix_agent_failure_sessao_criado", "sessao_id", "criado_em"),
        Index("ix_agent_failure_chat_criado", "chat_id", "criado_em"),
        Index("ix_agent_failure_tipo_criado", "tipo", "criado_em"),
        Index("ix_agent_failure_nao_resolvido", "resolvido_em"),  # parcial-friendly
    )

    id = Column(Integer, primary_key=True, index=True)

    # Ownership/escopo — sessao_id sempre presente; outros opcionais.
    sessao_id = Column(
        Integer,
        ForeignKey("sessoes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mensagem_id = Column(
        Integer,
        ForeignKey("mensagens.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agente_id = Column(
        Integer,
        ForeignKey("agentes.id", ondelete="SET NULL"),
        nullable=True,
    )
    chat_id = Column(String(100), nullable=True, index=True)

    # Categoria semantica — driva alertas e politica.
    tipo = Column(SAEnum(TipoFalha, name="tipo_falha"), nullable=False, default=TipoFalha.outros)

    # Identificacao da excecao real (pra agregacao em metricas).
    exception_class = Column(String(100), nullable=False)
    # `code` do FluxiError quando aplicavel (ex "llm.failed", "rate_limit.exceeded").
    # NULL quando a excecao nao eh FluxiError (ex: TimeoutError nativo).
    exception_code = Column(String(80), nullable=True, index=True)

    # Mensagem humana — pode ter PII, tratamos como sensivel.
    mensagem_erro = Column(Text, nullable=False)
    # Traceback completo. NULL pra erros "esperados" (recuperaveis); preenchido
    # pra imprevistos (mais util pra debug).
    traceback = Column(Text, nullable=True)

    # Contexto serializado — FluxiError.to_dict() + dados do pipeline (modelo,
    # tool, args). JSON nativo, NAO string-com-estrutura.
    payload = Column(JSON, nullable=True)

    # Quantas tentativas o supervisor fez antes de marcar como falha.
    tentativas = Column(Integer, nullable=False, default=1)

    # Timestamps.
    criado_em = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    # Unica coluna mutavel — admin marca quando inspecionou/resolveu.
    resolvido_em = Column(DateTime(timezone=True), nullable=True)
    resolvido_por = Column(String(120), nullable=True)  # email do admin
    resolucao_nota = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AgentFailure(id={self.id}, tipo={self.tipo}, "
            f"exception={self.exception_class}, sessao={self.sessao_id})>"
        )
