"""
Adapter WhatsApp via Neonize.

Encapsula NewClient, eventos (QR, Connected, Message, LoggedOut, PairStatus) e
envio de mídia. Expõe interface CanalClient — o resto do sistema (sessao_service,
mensagem_service, agente_service) só fala com essa interface.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional

import segno
from neonize.client import NewClient
from neonize.events import (
    ConnectedEv,
    LoggedOutEv,
    MessageEv,
    PairStatusEv,
)
from neonize.utils import build_jid

from canal.canal_base import (
    CanalClient,
    EventoMensagem,
    OnMensagem,
    OnStatus,
    Plataforma,
    StatusConexao,
    TipoMidia,
)

logger = logging.getLogger(__name__)

# Tamanho máximo do dedup de msg_id por adapter.
_DEDUP_MAX_SIZE = 1000


class CanalWhatsAppClient:
    """Implementação de CanalClient para WhatsApp (neonize)."""

    plataforma = Plataforma.WHATSAPP

    def __init__(
        self,
        sessao_id: int,
        sessao_dir: str,
        on_mensagem: OnMensagem,
        on_status: OnStatus,
        history_sync_delay: int = 5,
    ):
        self.sessao_id = sessao_id
        self.sessao_dir = sessao_dir
        self._on_mensagem = on_mensagem
        self._on_status = on_status
        self._history_sync_delay = history_sync_delay

        self._cliente: Optional[NewClient] = None
        self._thread: Optional[threading.Thread] = None
        self._connected_at: float = 0.0
        self._telefone_pareado: Optional[str] = None
        self._qr_code: Optional[str] = None

        # Dedup local (neonize pode disparar o mesmo evento 2x).
        self._msg_ids: deque = deque(maxlen=_DEDUP_MAX_SIZE)
        self._msg_ids_set: set = set()
        self._msg_lock = threading.Lock()

    # ----- helpers -----

    @property
    def qr_code(self) -> Optional[str]:
        return self._qr_code

    @property
    def db_path(self) -> str:
        return os.path.join(self.sessao_dir, f"sessao_{self.sessao_id}.db")

    def esta_conectado(self) -> bool:
        return self._cliente is not None and self._connected_at > 0

    @staticmethod
    def _build_jid_from_chat_id(chat_id: str):
        """Aceita 'user@server' ou apenas 'user'. Default server = s.whatsapp.net."""
        limpo = str(chat_id).strip()
        if "@" in limpo:
            user, server = limpo.split("@", 1)
            user = user.split(":")[0]
            return build_jid(user, server)
        user = limpo.split(":")[0]
        return build_jid(user)

    def _dedup(self, msg_id: Optional[str]) -> bool:
        """Retorna True se mensagem é nova (deve processar); False se duplicada."""
        if not msg_id:
            return True
        with self._msg_lock:
            if msg_id in self._msg_ids_set:
                return False
            if len(self._msg_ids) == _DEDUP_MAX_SIZE:
                self._msg_ids_set.discard(self._msg_ids[0])
            self._msg_ids.append(msg_id)
            self._msg_ids_set.add(msg_id)
            return True

    # ----- compat shim: API antiga (jid neonize) que outros services ainda usam -----
    # Esses métodos delegam direto ao cliente neonize interno. À medida que
    # mensagem_service/agente_service forem refatorados pra usar enviar_*,
    # esses shims podem ser removidos.

    def send_message(self, jid, message: str):
        if not self._cliente:
            raise RuntimeError("Cliente WA não inicializado")
        return self._cliente.send_message(jid, message=message)

    def send_image(self, jid, file_bytes: bytes, caption: str = ""):
        if not self._cliente:
            raise RuntimeError("Cliente WA não inicializado")
        return self._cliente.send_image(jid, file_bytes, caption=caption)

    def send_audio(self, jid, file_bytes: bytes, ptt: bool = False):
        if not self._cliente:
            raise RuntimeError("Cliente WA não inicializado")
        return self._cliente.send_audio(jid, file_bytes, ptt=ptt)

    def send_video(self, jid, file_bytes: bytes, caption: str = ""):
        if not self._cliente:
            raise RuntimeError("Cliente WA não inicializado")
        return self._cliente.send_video(jid, file_bytes, caption=caption)

    def send_document(self, jid, file_bytes: bytes, **kwargs):
        if not self._cliente:
            raise RuntimeError("Cliente WA não inicializado")
        return self._cliente.send_file(jid, file_bytes, **kwargs)

    def send_file(self, jid, file_bytes: bytes, **kwargs):
        if not self._cliente:
            raise RuntimeError("Cliente WA não inicializado")
        return self._cliente.send_file(jid, file_bytes, **kwargs)

    def download_any(self, message):
        if not self._cliente:
            raise RuntimeError("Cliente WA não inicializado")
        return self._cliente.download_any(message)

    # ----- envio (interface CanalClient) -----

    def enviar_texto(self, chat_id: str, texto: str) -> bool:
        if not self._cliente:
            logger.warning("WA[%s]: cliente não inicializado", self.sessao_id)
            return False
        try:
            self._cliente.send_message(self._build_jid_from_chat_id(chat_id), message=texto)
            return True
        except Exception:
            logger.exception("WA[%s]: erro ao enviar texto", self.sessao_id)
            return False

    def enviar_imagem(self, chat_id: str, imagem_bytes: bytes, legenda: str = "") -> bool:
        if not self._cliente:
            return False
        try:
            self._cliente.send_image(
                self._build_jid_from_chat_id(chat_id),
                imagem_bytes,
                caption=legenda or "",
            )
            return True
        except Exception:
            logger.exception("WA[%s]: erro ao enviar imagem", self.sessao_id)
            return False

    def enviar_audio(self, chat_id: str, audio_bytes: bytes, ptt: bool = True) -> bool:
        if not self._cliente:
            return False
        try:
            self._cliente.send_audio(
                self._build_jid_from_chat_id(chat_id),
                audio_bytes,
                ptt=ptt,
            )
            return True
        except Exception:
            logger.exception("WA[%s]: erro ao enviar audio", self.sessao_id)
            return False

    def enviar_video(self, chat_id: str, video_bytes: bytes, legenda: str = "") -> bool:
        if not self._cliente:
            return False
        try:
            self._cliente.send_video(
                self._build_jid_from_chat_id(chat_id),
                video_bytes,
                caption=legenda or "",
            )
            return True
        except Exception:
            logger.exception("WA[%s]: erro ao enviar video", self.sessao_id)
            return False

    def enviar_documento(self, chat_id: str, doc_bytes: bytes, nome_arquivo: str) -> bool:
        if not self._cliente:
            return False
        try:
            # Neonize: usa send_file (genérico) para documentos.
            self._cliente.send_file(
                self._build_jid_from_chat_id(chat_id),
                doc_bytes,
            )
            return True
        except Exception:
            logger.exception("WA[%s]: erro ao enviar documento %s", self.sessao_id, nome_arquivo)
            return False

    # ----- conexão -----

    def conectar(self, *, reconectar: bool = False) -> None:
        """Cria NewClient, registra handlers e dispara connect() em thread."""
        if self._cliente is not None:
            logger.debug("WA[%s]: cliente já existe", self.sessao_id)
            return

        os.makedirs(self.sessao_dir, exist_ok=True)
        if reconectar and not os.path.exists(self.db_path):
            logger.warning(
                "WA[%s]: sem banco salvo em %s, não é possível reconectar",
                self.sessao_id,
                self.db_path,
            )
            self._on_status(StatusConexao.DESCONECTADO, "sem credenciais salvas")
            return

        logger.info(
            "WA[%s]: criando NewClient (db=%s, reconectar=%s)",
            self.sessao_id,
            self.db_path,
            reconectar,
        )
        cliente = NewClient(self.db_path)
        self._cliente = cliente
        self._registrar_handlers(cliente, reconectar=reconectar)

        def _conectar_thread():
            try:
                cliente.connect()
            except Exception:
                logger.exception("WA[%s]: erro em cliente.connect()", self.sessao_id)
                self._on_status(StatusConexao.ERRO, "falha em cliente.connect()")

        self._thread = threading.Thread(target=_conectar_thread, daemon=True)
        self._thread.start()
        self._on_status(StatusConexao.INICIANDO, None)

    def desconectar(self) -> None:
        """Limpa referência ao cliente. Neonize não tem disconnect explícito;
        a thread morre junto com o processo ou quando o socket é fechado."""
        self._cliente = None
        self._thread = None
        self._connected_at = 0.0
        self._qr_code = None
        self._on_status(StatusConexao.DESCONECTADO, None)

    # ----- handlers -----

    def _registrar_handlers(self, cliente: NewClient, *, reconectar: bool) -> None:
        sessao_id = self.sessao_id

        @cliente.qr
        def _qr_handler(_cli: NewClient, qr_data: bytes):
            if reconectar:
                logger.warning("WA[%s]: QR gerado durante reconexão (inesperado)", sessao_id)
                return
            try:
                qr_string = qr_data.decode("utf-8")
                qr = segno.make(qr_string)
                buf = io.BytesIO()
                qr.save(buf, kind="png", scale=8)
                buf.seek(0)
                self._qr_code = base64.b64encode(buf.read()).decode("utf-8")
                self._on_status(StatusConexao.CONECTANDO_QR, self._qr_code)
                logger.info("WA[%s]: QR Code gerado", sessao_id)
            except Exception:
                logger.exception("WA[%s]: erro ao processar QR", sessao_id)

        @cliente.event(PairStatusEv)
        def _on_pair(_cli: NewClient, event: PairStatusEv):
            if hasattr(event, "ID") and hasattr(event.ID, "User"):
                self._telefone_pareado = event.ID.User
                logger.info("WA[%s]: pareada", sessao_id)

        @cliente.event(ConnectedEv)
        def _on_connected(client: NewClient, _event: ConnectedEv):
            self._connected_at = time.time()
            telefone = self._telefone_pareado
            if not telefone:
                try:
                    if hasattr(client, "me") and client.me and hasattr(client.me, "User"):
                        telefone = client.me.User
                    if not telefone:
                        me_info = client.get_me()
                        if hasattr(me_info, "User"):
                            telefone = me_info.User
                except Exception as e:
                    logger.warning("WA[%s]: erro ao obter telefone do me: %s", sessao_id, e)
            self._qr_code = None
            # Reportar telefone via extras do status — quem assina decide gravar.
            self._on_status(StatusConexao.CONECTADO, telefone)

        @cliente.event(LoggedOutEv)
        def _on_logged_out(_cli: NewClient, event: LoggedOutEv):
            razao = event.Reason if hasattr(event, "Reason") else "desconhecida"
            logger.warning("WA[%s]: logout. Razão: %s", sessao_id, razao)
            self._cliente = None
            self._connected_at = 0.0
            self._on_status(StatusConexao.DESCONECTADO, f"logout: {razao}")
            # Remover arquivo de sessão local — pareamento foi invalidado.
            try:
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)
                    logger.info("WA[%s]: arquivo %s removido após logout", sessao_id, self.db_path)
            except Exception as e:
                logger.warning("WA[%s]: erro ao remover %s: %s", sessao_id, self.db_path, e)

        @cliente.event(MessageEv)
        def _on_message(_cli: NewClient, event: MessageEv):
            try:
                if hasattr(event.Info, "IsFromMe") and event.Info.IsFromMe:
                    return
                msg_id = getattr(event.Info, "ID", None)
                if not self._dedup(msg_id):
                    return
                if time.time() - self._connected_at < self._history_sync_delay:
                    logger.debug("WA[%s]: ignorada (history sync)", sessao_id)
                    return

                evento = self._construir_evento(event)
                self._on_mensagem(evento)
            except Exception:
                logger.exception("WA[%s]: erro no handler de mensagem", sessao_id)

    def _construir_evento(self, event: MessageEv) -> EventoMensagem:
        """Constrói EventoMensagem mantendo `raw=event` pra quem ainda usa
        protocolo neonize específico (mensagem_service hoje)."""
        info = event.Info
        message_source = info.MessageSource
        sender_jid = message_source.Sender

        # Telefone do cliente — mesma lógica do mensagem_service original.
        telefone_cliente: Optional[str] = None
        sender_alt = getattr(message_source, "SenderAlt", None)
        if sender_alt and getattr(sender_alt, "User", None):
            telefone_cliente = sender_alt.User
        else:
            chat_jid = getattr(info, "Chat", None)
            if chat_jid and getattr(chat_jid, "Server", None) == "s.whatsapp.net" and getattr(chat_jid, "User", None):
                telefone_cliente = chat_jid.User
            elif getattr(sender_jid, "Server", None) == "s.whatsapp.net" and getattr(sender_jid, "User", None):
                telefone_cliente = sender_jid.User
            elif getattr(sender_jid, "User", None):
                telefone_cliente = sender_jid.User
            else:
                telefone_cliente = str(sender_jid).split("@")[0]

        tipo = _detectar_tipo_wa(event.Message)
        msg_id = getattr(info, "ID", None) or ""

        return EventoMensagem(
            plataforma=Plataforma.WHATSAPP,
            sessao_id=self.sessao_id,
            mensagem_id_externo=str(msg_id),
            chat_id=str(telefone_cliente or ""),
            remetente_id=str(telefone_cliente or ""),
            remetente_nome=getattr(info, "PushName", None),
            tipo=tipo,
            raw=event,
        )


def _detectar_tipo_wa(message) -> TipoMidia:
    def tem_conteudo(campo) -> bool:
        if not campo:
            return False
        if hasattr(campo, "mimetype") and campo.mimetype:
            return True
        if hasattr(campo, "url") and campo.url:
            return True
        try:
            return campo.ByteSize() > 0
        except Exception:
            return bool(campo)

    if hasattr(message, "conversation") and message.conversation:
        return TipoMidia.TEXTO
    if hasattr(message, "extendedTextMessage") and tem_conteudo(message.extendedTextMessage):
        return TipoMidia.TEXTO
    if hasattr(message, "audioMessage") and tem_conteudo(message.audioMessage):
        return TipoMidia.AUDIO
    if hasattr(message, "imageMessage") and tem_conteudo(message.imageMessage):
        return TipoMidia.IMAGEM
    if hasattr(message, "videoMessage") and tem_conteudo(message.videoMessage):
        return TipoMidia.VIDEO
    if hasattr(message, "stickerMessage") and tem_conteudo(message.stickerMessage):
        return TipoMidia.STICKER
    if hasattr(message, "locationMessage") and tem_conteudo(message.locationMessage):
        return TipoMidia.LOCALIZACAO
    if hasattr(message, "documentMessage") and tem_conteudo(message.documentMessage):
        return TipoMidia.DOCUMENTO
    return TipoMidia.TEXTO


