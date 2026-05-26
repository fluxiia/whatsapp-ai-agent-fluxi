"""
Adapter WebChat.

Não há "conexão externa" — o canal está sempre disponível enquanto o serviço
roda. O adapter mantém uma fila de eventos por chat_id; endpoints SSE em
webchat/webchat_router.py consomem essas filas pra empurrar mensagens pro
browser do visitante.

Identidade do cliente = UUID gerado no browser (localStorage), enviado em
toda requisição. Múltiplos visitantes simultâneos, cada um com seu chat_id.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from typing import Dict, Optional

from canal.canal_base import (
    EventoMensagem,
    OnMensagem,
    OnStatus,
    Plataforma,
    StatusConexao,
)

logger = logging.getLogger(__name__)


class CanalWebChatClient:
    """Implementação de CanalClient para o web chat embutido.

    Não cria thread/loop próprio. As filas vivem no event loop do FastAPI
    (capturado em MensagemService.set_fastapi_loop). Operações de envio
    delegam pro loop quando chamadas de outras threads.
    """

    plataforma = Plataforma.WEBCHAT

    def __init__(
        self,
        sessao_id: int,
        on_mensagem: OnMensagem,
        on_status: OnStatus,
    ):
        self.sessao_id = sessao_id
        self._on_mensagem = on_mensagem
        self._on_status = on_status
        self._conectado: bool = False
        # chat_id (UUID do visitante) -> Queue de eventos JSON pra SSE.
        self._filas: Dict[str, asyncio.Queue] = {}
        # Quando a fila foi acessada por última vez (timestamp epoch).
        self._ultimo_acesso: Dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def qr_code(self) -> Optional[str]:
        return None

    def esta_conectado(self) -> bool:
        return self._conectado

    def conectar(self) -> None:
        """WebChat fica 'conectado' assim que o adapter é criado — não há
        handshake externo. O status reflete que o canal está pronto pra
        atender visitantes."""
        self._conectado = True
        self._on_status(StatusConexao.CONECTADO, "webchat")

    def desconectar(self) -> None:
        self._conectado = False
        with self._lock:
            self._filas.clear()
            self._ultimo_acesso.clear()
        self._on_status(StatusConexao.DESCONECTADO, None)

    # ----- API consumida pelo router SSE / endpoint de envio -----

    def obter_ou_criar_fila(self, chat_id: str) -> asyncio.Queue:
        with self._lock:
            fila = self._filas.get(chat_id)
            if fila is None:
                fila = asyncio.Queue()
                self._filas[chat_id] = fila
            self._ultimo_acesso[chat_id] = time.time()
            return fila

    def limpar_fila_inativa(self, chat_id: str) -> None:
        with self._lock:
            self._filas.pop(chat_id, None)
            self._ultimo_acesso.pop(chat_id, None)

    def coletar_filas_zumbis(self, timeout_segundos: int = 600) -> list[str]:
        """Lista chat_ids cujas filas não receberam acesso recentemente.
        Caller decide se chama limpar_fila_inativa em cada."""
        agora = time.time()
        com_timeout: list[str] = []
        with self._lock:
            for cid, ts in self._ultimo_acesso.items():
                if agora - ts > timeout_segundos:
                    com_timeout.append(cid)
        return com_timeout

    def despachar_evento_recebido(self, evento: EventoMensagem) -> None:
        """Chamado pelo router quando o browser envia uma mensagem.

        Reusa o callback on_mensagem padrão — daí em diante é o pipeline
        de MensagemService (igual WA/TG).
        """
        self._on_mensagem(evento)

    def empurrar_indicador_digitando(self, chat_id: str, ativo: bool) -> None:
        """Atalho pro frontend mostrar/esconder 'digitando...'."""
        self._enfileirar(chat_id, {"tipo": "digitando", "ativo": ativo})

    # ----- envio (interface CanalClient) -----

    def enviar_texto(self, chat_id: str, texto: str) -> bool:
        return self._enfileirar(chat_id, {"tipo": "texto", "texto": texto})

    def enviar_imagem(self, chat_id: str, imagem_bytes: bytes, legenda: str = "") -> bool:
        b64 = base64.b64encode(imagem_bytes).decode("ascii")
        return self._enfileirar(
            chat_id, {"tipo": "imagem", "base64": b64, "mime": "image/jpeg", "legenda": legenda}
        )

    def enviar_audio(self, chat_id: str, audio_bytes: bytes, ptt: bool = True) -> bool:
        b64 = base64.b64encode(audio_bytes).decode("ascii")
        return self._enfileirar(
            chat_id, {"tipo": "audio", "base64": b64, "mime": "audio/ogg", "ptt": ptt}
        )

    def enviar_video(self, chat_id: str, video_bytes: bytes, legenda: str = "") -> bool:
        b64 = base64.b64encode(video_bytes).decode("ascii")
        return self._enfileirar(
            chat_id, {"tipo": "video", "base64": b64, "mime": "video/mp4", "legenda": legenda}
        )

    def enviar_documento(self, chat_id: str, doc_bytes: bytes, nome_arquivo: str) -> bool:
        b64 = base64.b64encode(doc_bytes).decode("ascii")
        return self._enfileirar(
            chat_id,
            {"tipo": "documento", "base64": b64, "nome": nome_arquivo or "arquivo"},
        )

    # ----- internos -----

    def _enfileirar(self, chat_id: str, payload: dict) -> bool:
        """Coloca payload na fila do chat_id. Roda no event loop do FastAPI
        (capturado em MensagemService) pra Queue ser thread-safe."""
        from mensagem.mensagem_service import MensagemService

        fila = self.obter_ou_criar_fila(chat_id)
        loop = MensagemService._fastapi_loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(fila.put(payload), loop)
            return True
        # Fallback: a fila é asyncio.Queue, mas se não há loop, usar put_nowait
        # diretamente (funciona quando chamado da própria thread do loop).
        try:
            fila.put_nowait(payload)
            return True
        except Exception:
            logger.exception("WebChat[%s]: falha ao enfileirar evento", self.sessao_id)
            return False
