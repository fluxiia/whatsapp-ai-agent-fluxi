"""Cria o CanalClient adequado pra cada Sessao baseado em sessao.plataforma."""
from __future__ import annotations

import logging
from typing import Optional

from canal.canal_base import CanalClient, OnMensagem, OnStatus, Plataforma
from canal.canal_credenciais import descriptografar

logger = logging.getLogger(__name__)


def criar_canal(
    sessao,
    sessao_dir: str,
    on_mensagem: OnMensagem,
    on_status: OnStatus,
    history_sync_delay: int = 5,
) -> Optional[CanalClient]:
    """Retorna um CanalClient pronto pra conectar.

    Args:
        sessao: instância de Sessao (sqlalchemy model).
        sessao_dir: diretório onde adapters podem persistir estado (WA usa, TG não).
        on_mensagem: callback chamado com EventoMensagem ao receber mensagem.
        on_status: callback chamado com (StatusConexao, info_extra).
    """
    plataforma = (sessao.plataforma or "whatsapp").lower()

    if plataforma == Plataforma.WHATSAPP.value:
        from canal.canal_whatsapp import CanalWhatsAppClient
        return CanalWhatsAppClient(
            sessao_id=sessao.id,
            sessao_dir=sessao_dir,
            on_mensagem=on_mensagem,
            on_status=on_status,
            history_sync_delay=history_sync_delay,
        )

    if plataforma == Plataforma.TELEGRAM.value:
        from canal.canal_telegram import CanalTelegramClient
        creds = descriptografar(sessao.credenciais)
        bot_token = creds.get("bot_token")
        if not bot_token:
            logger.error(
                "Sessão %s (telegram) sem bot_token nas credenciais — não pode conectar.",
                sessao.id,
            )
            return None
        return CanalTelegramClient(
            sessao_id=sessao.id,
            bot_token=bot_token,
            on_mensagem=on_mensagem,
            on_status=on_status,
        )

    if plataforma == Plataforma.WEBCHAT.value:
        from canal.canal_webchat import CanalWebChatClient
        return CanalWebChatClient(
            sessao_id=sessao.id,
            on_mensagem=on_mensagem,
            on_status=on_status,
        )

    logger.error("Plataforma desconhecida em sessão %s: %s", sessao.id, plataforma)
    return None
