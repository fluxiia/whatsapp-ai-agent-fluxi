"""
Interface comum para canais de comunicação (WhatsApp, Telegram).

Toda a lógica do agente, mensagens e sessões fala com `CanalClient`, nunca
com a lib de plataforma direto. Adaptadores específicos vivem em
canal_whatsapp.py e canal_telegram.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol, runtime_checkable


class Plataforma(str, Enum):
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    WEBCHAT = "webchat"


class StatusConexao(str, Enum):
    DESCONECTADO = "desconectado"
    INICIANDO = "iniciando"
    CONECTANDO_QR = "conectando_qr"
    CONECTADO = "conectado"
    ERRO = "erro"


class TipoMidia(str, Enum):
    TEXTO = "texto"
    IMAGEM = "imagem"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENTO = "documento"
    STICKER = "sticker"
    LOCALIZACAO = "localizacao"
    OUTRO = "outro"


@dataclass
class EventoMensagem:
    """Mensagem recebida normalizada — independente de plataforma."""

    plataforma: Plataforma
    sessao_id: int
    # Identificador único da mensagem na plataforma (msg_id WA, message_id TG).
    # Não é único globalmente no Telegram (incrementa por chat) — sempre
    # combine com chat_id pra dedup.
    mensagem_id_externo: str
    # Chat onde a mensagem foi recebida (telefone limpo no WA, chat_id no TG).
    chat_id: str
    # Identificador legível do remetente (telefone no WA, username/id no TG).
    remetente_id: str
    remetente_nome: Optional[str] = None
    tipo: TipoMidia = TipoMidia.TEXTO
    texto: str = ""
    # Conteúdo binário quando aplicável (áudio/imagem/vídeo/documento).
    midia_bytes: Optional[bytes] = None
    midia_mime: Optional[str] = None
    midia_nome: Optional[str] = None
    # Dados específicos da plataforma — uso restrito (logs, debug, fallback).
    raw: Any = None
    extras: dict = field(default_factory=dict)


@runtime_checkable
class CanalClient(Protocol):
    """Contrato comum a todos os adaptadores de canal.

    Adaptadores rodam em thread dedicada por sessão; chamadas síncronas
    (`enviar_*`) podem ser invocadas do MensagemService/AgenteService a partir
    de qualquer thread, e o adapter cuida de despachar pra própria thread/loop.
    """

    sessao_id: int
    plataforma: Plataforma

    def conectar(self) -> None:
        """Inicia conexão (gera QR no WA, abre polling no TG). Não bloqueia."""
        ...

    def desconectar(self) -> None:
        """Encerra conexão e libera recursos."""
        ...

    def esta_conectado(self) -> bool:
        ...

    def enviar_texto(self, chat_id: str, texto: str) -> bool:
        ...

    def enviar_imagem(
        self, chat_id: str, imagem_bytes: bytes, legenda: str = ""
    ) -> bool:
        ...

    def enviar_audio(
        self, chat_id: str, audio_bytes: bytes, ptt: bool = True
    ) -> bool:
        ...

    def enviar_video(
        self, chat_id: str, video_bytes: bytes, legenda: str = ""
    ) -> bool:
        ...

    def enviar_documento(
        self, chat_id: str, doc_bytes: bytes, nome_arquivo: str
    ) -> bool:
        ...


# Tipo dos callbacks que o adapter dispara — definido aqui pra evitar
# import circular. O adapter recebe ambos no __init__.
OnMensagem = Callable[[EventoMensagem], None]
OnStatus = Callable[[StatusConexao, Optional[str]], None]
