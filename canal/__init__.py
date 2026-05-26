"""Camada de abstração de canais de comunicação (WhatsApp, Telegram, ...)."""
from canal.canal_base import (
    CanalClient,
    EventoMensagem,
    Plataforma,
    StatusConexao,
    TipoMidia,
)

__all__ = [
    "CanalClient",
    "EventoMensagem",
    "Plataforma",
    "StatusConexao",
    "TipoMidia",
]
