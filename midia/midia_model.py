"""Modelo Midia — tracking de arquivos no FS local com TTL.

`media_id` é a chave externa estável que o agente/LLM enxerga:
- `s{sessao_id}_{chat_id_digits}_{origem}_{rand}` (inbound)
- `gen_{rand}` (gerada pelo agente/IA)
- `tratada_{rand}` (logo limpa, processada, etc.)

Cron `purgar_expiradas` deleta arquivo + linha onde `ttl_em < now`.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class OrigemMidia(str, PyEnum):
    upload = "upload"       # recebida do usuario via canal
    gerada = "gerada"       # gerada por IA/agente
    tratada = "tratada"     # processada (logo limpa, ajuste)
    baixada = "baixada"     # baixada de URL externa pelo agente


class VinculadaTipo(str, PyEnum):
    mensagem = "mensagem"   # vinculada a uma Mensagem especifica
    sessao = "sessao"       # vinculada a sessao (avatar, etc)
    agente = "agente"       # vinculada a agente (foto perfil, etc)
    rag = "rag"             # documento de RAG
    outros = "outros"


class Midia(Base):
    """Registro de arquivo armazenado no FS com TTL.

    `media_id` unique global — o agente referencia por string estavel.
    `sessao_id` faz papel de ownership (analogo a usuario_id no Brisa).
    """

    __tablename__ = "midias"
    __table_args__ = (
        Index("ix_midia_sessao_ttl", "sessao_id", "ttl_em"),
        Index("ix_midia_sessao_origem", "sessao_id", "origem"),
        Index("ix_midia_vinculada", "vinculada_tipo", "vinculada_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    sessao_id = Column(
        Integer, ForeignKey("sessoes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chat_id = Column(String(100), nullable=True, index=True)

    media_id = Column(String(120), unique=True, nullable=False, index=True)
    path = Column(String(500), nullable=False)
    mime = Column(String(80), nullable=False)
    tamanho_bytes = Column(Integer, nullable=False, default=0)

    origem = Column(SAEnum(OrigemMidia, name="origem_midia"), nullable=False, default=OrigemMidia.upload)
    vinculada_tipo = Column(SAEnum(VinculadaTipo, name="vinculada_tipo"), nullable=True)
    vinculada_id = Column(Integer, nullable=True)

    criada_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ttl_em = Column(DateTime(timezone=True), nullable=True, index=True)

    sessao = relationship("Sessao")

    def __repr__(self) -> str:
        return f"<Midia(media_id='{self.media_id}', mime='{self.mime}', tamanho={self.tamanho_bytes})>"
