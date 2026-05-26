"""
Adapter Telegram via python-telegram-bot (v21+, async).

Cada sessão TG roda em sua própria thread com um event loop asyncio dedicado.
Long polling — sem necessidade de webhook/HTTPS público.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

from canal.canal_base import (
    EventoMensagem,
    OnMensagem,
    OnStatus,
    Plataforma,
    StatusConexao,
    TipoMidia,
)

logger = logging.getLogger(__name__)


class CanalTelegramClient:
    """Implementação de CanalClient para Telegram."""

    plataforma = Plataforma.TELEGRAM

    def __init__(
        self,
        sessao_id: int,
        bot_token: str,
        on_mensagem: OnMensagem,
        on_status: OnStatus,
    ):
        if not bot_token:
            raise ValueError("bot_token vazio")
        self.sessao_id = sessao_id
        self._bot_token = bot_token
        self._on_mensagem = on_mensagem
        self._on_status = on_status

        self._app: Optional[Application] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._connected: bool = False
        self._loop_ready = threading.Event()

    def esta_conectado(self) -> bool:
        return self._connected

    # ----- conexão -----

    def conectar(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.debug("TG[%s]: thread já viva", self.sessao_id)
            return
        self._on_status(StatusConexao.INICIANDO, None)
        self._thread = threading.Thread(target=self._rodar_loop, daemon=True)
        self._thread.start()

    def desconectar(self) -> None:
        if self._loop and self._app:
            future = asyncio.run_coroutine_threadsafe(self._parar_app(), self._loop)
            try:
                future.result(timeout=15)
            except Exception:
                logger.exception("TG[%s]: erro ao parar Application", self.sessao_id)
        self._connected = False
        self._app = None
        self._loop = None
        self._thread = None
        self._on_status(StatusConexao.DESCONECTADO, None)

    async def _parar_app(self):
        if not self._app:
            return
        if self._app.updater and self._app.updater.running:
            await self._app.updater.stop()
        if self._app.running:
            await self._app.stop()
        await self._app.shutdown()

    def _rodar_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()
        try:
            loop.run_until_complete(self._executar())
        except Exception:
            logger.exception("TG[%s]: erro fatal no loop", self.sessao_id)
            self._on_status(StatusConexao.ERRO, "loop terminou com erro")
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _executar(self):
        try:
            self._app = ApplicationBuilder().token(self._bot_token).build()
            self._registrar_handlers(self._app)
            await self._app.initialize()
            await self._app.start()
            # Validar token e obter identidade.
            try:
                me = await self._app.bot.get_me()
                identificador = me.username or str(me.id)
            except Exception as e:
                logger.exception("TG[%s]: get_me() falhou — token inválido?", self.sessao_id)
                self._on_status(StatusConexao.ERRO, f"token inválido: {e}")
                return
            await self._app.updater.start_polling(drop_pending_updates=True)
            self._connected = True
            self._on_status(StatusConexao.CONECTADO, identificador)
            logger.info("TG[%s]: conectado como @%s", self.sessao_id, identificador)
            # Mantém o loop vivo até desconexão.
            while self._connected and self._app and self._app.updater and self._app.updater.running:
                await asyncio.sleep(1)
        except Exception:
            logger.exception("TG[%s]: erro em _executar", self.sessao_id)
            self._on_status(StatusConexao.ERRO, "exceção em _executar")

    # ----- envio -----

    def _despachar(self, coro) -> bool:
        if not self._loop or not self._app:
            logger.warning("TG[%s]: tentativa de envio sem conexão ativa", self.sessao_id)
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            future.result(timeout=30)
            return True
        except Exception:
            logger.exception("TG[%s]: erro ao despachar envio", self.sessao_id)
            return False

    def enviar_texto(self, chat_id: str, texto: str) -> bool:
        return self._despachar(self._app.bot.send_message(chat_id=int(chat_id), text=texto))

    def enviar_imagem(self, chat_id: str, imagem_bytes: bytes, legenda: str = "") -> bool:
        return self._despachar(
            self._app.bot.send_photo(chat_id=int(chat_id), photo=imagem_bytes, caption=legenda or None)
        )

    def enviar_audio(self, chat_id: str, audio_bytes: bytes, ptt: bool = True) -> bool:
        # ptt=True → voice note (OGG/Opus). Falso → tratar como música.
        if ptt:
            return self._despachar(self._app.bot.send_voice(chat_id=int(chat_id), voice=audio_bytes))
        return self._despachar(self._app.bot.send_audio(chat_id=int(chat_id), audio=audio_bytes))

    def enviar_video(self, chat_id: str, video_bytes: bytes, legenda: str = "") -> bool:
        return self._despachar(
            self._app.bot.send_video(chat_id=int(chat_id), video=video_bytes, caption=legenda or None)
        )

    def enviar_documento(self, chat_id: str, doc_bytes: bytes, nome_arquivo: str) -> bool:
        # PTB aceita bytes mas precisa de um nome para o documento — gera InputFile interno.
        import io as _io

        buf = _io.BytesIO(doc_bytes)
        buf.name = nome_arquivo or "arquivo"
        return self._despachar(self._app.bot.send_document(chat_id=int(chat_id), document=buf))

    # ----- handlers -----

    def _registrar_handlers(self, app: Application) -> None:
        # Um handler por tipo — captura por categoria de mídia.
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_texto))
        app.add_handler(MessageHandler(filters.COMMAND, self._on_texto))  # /start, /help — tratar como texto
        app.add_handler(MessageHandler(filters.VOICE, self._on_voice))
        app.add_handler(MessageHandler(filters.AUDIO, self._on_audio))
        app.add_handler(MessageHandler(filters.PHOTO, self._on_photo))
        app.add_handler(MessageHandler(filters.VIDEO, self._on_video))
        app.add_handler(MessageHandler(filters.Document.ALL, self._on_document))

    async def _on_texto(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        if not msg or not update.effective_chat:
            return
        evento = EventoMensagem(
            plataforma=Plataforma.TELEGRAM,
            sessao_id=self.sessao_id,
            mensagem_id_externo=str(msg.message_id),
            chat_id=str(update.effective_chat.id),
            remetente_id=str(update.effective_user.id) if update.effective_user else str(update.effective_chat.id),
            remetente_nome=(update.effective_user.full_name if update.effective_user else None),
            tipo=TipoMidia.TEXTO,
            texto=msg.text or msg.caption or "",
            raw=update,
        )
        await self._entregar(evento)

    async def _on_voice(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        await self._on_midia_audio(update, ptt=True)

    async def _on_audio(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        await self._on_midia_audio(update, ptt=False)

    async def _on_midia_audio(self, update: Update, *, ptt: bool):
        msg = update.effective_message
        if not msg or not update.effective_chat:
            return
        media = msg.voice if ptt else msg.audio
        if not media:
            return
        midia_bytes = await self._baixar(media.file_id)
        mime = getattr(media, "mime_type", None) or ("audio/ogg" if ptt else "audio/mpeg")
        evento = EventoMensagem(
            plataforma=Plataforma.TELEGRAM,
            sessao_id=self.sessao_id,
            mensagem_id_externo=str(msg.message_id),
            chat_id=str(update.effective_chat.id),
            remetente_id=str(update.effective_user.id) if update.effective_user else str(update.effective_chat.id),
            remetente_nome=(update.effective_user.full_name if update.effective_user else None),
            tipo=TipoMidia.AUDIO,
            texto=msg.caption or "",
            midia_bytes=midia_bytes,
            midia_mime=mime,
            raw=update,
            extras={"ptt": ptt},
        )
        await self._entregar(evento)

    async def _on_photo(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        if not msg or not msg.photo or not update.effective_chat:
            return
        # Pegar a maior resolução disponível.
        photo = msg.photo[-1]
        midia_bytes = await self._baixar(photo.file_id)
        evento = EventoMensagem(
            plataforma=Plataforma.TELEGRAM,
            sessao_id=self.sessao_id,
            mensagem_id_externo=str(msg.message_id),
            chat_id=str(update.effective_chat.id),
            remetente_id=str(update.effective_user.id) if update.effective_user else str(update.effective_chat.id),
            remetente_nome=(update.effective_user.full_name if update.effective_user else None),
            tipo=TipoMidia.IMAGEM,
            texto=msg.caption or "",
            midia_bytes=midia_bytes,
            midia_mime="image/jpeg",
            raw=update,
        )
        await self._entregar(evento)

    async def _on_video(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        if not msg or not msg.video or not update.effective_chat:
            return
        midia_bytes = await self._baixar(msg.video.file_id)
        evento = EventoMensagem(
            plataforma=Plataforma.TELEGRAM,
            sessao_id=self.sessao_id,
            mensagem_id_externo=str(msg.message_id),
            chat_id=str(update.effective_chat.id),
            remetente_id=str(update.effective_user.id) if update.effective_user else str(update.effective_chat.id),
            remetente_nome=(update.effective_user.full_name if update.effective_user else None),
            tipo=TipoMidia.VIDEO,
            texto=msg.caption or "",
            midia_bytes=midia_bytes,
            midia_mime=getattr(msg.video, "mime_type", None) or "video/mp4",
            raw=update,
        )
        await self._entregar(evento)

    async def _on_document(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        if not msg or not msg.document or not update.effective_chat:
            return
        midia_bytes = await self._baixar(msg.document.file_id)
        evento = EventoMensagem(
            plataforma=Plataforma.TELEGRAM,
            sessao_id=self.sessao_id,
            mensagem_id_externo=str(msg.message_id),
            chat_id=str(update.effective_chat.id),
            remetente_id=str(update.effective_user.id) if update.effective_user else str(update.effective_chat.id),
            remetente_nome=(update.effective_user.full_name if update.effective_user else None),
            tipo=TipoMidia.DOCUMENTO,
            texto=msg.caption or "",
            midia_bytes=midia_bytes,
            midia_mime=msg.document.mime_type or "application/octet-stream",
            midia_nome=msg.document.file_name,
            raw=update,
        )
        await self._entregar(evento)

    async def _baixar(self, file_id: str) -> bytes:
        f = await self._app.bot.get_file(file_id)
        data = await f.download_as_bytearray()
        return bytes(data)

    async def _entregar(self, evento: EventoMensagem):
        # on_mensagem é sincrono (a interface não força async). Roda em
        # threadpool pra não bloquear o loop do polling.
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._on_mensagem, evento)
        except Exception:
            logger.exception("TG[%s]: erro no on_mensagem callback", self.sessao_id)
