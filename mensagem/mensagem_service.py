"""
Serviço de lógica de negócio para mensagens.
"""
import asyncio
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timedelta
import os
import base64
from pathlib import Path
from PIL import Image
import io
from neonize.events import MessageEv
from mensagem.mensagem_model import Mensagem
from mensagem.mensagem_schema import MensagemCriar
from mensagem.markdown_whatsapp import markdown_para_whatsapp
from config.config_service import ConfiguracaoService
from security import validate_upload_file, sanitize_user_input
from log.log_service import fluxi_log


class MensagemService:
    """Serviço para gerenciar mensagens."""

    # Lock em memória para evitar processamento duplicado da mesma mensagem
    _mensagens_em_processamento = set()
    _lock_processamento = __import__('threading').Lock()

    # Referências fortes para background tasks — impede o GC de destruir tasks pendentes.
    _background_tasks: set = set()

    # Event loop principal do FastAPI/uvicorn — setado no startup da app.
    # Usado para despachar coding tasks da thread do neonize para o loop principal.
    _fastapi_loop: asyncio.AbstractEventLoop = None

    @classmethod
    def set_fastapi_loop(cls, loop: asyncio.AbstractEventLoop):
        """Chamado no startup do FastAPI para capturar o event loop principal."""
        cls._fastapi_loop = loop
        fluxi_log.info("sistema", None, "Event loop FastAPI capturado para MensagemService")

    @staticmethod
    def _resolver_jid_destino(info, message_source, telefone_cliente):
        """Resolve o JID de destino limpando a parte do dispositivo para evitar erros no envio."""
        from neonize.utils import build_jid

        def _limpar_jid(jid_obj):
            if jid_obj and hasattr(jid_obj, 'User') and jid_obj.User and hasattr(jid_obj, 'Server') and jid_obj.Server:
                user_clean = str(jid_obj.User).split(':')[0]
                novo_jid = build_jid(user_clean, jid_obj.Server)
                # Garante que Device seja limpo, se a propriedade existir
                if hasattr(novo_jid, 'Device'):
                    setattr(novo_jid, 'Device', 0)
                if hasattr(novo_jid, 'RawAgent'):
                    setattr(novo_jid, 'RawAgent', 0)
                return novo_jid
            return None

        chat_jid = getattr(info, 'Chat', None)
        chat_limpo = _limpar_jid(chat_jid)
        if chat_limpo:
            return chat_limpo

        sender_alt = getattr(message_source, 'SenderAlt', None)
        alt_limpo = _limpar_jid(sender_alt)
        if alt_limpo:
            return alt_limpo

        sender = getattr(message_source, 'Sender', None)
        sender_limpo = _limpar_jid(sender)
        if sender_limpo:
            return sender_limpo

        telefone_limpo = str(telefone_cliente).split('@')[0].split(':')[0]
        return build_jid(telefone_limpo)

    @staticmethod
    def _jid_para_log(jid) -> str:
        """Formata JID para logs de roteamento."""
        user = getattr(jid, 'User', '?')
        server = getattr(jid, 'Server', '?')
        return f"{user}@{server}"

    @staticmethod
    async def _executar_comando_se_aplicavel(
        db: Session,
        sessao,
        canal,
        chat_id: str,
        telefone_cliente: str,
        texto: str,
    ) -> bool:
        """Detecta comando cadastrado em `sessao_comandos` e executa.

        Reusavel entre pipelines (WA tem versao inline mais antiga; TG usa essa).
        Retorna True se o texto era um comando e foi executado (caller deve
        encerrar o turno). Retorna False se nao era comando — caller segue
        pipeline normal.

        Cobre: ativar, desativar, limpar, ajuda, status, listar. trocar_agente
        fica fora desta camada — ainda exige integracao com AgenteService.
        """
        if not texto:
            return False

        from sessao.sessao_comando_service import SessaoComandoService

        comando = SessaoComandoService.obter_por_gatilho(db, sessao.id, texto)
        if comando is None:
            return False

        # Envio uniforme via interface CanalClient (funciona p/ WA e TG).
        def _send(msg: str) -> None:
            try:
                if hasattr(canal, "enviar_texto"):
                    canal.enviar_texto(chat_id, msg)
            except Exception:
                fluxi_log.error(
                    "mensagem", "comando", "Falha ao enviar resposta de comando",
                    exc_info=True, session_id=sessao.id,
                )

        cid = comando.comando_id

        if cid == "ativar":
            fluxi_log.info("mensagem", "comando", "Comando ativar IA", extra={"gatilho": comando.gatilho}, session_id=sessao.id)
            sessao.auto_responder = True
            db.commit()
            _send(comando.resposta or "🤖 *IA Ativada!*")
            return True

        if cid == "desativar":
            fluxi_log.info("mensagem", "comando", "Comando desativar IA", extra={"gatilho": comando.gatilho}, session_id=sessao.id)
            sessao.auto_responder = False
            db.commit()
            _send(comando.resposta or "😴 *IA Desativada!*")
            return True

        if cid == "limpar":
            n = (
                db.query(Mensagem)
                .filter(Mensagem.sessao_id == sessao.id, Mensagem.chat_id == chat_id)
                .delete(synchronize_session=False)
            )
            # Compat: alguns registros legados de TG podem ter chat_id=None,
            # mas telefone_cliente preenchido. Tenta tambem por essa chave.
            n += (
                db.query(Mensagem)
                .filter(
                    Mensagem.sessao_id == sessao.id,
                    Mensagem.chat_id.is_(None),
                    Mensagem.telefone_cliente == telefone_cliente,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
            fluxi_log.info(
                "mensagem", "comando", "Histórico limpo via #limpar",
                extra={"chat_id": chat_id, "deletadas": n}, session_id=sessao.id,
            )
            _send(comando.resposta or f"🧹 Histórico apagado ({n} mensagens).")
            return True

        if cid == "ajuda":
            try:
                texto_ajuda = SessaoComandoService.gerar_texto_ajuda(db, sessao.id)
            except Exception:
                texto_ajuda = comando.resposta or "Comandos disponíveis: #ativar #desativar #limpar #ajuda #status"
            _send(texto_ajuda)
            return True

        if cid == "status":
            status_txt = (
                f"📊 Sessão: {sessao.nome}\n"
                f"Plataforma: {sessao.plataforma}\n"
                f"Auto-responder: {'✅' if sessao.auto_responder else '❌'}\n"
                f"Status: {sessao.status}"
            )
            _send(comando.resposta or status_txt)
            return True

        # Outros (listar / trocar_agente) ainda não portados — deixa o pipeline normal seguir.
        return False

    @staticmethod
    def _anexar_nota_midia(texto_atual, media_id: str, tipo: str) -> str:
        """Anexa nota visivel ao LLM contendo o media_id real.

        Sem isso o LLM tenta inventar nomes de arquivo ou URLs ao chamar
        `enviar_arquivo`. A nota fica no `conteudo_texto` da Mensagem,
        que entra no historico que o agente le. Pequena poluicao em troca
        de viabilizar reenvio.
        """
        nota = (
            f"\n\n[mídia anexada: tipo={tipo}, media_id=\"{media_id}\". "
            f"Para reenviar esta mídia ao usuário, chame a ferramenta "
            f"enviar_arquivo com ref=\"id:{media_id}\".]"
        )
        return (texto_atual or "") + nota

    @staticmethod
    def _extrair_texto_mensagem(message) -> str:
        """Extrai texto de mensagens WhatsApp (conversation/extendedTextMessage)."""
        if hasattr(message, 'conversation') and message.conversation:
            return message.conversation.strip()

        if hasattr(message, 'extendedTextMessage') and message.extendedTextMessage:
            texto = getattr(message.extendedTextMessage, 'text', None)
            if texto:
                return texto.strip()

        return ""

    @staticmethod
    def listar_por_sessao(
        db: Session,
        sessao_id: int,
        limite: int = 100,
        offset: int = 0
    ) -> List[Mensagem]:
        """Lista mensagens de uma sessão."""
        return db.query(Mensagem)\
            .filter(Mensagem.sessao_id == sessao_id)\
            .order_by(Mensagem.criado_em.desc())\
            .limit(limite)\
            .offset(offset)\
            .all()

    @staticmethod
    def listar_por_cliente(
        db: Session,
        sessao_id: int,
        telefone_cliente: str,
        limite: int = 50
    ) -> List[Mensagem]:
        """Lista mensagens de um cliente específico."""
        return db.query(Mensagem)\
            .filter(
                Mensagem.sessao_id == sessao_id,
                Mensagem.telefone_cliente == telefone_cliente
            )\
            .order_by(Mensagem.criado_em.desc())\
            .limit(limite)\
            .all()

    @staticmethod
    def obter_por_id(db: Session, mensagem_id: int) -> Optional[Mensagem]:
        """Obtém uma mensagem pelo ID."""
        return db.query(Mensagem).filter(Mensagem.id == mensagem_id).first()

    @staticmethod
    def criar(db: Session, mensagem: MensagemCriar) -> Mensagem:
        """Cria uma nova mensagem."""
        db_mensagem = Mensagem(**mensagem.model_dump())
        db.add(db_mensagem)
        db.commit()
        db.refresh(db_mensagem)
        return db_mensagem

    @staticmethod
    def salvar_imagem(imagem_bytes: bytes, telefone: str, sessao_id: int, db: Session = None) -> tuple[str, str]:
        """
        Salva uma imagem localmente e retorna o caminho e base64.

        Returns:
            tuple: (caminho_arquivo, base64_string)
        """
        try:
            from security import SecurityConfig

            # Validação de segurança do arquivo
            max_file_size_mb = ConfiguracaoService.obter_valor(db, "sistema_max_file_size_mb", 10)
            validate_upload_file(
                file_bytes=imagem_bytes,
                mime_type="image/jpeg",
                allowed_types=SecurityConfig.ALLOWED_IMAGE_TYPES,
                max_size_mb=max_file_size_mb
            )

            # Validação de tipo de imagem
            img = Image.open(io.BytesIO(imagem_bytes))
            img.verify()
            img = Image.open(io.BytesIO(imagem_bytes))

        except Exception as e:
            fluxi_log.error("mensagem", "imagem", "Erro na validacao de imagem", exc_info=True, session_id=sessao_id)
            return None, None

        # Obter diretório de uploads configurável
        if db:
            upload_base = ConfiguracaoService.obter_valor(db, "sistema_diretorio_uploads", "./uploads")
            qualidade_jpeg = ConfiguracaoService.obter_valor(db, "sistema_qualidade_jpeg", 85)
        else:
            upload_base = "./uploads"
            qualidade_jpeg = 85

        # Criar diretório se não existir
        upload_dir = Path(upload_base) / f"sessao_{sessao_id}" / telefone
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Gerar nome único para arquivo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"img_{timestamp}.jpg"
        filepath = upload_dir / filename

        # Salvar imagem
        try:
            # Abrir e converter para RGB (caso seja RGBA)
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')

            # Sanitização: remover metadados EXIF para privacidade
            data = list(img.getdata())
            img_without_exif = Image.new(img.mode, img.size)
            img_without_exif.putdata(data)

            # Salvar com qualidade configurável
            img_without_exif.save(filepath, 'JPEG', quality=int(qualidade_jpeg), optimize=True)

            # Converter para base64
            base64_string = base64.b64encode(imagem_bytes).decode('utf-8')

            return str(filepath), base64_string
        except Exception as e:
            fluxi_log.error("mensagem", "imagem", "Erro ao salvar imagem", exc_info=True, session_id=sessao_id)
            return None, None

    @staticmethod
    def _detectar_tipo_mensagem(message) -> str:
        """Detecta o tipo de uma mensagem do WhatsApp."""
        # Função auxiliar para verificar se campo protobuf tem conteúdo
        def tem_conteudo(campo):
            if not campo:
                return False
            # Verificar se tem algum campo preenchido (mime_type, url, etc.)
            if hasattr(campo, 'mimetype') and campo.mimetype:
                return True
            if hasattr(campo, 'url') and campo.url:
                return True
            if hasattr(campo, 'fileSha256') and campo.fileSha256:
                return True
            # Para protobuf, verificar se não está vazio
            try:
                return campo.ByteSize() > 0
            except:
                return bool(campo)
        
        # Verificar texto primeiro
        if hasattr(message, 'conversation') and message.conversation:
            return "texto"
        if hasattr(message, 'extendedTextMessage') and tem_conteudo(message.extendedTextMessage):
            return "texto"
        
        # Verificar áudio ANTES de imagem (áudio pode ter campos parecidos)
        if hasattr(message, 'audioMessage') and tem_conteudo(message.audioMessage):
            return "audio"
        
        # Verificar outros tipos de mídia
        if hasattr(message, 'imageMessage') and tem_conteudo(message.imageMessage):
            return "imagem"
        if hasattr(message, 'videoMessage') and tem_conteudo(message.videoMessage):
            return "video"
        if hasattr(message, 'stickerMessage') and tem_conteudo(message.stickerMessage):
            return "sticker"
        if hasattr(message, 'locationMessage') and tem_conteudo(message.locationMessage):
            return "localizacao"
        if hasattr(message, 'documentMessage') and tem_conteudo(message.documentMessage):
            return "documento"
        
        return "texto"  # Default
    
    @staticmethod
    async def processar_evento_canal(db: Session, evento) -> None:
        """Ponto de entrada único pra mensagens vindas de qualquer canal.

        Roteia pra pipeline específica por plataforma. Quem chama é o
        callback `on_mensagem` montado em sessao_service.

        SUPERVISOR EXPLÍCITO (skill `resiliencia-erros`):
        Qualquer exceção que escapar do tratamento interno das pipelines cai
        aqui no try/except externo, dispara `MensagemFallbackService.acionar`
        (audit + mensagem ao usuário) e termina o turno limpo. Eh o ÚNICO
        try/except `except Exception` legítimo do pipeline.
        """
        from canal.canal_base import Plataforma
        from mensagem import mensagem_fallback_service

        try:
            if evento.plataforma == Plataforma.WHATSAPP:
                # `evento.raw` é o MessageEv original — preserva 100% do pipeline atual.
                await MensagemService.processar_mensagem_recebida(
                    db, evento.sessao_id, evento.raw
                )
            elif evento.plataforma == Plataforma.TELEGRAM:
                await MensagemService.processar_evento_telegram(db, evento)
            else:
                fluxi_log.warning(
                    "mensagem", "roteamento", "Plataforma desconhecida no evento",
                    extra={"plataforma": str(evento.plataforma)},
                    session_id=evento.sessao_id,
                )
        except Exception as exc:
            # Imprevisto. Pipeline NUNCA derruba o callback do canal.
            chat_id = getattr(evento, "chat_id", "") or ""
            fluxi_log.error(
                "mensagem", "supervisor",
                "Excecao imprevista no pipeline — acionando fallback",
                exc_info=True,
                session_id=evento.sessao_id,
                extra={"chat_id": chat_id, "exception": type(exc).__name__},
            )
            try:
                # Tenta achar a Mensagem que estava sendo processada (pra marcar respondida).
                from mensagem.mensagem_model import Mensagem

                mensagem_db = None
                msg_id_ext = getattr(evento, "mensagem_id_externo", None)
                if msg_id_ext:
                    mensagem_db = (
                        db.query(Mensagem)
                        .filter(
                            Mensagem.sessao_id == evento.sessao_id,
                            Mensagem.mensagem_id_externo == msg_id_ext,
                        )
                        .first()
                    )
                await mensagem_fallback_service.acionar(
                    db,
                    sessao_id=evento.sessao_id,
                    chat_id=chat_id,
                    exc=exc,
                    mensagem_db=mensagem_db,
                    contexto_extra={"plataforma": str(evento.plataforma)},
                )
            except Exception:
                # Fallback do fallback — log e segue. Nao propagar pro callback do canal.
                fluxi_log.error(
                    "mensagem", "supervisor",
                    "Fallback service falhou — turno terminado em silêncio",
                    exc_info=True,
                    session_id=evento.sessao_id,
                )

    @staticmethod
    async def processar_evento_telegram(db: Session, evento) -> None:
        """Pipeline para mensagens vindas do Telegram.

        Mais enxuto que o WA porque o adapter já entrega bytes de mídia e
        identifica o tipo. Cobre: texto, áudio (voice/audio), imagem.
        """
        from agente.agente_service import AgenteService
        from canal.canal_base import TipoMidia
        from sessao.sessao_service import SessaoService, gerenciador_sessoes

        sessao_id = evento.sessao_id
        chat_id = evento.chat_id
        sessao = SessaoService.obter_por_id(db, sessao_id)
        if not sessao or not sessao.ativa:
            return

        # Dedup por (plataforma, sessao, chat, mensagem_id) — chave composta
        # porque message_id do Telegram não é único globalmente.
        chave_msg = f"TG_{sessao_id}_{chat_id}_{evento.mensagem_id_externo}"
        with MensagemService._lock_processamento:
            if chave_msg in MensagemService._mensagens_em_processamento:
                return
            MensagemService._mensagens_em_processamento.add(chave_msg)

        # Verificar no DB (idempotência cross-restart).
        existente = db.query(Mensagem).filter(
            Mensagem.sessao_id == sessao_id,
            Mensagem.plataforma == "telegram",
            Mensagem.chat_id == chat_id,
            Mensagem.mensagem_id_externo == evento.mensagem_id_externo,
        ).first()
        if existente:
            with MensagemService._lock_processamento:
                MensagemService._mensagens_em_processamento.discard(chave_msg)
            return

        canal = gerenciador_sessoes.obter_cliente(sessao_id)
        if not canal:
            fluxi_log.warning(
                "mensagem", "telegram", "Canal ausente ao processar evento",
                session_id=sessao_id,
            )
            return

        # ─── Detecção de comando (#limpar / #ativar / #desativar / #ajuda etc.)
        # Pipeline do WhatsApp já tem isso embutido; aqui replicamos pra TG
        # antes de gravar mensagem ou chamar agente. Se for comando, o canal
        # responde direto e a função retorna sem passar pelo LLM.
        if evento.tipo == TipoMidia.TEXTO and evento.texto:
            try:
                comando_executado = await MensagemService._executar_comando_se_aplicavel(
                    db=db,
                    sessao=sessao,
                    canal=canal,
                    chat_id=chat_id,
                    telefone_cliente=chat_id,  # TG: chat_id faz papel de telefone_cliente
                    texto=evento.texto.strip(),
                )
                if comando_executado:
                    # Comando interceptado — não cria db_mensagem nem chama agente.
                    return
            except Exception:
                fluxi_log.error(
                    "mensagem", "telegram", "Erro ao processar comando — seguindo pipeline normal",
                    exc_info=True, session_id=sessao_id,
                )

        db_mensagem = Mensagem(
            sessao_id=sessao_id,
            plataforma="telegram",
            telefone_cliente=chat_id,  # legacy: preencher pra compat
            chat_id=chat_id,
            mensagem_id_externo=evento.mensagem_id_externo,
            mensagem_id_whatsapp=None,
            nome_cliente=evento.remetente_nome,
            tipo="texto",
            direcao="recebida",
            processada=False,
            respondida=False,
        )

        try:
            if evento.tipo == TipoMidia.AUDIO and evento.midia_bytes:
                db_mensagem.tipo = "audio"
                # Registrar na camada midias (media_id estavel pro agente).
                try:
                    from midia import midia_service as _midia_svc
                    _m = _midia_svc.registrar_midia(
                        db,
                        sessao_id=sessao_id,
                        chat_id=chat_id,
                        conteudo=evento.midia_bytes,
                        mime=evento.midia_mime or "audio/ogg",
                        origem="upload",
                        vinculada_tipo="mensagem",
                    )
                    db_mensagem.media_id = _m.media_id
                    db_mensagem.conteudo_texto = MensagemService._anexar_nota_midia(
                        db_mensagem.conteudo_texto, _m.media_id, "audio"
                    )
                except Exception:
                    fluxi_log.warning("mensagem", "audio", "Falha ao registrar midia TG", exc_info=True, session_id=sessao_id)

                try:
                    from audio.transcription_service import TranscriptionService

                    resultado = await TranscriptionService.transcrever(
                        db,
                        evento.midia_bytes,
                        filename="audio.ogg",
                        mime_type=evento.midia_mime or "audio/ogg",
                    )
                    if resultado.get("sucesso"):
                        texto = sanitize_user_input(resultado.get("texto", ""))
                        db_mensagem.conteudo_texto = f"[Áudio transcrito]: {texto}"
                        fluxi_log.info(
                            "mensagem", "audio",
                            "Transcricao concluida (TG)",
                            extra={"preview": texto[:100]}, session_id=sessao_id,
                        )
                    else:
                        db_mensagem.conteudo_texto = "[Áudio não transcrito]"
                except Exception:
                    fluxi_log.error(
                        "mensagem", "audio", "Erro ao transcrever audio TG",
                        exc_info=True, session_id=sessao_id,
                    )
                    db_mensagem.conteudo_texto = "[Erro ao processar áudio]"

            elif evento.tipo == TipoMidia.IMAGEM and evento.midia_bytes:
                db_mensagem.tipo = "imagem"
                caminho, base64_str = MensagemService.salvar_imagem(
                    evento.midia_bytes, chat_id, sessao_id, db
                )
                if caminho:
                    db_mensagem.conteudo_imagem_path = caminho
                    db_mensagem.conteudo_imagem_base64 = base64_str
                    db_mensagem.conteudo_mime_type = evento.midia_mime or "image/jpeg"
                if evento.texto:
                    db_mensagem.conteudo_texto = sanitize_user_input(evento.texto)
                try:
                    from midia import midia_service as _midia_svc
                    _m = _midia_svc.registrar_midia(
                        db,
                        sessao_id=sessao_id,
                        chat_id=chat_id,
                        conteudo=evento.midia_bytes,
                        mime=evento.midia_mime or "image/jpeg",
                        origem="upload",
                        vinculada_tipo="mensagem",
                    )
                    db_mensagem.media_id = _m.media_id
                    db_mensagem.conteudo_texto = MensagemService._anexar_nota_midia(
                        db_mensagem.conteudo_texto, _m.media_id, "imagem"
                    )
                except Exception:
                    fluxi_log.warning("mensagem", "imagem", "Falha ao registrar midia TG", exc_info=True, session_id=sessao_id)

            elif evento.tipo == TipoMidia.TEXTO:
                texto = sanitize_user_input(evento.texto or "")
                if not texto.strip():
                    return
                db_mensagem.conteudo_texto = texto
            elif evento.tipo in (TipoMidia.VIDEO, TipoMidia.DOCUMENTO) and evento.midia_bytes:
                # Cobertura nova: video/documento via Telegram (adapter ja entrega bytes).
                db_mensagem.tipo = evento.tipo.value if hasattr(evento.tipo, "value") else str(evento.tipo)
                if evento.texto:
                    db_mensagem.conteudo_texto = sanitize_user_input(evento.texto)
                try:
                    from midia import midia_service as _midia_svc
                    _m = _midia_svc.registrar_midia(
                        db,
                        sessao_id=sessao_id,
                        chat_id=chat_id,
                        conteudo=evento.midia_bytes,
                        mime=evento.midia_mime or "application/octet-stream",
                        origem="upload",
                        vinculada_tipo="mensagem",
                    )
                    db_mensagem.media_id = _m.media_id
                    db_mensagem.conteudo_imagem_path = _m.path
                    db_mensagem.conteudo_mime_type = _m.mime
                    db_mensagem.conteudo_texto = MensagemService._anexar_nota_midia(
                        db_mensagem.conteudo_texto, _m.media_id, db_mensagem.tipo
                    )
                except Exception:
                    fluxi_log.error("mensagem", db_mensagem.tipo, "Erro ao registrar midia TG", exc_info=True, session_id=sessao_id)
            else:
                # Tipos sem bytes (sticker/localizacao): salvar registro mas
                # não processar com agente.
                db_mensagem.tipo = evento.tipo.value if hasattr(evento.tipo, "value") else str(evento.tipo)
                db_mensagem.conteudo_texto = f"[Mídia: {db_mensagem.tipo}]"

            db.add(db_mensagem)
            db.commit()
            db.refresh(db_mensagem)

            if not sessao.auto_responder:
                return

            historico_limite = ConfiguracaoService.obter_valor(
                db, "agente_historico_mensagens", 10
            )
            historico = (
                db.query(Mensagem)
                .filter(Mensagem.sessao_id == sessao_id, Mensagem.chat_id == chat_id)
                .order_by(Mensagem.criado_em.desc())
                .limit(historico_limite)
                .all()
            )

            resposta = await AgenteService.processar_mensagem(
                db, sessao, db_mensagem, historico, jid_destino=None
            )
            db_mensagem.resposta_texto = resposta.get("texto")
            db_mensagem.resposta_tokens_input = resposta.get("tokens_input")
            db_mensagem.resposta_tokens_output = resposta.get("tokens_output")
            db_mensagem.resposta_tempo_ms = resposta.get("tempo_ms")
            db_mensagem.resposta_modelo = resposta.get("modelo")
            db_mensagem.ferramentas_usadas = resposta.get("ferramentas")
            db_mensagem.processada = True
            db_mensagem.processado_em = datetime.now()

            texto_resposta = resposta.get("texto")
            if texto_resposta:
                ok = canal.enviar_texto(chat_id, texto_resposta)
                if ok:
                    db_mensagem.respondida = True
                    db_mensagem.respondido_em = datetime.now()
                else:
                    db_mensagem.resposta_erro = "Falha ao enviar resposta TG"

            db.commit()
        except Exception as e:
            fluxi_log.error(
                "mensagem", "telegram", "Erro no pipeline TG",
                exc_info=True, session_id=sessao_id,
            )
            db_mensagem.resposta_erro = str(e)
            db_mensagem.processada = True
            db_mensagem.processado_em = datetime.now()
            try:
                canal.enviar_texto(
                    chat_id,
                    "❌ Não consegui processar sua mensagem agora. Tente novamente.",
                )
            except Exception:
                pass
            db.commit()
        finally:
            with MensagemService._lock_processamento:
                MensagemService._mensagens_em_processamento.discard(chave_msg)

    @staticmethod
    async def processar_mensagem_recebida(
        db: Session,
        sessao_id: int,
        event: MessageEv
    ):
        """
        Processa uma mensagem recebida do WhatsApp.
        """
        from sessao.sessao_service import SessaoService
        from sessao.sessao_tipo_mensagem_service import SessaoTipoMensagemService
        from agente.agente_service import AgenteService
        
        # Obter informações da mensagem
        message = event.Message
        info = event.Info
        message_source = info.MessageSource
        sender_jid = message_source.Sender
        
        # Extrair telefone do cliente
        # Prioridade: SenderAlt (número real) > Sender (pode ser "lid" interno)
        telefone_cliente = None
        if hasattr(message_source, 'SenderAlt') and message_source.SenderAlt and hasattr(message_source.SenderAlt, 'User') and message_source.SenderAlt.User:
            telefone_cliente = message_source.SenderAlt.User
        else:
            chat_jid = getattr(info, 'Chat', None)
            if chat_jid and hasattr(chat_jid, 'Server') and chat_jid.Server == "s.whatsapp.net" and hasattr(chat_jid, 'User') and chat_jid.User:
                telefone_cliente = chat_jid.User
            elif hasattr(sender_jid, 'Server') and sender_jid.Server == "s.whatsapp.net" and hasattr(sender_jid, 'User') and sender_jid.User:
                telefone_cliente = sender_jid.User
            elif hasattr(sender_jid, 'User') and sender_jid.User:
                telefone_cliente = sender_jid.User
            else:
                telefone_cliente = str(sender_jid).split('@')[0] if '@' in str(sender_jid) else str(sender_jid)

        if hasattr(sender_jid, 'Server') and sender_jid.Server == "lid":
            fluxi_log.warning("mensagem", "roteamento", "Sender em formato LID detectado", extra={"sender_alt_usado": bool(getattr(message_source, 'SenderAlt', None))}, session_id=sessao_id)
        
        # Obter sessão
        sessao = SessaoService.obter_por_id(db, sessao_id)
        if not sessao or not sessao.ativa:
            return

        # Ignorar mensagens duplicadas (idempotência) - lock em memória + DB
        mensagem_id_whatsapp = getattr(info, 'ID', None)
        if mensagem_id_whatsapp:
            chave_msg = f"{sessao_id}_{mensagem_id_whatsapp}"
            with MensagemService._lock_processamento:
                if chave_msg in MensagemService._mensagens_em_processamento:
                    fluxi_log.info("mensagem", "roteamento", "Mensagem ja em processamento (lock memoria)", extra={"mensagem_id": mensagem_id_whatsapp}, session_id=sessao_id)
                    return
                MensagemService._mensagens_em_processamento.add(chave_msg)
            
            # Também verificar no DB
            mensagem_existente = db.query(Mensagem).filter(
                Mensagem.sessao_id == sessao_id,
                Mensagem.mensagem_id_whatsapp == mensagem_id_whatsapp
            ).first()
            if mensagem_existente:
                fluxi_log.info("mensagem", "roteamento", "Mensagem duplicada ignorada (DB)", extra={"mensagem_id": mensagem_id_whatsapp}, session_id=sessao_id)
                with MensagemService._lock_processamento:
                    MensagemService._mensagens_em_processamento.discard(chave_msg)
                return
        
        # Detectar tipo de mensagem e verificar configuração
        tipo_mensagem = MensagemService._detectar_tipo_mensagem(message)
        texto_recebido = MensagemService._extrair_texto_mensagem(message)
        config_tipo = SessaoTipoMensagemService.obter_acao(db, sessao_id, tipo_mensagem)
        
        # Se for ignorar e não for texto, retornar
        if tipo_mensagem != "texto" and config_tipo["acao"] == "ignorar":
            fluxi_log.info("mensagem", "roteamento", "Mensagem ignorada por tipo", extra={"tipo": tipo_mensagem}, session_id=sessao_id)
            return
        
        # Se for resposta fixa, enviar e retornar
        if tipo_mensagem != "texto" and config_tipo["acao"] == "resposta_fixa" and config_tipo["resposta_fixa"]:
            from sessao.sessao_service import gerenciador_sessoes
            cliente = gerenciador_sessoes.obter_cliente(sessao_id)
            if cliente:
                jid = MensagemService._resolver_jid_destino(info, message_source, telefone_cliente)
                cliente.send_message(jid, message=config_tipo["resposta_fixa"])
                fluxi_log.info("mensagem", "roteamento", "Resposta fixa enviada", extra={"tipo": tipo_mensagem, "jid": MensagemService._jid_para_log(jid)}, session_id=sessao_id)
            return
        
        # Criar registro de mensagem
        db_mensagem = Mensagem(
            sessao_id=sessao_id,
            telefone_cliente=telefone_cliente,
            mensagem_id_whatsapp=mensagem_id_whatsapp,
            tipo="texto",
            direcao="recebida",
            processada=False,
            respondida=False
        )
        
        # Processar conteúdo
        if tipo_mensagem == "texto" and texto_recebido:
            # Sanitizar texto recebido
            texto_recebido = sanitize_user_input(texto_recebido)

            # Mensagem de texto
            db_mensagem.conteudo_texto = texto_recebido
            db_mensagem.tipo = "texto"
            fluxi_log.info("mensagem", "roteamento", "Mensagem de texto recebida", extra={"preview": texto_recebido[:50]}, session_id=sessao_id)

            # Verificar gatilho !skill <nome>
            texto_lower = texto_recebido.strip().lower()
            if texto_lower.startswith("!skill"):
                from sessao.sessao_service import gerenciador_sessoes
                cliente_skill = gerenciador_sessoes.obter_cliente(sessao_id)
                jid_skill = MensagemService._resolver_jid_destino(info, message_source, telefone_cliente) if cliente_skill else None
                partes = texto_recebido.strip().split(maxsplit=1)
                nome_skill = partes[1].strip() if len(partes) > 1 else ""
                if nome_skill:
                    from skill.skill_service import SkillService
                    skill_obj = SkillService.obter_por_nome(db, nome_skill)
                    if skill_obj and skill_obj.ativa:
                        if sessao.agente_ativo_id:
                            skills_agente = SkillService.listar_skills_agente(db, sessao.agente_ativo_id)
                            nomes_agente = {s.nome for s in skills_agente}
                            if nome_skill not in nomes_agente:
                                SkillService.atualizar_skills_agente(
                                    db, sessao.agente_ativo_id,
                                    [s.id for s in skills_agente] + [skill_obj.id]
                                )
                        resposta_skill = (
                            f"✅ *Skill ativada:* `{skill_obj.icone or ''} {skill_obj.nome}`\n"
                            f"_{skill_obj.descricao}_\n\n"
                            f"Pode enviar sua mensagem normalmente agora."
                        )
                        if cliente_skill and jid_skill:
                            cliente_skill.send_message(jid_skill, message=sanitize_user_input(resposta_skill))
                    else:
                        if cliente_skill and jid_skill:
                            cliente_skill.send_message(jid_skill, message=f"❌ Skill *{nome_skill}* não encontrada.")
                else:
                    if sessao.agente_ativo_id and cliente_skill and jid_skill:
                        from skill.skill_service import SkillService
                        skills_agente = SkillService.listar_skills_agente(db, sessao.agente_ativo_id)
                        if skills_agente:
                            lista_sk = "\n".join(f"  {s.icone or '🔧'} *{s.nome}* — {s.descricao}" for s in skills_agente)
                            cliente_skill.send_message(
                                jid_skill,
                                message=sanitize_user_input(f"🧠 *Skills deste agente:*\n\n{lista_sk}")
                            )
                        else:
                            cliente_skill.send_message(jid_skill, message="⚠️ Este agente não possui skills configuradas.")
                return

            # Verificar comandos personalizáveis
            from sessao.sessao_comando_service import SessaoComandoService
            
            # ── PROTEÇÃO PARA O CODING AGENT ────────────────────────
            # Impede que o comando genérico "#" (trocar agente) capture a mensagem "#code"
            # Se for uma mensagem pro coding agent, ignoramos os comandos personalizáveis.
            is_coding_message = False
            try:
                from coding_agent.coding_service import CodingService
                from agente.agente_model import Agente as AgenteModel
                agente_coding = db.query(AgenteModel).filter(
                    AgenteModel.sessao_id == sessao_id,
                    AgenteModel.is_coding_agent == True
                ).first()
                if agente_coding:
                    coding_session = CodingService.obter_sessao_por_agente(db, agente_coding.id)
                    if coding_session:
                        prefixo_coding = (coding_session.routing_prefix or "#code").lower()
                        if texto_lower.startswith(prefixo_coding):
                            is_coding_message = True
            except Exception as e:
                fluxi_log.warning("mensagem", "coding", "Erro na protecao do Coding Agent", exc_info=True, session_id=sessao_id)
            
            if not is_coding_message:
                comando_encontrado = SessaoComandoService.obter_por_gatilho(db, sessao_id, texto_recebido)
            else:
                comando_encontrado = None

            if comando_encontrado:
                from sessao.sessao_service import gerenciador_sessoes
                cliente = gerenciador_sessoes.obter_cliente(sessao_id)
                jid = MensagemService._resolver_jid_destino(info, message_source, telefone_cliente) if cliente else None

                # Processar comando baseado no tipo
                if comando_encontrado.comando_id == "ativar":
                    fluxi_log.info("mensagem", "comando", "Comando ativar IA", extra={"gatilho": comando_encontrado.gatilho}, session_id=sessao_id)
                    sessao.auto_responder = True
                    db.commit()

                    if cliente and jid:
                        resposta = comando_encontrado.resposta or "🤖 *IA Ativada!*"
                        resposta = sanitize_user_input(resposta)
                        cliente.send_message(jid, message=resposta)
                    return

                elif comando_encontrado.comando_id == "desativar":
                    fluxi_log.info("mensagem", "comando", "Comando desativar IA", extra={"gatilho": comando_encontrado.gatilho}, session_id=sessao_id)
                    sessao.auto_responder = False
                    db.commit()

                    if cliente and jid:
                        resposta = comando_encontrado.resposta or "😴 *IA Desativada!*"
                        resposta = sanitize_user_input(resposta)
                        cliente.send_message(jid, message=resposta)
                    return

                elif comando_encontrado.comando_id == "limpar":
                    fluxi_log.info("mensagem", "comando", "Comando limpar historico", extra={"gatilho": comando_encontrado.gatilho, "telefone": telefone_cliente}, session_id=sessao_id)

                    # Deletar histórico
                    mensagens_deletadas = db.query(Mensagem)\
                        .filter(
                            Mensagem.sessao_id == sessao_id,
                            Mensagem.telefone_cliente == telefone_cliente
                        )\
                        .delete()
                    db.commit()
                    fluxi_log.info("mensagem", "comando", "Historico limpo", extra={"mensagens_deletadas": mensagens_deletadas}, session_id=sessao_id)

                    if cliente and jid:
                        resposta = comando_encontrado.resposta or "🧹 *Histórico limpo!*\n\nSeu histórico de conversas foi apagado."
                        resposta = sanitize_user_input(resposta)
                        cliente.send_message(jid, message=resposta)
                    return

                elif comando_encontrado.comando_id == "ajuda":
                    fluxi_log.info("mensagem", "comando", "Comando ajuda", extra={"gatilho": comando_encontrado.gatilho, "telefone": telefone_cliente}, session_id=sessao_id)
                    if cliente and jid:
                        ajuda_texto = SessaoComandoService.gerar_texto_ajuda(db, sessao_id)
                        ajuda_texto = sanitize_user_input(ajuda_texto)
                        cliente.send_message(jid, message=ajuda_texto)
                    return

                elif comando_encontrado.comando_id == "status":
                    fluxi_log.info("mensagem", "comando", "Comando status", extra={"gatilho": comando_encontrado.gatilho, "telefone": telefone_cliente}, session_id=sessao_id)
                    if cliente and jid:
                        from agente.agente_service import AgenteService
                        total_msgs = db.query(Mensagem).filter(
                            Mensagem.sessao_id == sessao_id,
                            Mensagem.telefone_cliente == telefone_cliente
                        ).count()

                        agente_nome = "Nenhum"
                        if sessao.agente_ativo_id:
                            agente_ativo = AgenteService.obter_por_id(db, sessao.agente_ativo_id)
                            if agente_ativo:
                                agente_nome = f"#{agente_ativo.codigo} - {agente_ativo.nome}"

                        ia_status = "🟢 Ativada" if sessao.auto_responder else "🔴 Desativada"
                        status_texto = f"📊 *Status da Sessão:*\n\n🤖 IA: {ia_status}\n💬 Mensagens: {total_msgs}\n👤 Agente: {agente_nome}"
                        status_texto = sanitize_user_input(status_texto)
                        cliente.send_message(jid, message=status_texto)
                    return

                elif comando_encontrado.comando_id == "listar":
                    fluxi_log.info("mensagem", "comando", "Comando listar agentes", extra={"gatilho": comando_encontrado.gatilho, "telefone": telefone_cliente}, session_id=sessao_id)
                    if cliente and jid:
                        from agente.agente_service import AgenteService
                        agentes = AgenteService.listar_por_sessao_ativos(db, sessao_id)

                        if agentes:
                            comandos = SessaoComandoService.obter_comandos_dict(db, sessao_id)
                            prefixo = comandos.get("trocar_agente", {})
                            prefixo = prefixo.gatilho if hasattr(prefixo, 'gatilho') else "#"

                            lista_texto = "🤖 *Agentes Disponíveis:*\n\n"
                            for agente in agentes:
                                marcador = "✅" if sessao.agente_ativo_id == agente.id else "⚪"
                                lista_texto += f"{marcador} *{prefixo}{agente.codigo}* - {agente.nome}\n"
                                if agente.descricao:
                                    lista_texto += f"   _{agente.descricao}_\n"
                            lista_texto += f"\n💡 Digite *{prefixo}XX* para ativar um agente"
                        else:
                            lista_texto = "⚠️ *Nenhum agente disponível*"

                        lista_texto = sanitize_user_input(lista_texto)
                        cliente.send_message(jid, message=lista_texto)
                    return

                elif comando_encontrado.comando_id == "trocar_agente":
                    codigo_agente = SessaoComandoService.extrair_codigo_agente(
                        texto_recebido,
                        comando_encontrado.gatilho
                    )
                    fluxi_log.info("mensagem", "comando", "Comando troca de agente", extra={"codigo_agente": codigo_agente}, session_id=sessao_id)

                    from agente.agente_service import AgenteService
                    agente = AgenteService.obter_por_codigo(db, sessao_id, codigo_agente)

                    if agente and agente.ativo:
                        sessao.agente_ativo_id = agente.id
                        db.commit()

                        if cliente and jid:
                            if comando_encontrado.resposta:
                                confirmacao = SessaoComandoService.formatar_resposta(
                                    comando_encontrado.resposta,
                                    {
                                        "agente_nome": agente.nome,
                                        "agente_descricao": agente.descricao or "",
                                        "agente_papel": agente.agente_papel or ""
                                    }
                                )
                            else:
                                confirmacao = f"✅ *Agente Ativado!*\n\n🤖 *{agente.nome}*"
                                if agente.descricao:
                                    confirmacao += f"\n_{agente.descricao}_"
                            confirmacao = sanitize_user_input(confirmacao)
                            cliente.send_message(jid, message=confirmacao)
                        fluxi_log.info("mensagem", "comando", "Agente ativado", extra={"codigo": agente.codigo, "nome": agente.nome}, session_id=sessao_id)
                    elif cliente and jid:
                        cliente.send_message(jid, message=f"❌ Agente *{codigo_agente}* não encontrado")
                    return
            
        
        elif tipo_mensagem == "audio":
            # Mensagem com áudio
            db_mensagem.tipo = "audio"
            fluxi_log.info("mensagem", "audio", "Mensagem com audio recebida", session_id=sessao_id)

            # Baixar e transcrever áudio
            try:
                from sessao.sessao_service import gerenciador_sessoes
                from audio.transcription_service import TranscriptionService
                from security import SecurityConfig

                cliente = gerenciador_sessoes.obter_cliente(sessao_id)

                if cliente:
                    # Download do áudio
                    audio_bytes = cliente.download_any(message)

                    if audio_bytes:
                        # Obter mime type (pode vir como "audio/ogg; codecs=opus")
                        mime_type = "audio/ogg"
                        if hasattr(message.audioMessage, 'mimetype'):
                            mime_type = message.audioMessage.mimetype

                        # Validar tipo de áudio
                        from security import SecurityValidator
                        if not SecurityValidator.validate_mime_type(mime_type, SecurityConfig.ALLOWED_AUDIO_TYPES):
                            fluxi_log.warning("mensagem", "audio", "Tipo de audio nao permitido", extra={"mime_type": mime_type}, session_id=sessao_id)
                            db_mensagem.conteudo_texto = "[Tipo de áudio não suportado]"
                            db.add(db_mensagem)
                            db.commit()
                            return

                        # Validar tamanho de arquivo
                        try:
                            SecurityValidator.validate_file_size(audio_bytes)
                        except ValueError as e:
                            fluxi_log.warning("mensagem", "audio", "Arquivo de audio muito grande", exc_info=True, session_id=sessao_id)
                            db_mensagem.conteudo_texto = f"[Erro: {str(e)}]"
                            db.add(db_mensagem)
                            db.commit()
                            return

                        # Extrair extensão limpa (remover parâmetros como "; codecs=opus")
                        mime_base = mime_type.split(";")[0].strip()  # "audio/ogg; codecs=opus" -> "audio/ogg"
                        ext = mime_base.split("/")[-1] if "/" in mime_base else "ogg"

                        # Salvar áudio localmente
                        upload_base = ConfiguracaoService.obter_valor(db, "sistema_diretorio_uploads", "./uploads")
                        audio_dir = Path(upload_base) / f"sessao_{sessao_id}" / telefone_cliente
                        audio_dir.mkdir(parents=True, exist_ok=True)

                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        audio_path = audio_dir / f"audio_{timestamp}.{ext}"

                        with open(audio_path, "wb") as f:
                            f.write(audio_bytes)

                        fluxi_log.info("mensagem", "audio", "Audio salvo", extra={"path": str(audio_path)}, session_id=sessao_id)

                        # Registrar tambem na camada `midias` (media_id estavel pro agente).
                        # Falha aqui nao quebra o fluxo legado.
                        try:
                            from midia import midia_service as _midia_svc
                            _m = _midia_svc.registrar_midia(
                                db,
                                sessao_id=sessao_id,
                                chat_id=telefone_cliente,
                                conteudo=audio_bytes,
                                mime=mime_type,
                                origem="upload",
                                vinculada_tipo="mensagem",
                            )
                            db_mensagem.media_id = _m.media_id
                            db_mensagem.conteudo_texto = MensagemService._anexar_nota_midia(
                                db_mensagem.conteudo_texto, _m.media_id, "audio"
                            )
                        except Exception:
                            fluxi_log.warning("mensagem", "audio", "Falha ao registrar midia (legacy ok)", exc_info=True, session_id=sessao_id)

                        # Transcrever áudio
                        resultado_transcricao = await TranscriptionService.transcrever(
                            db,
                            audio_bytes,
                            filename=f"audio.{ext}",
                            mime_type=mime_type
                        )

                        if resultado_transcricao["sucesso"]:
                            texto_transcrito = resultado_transcricao["texto"]
                            # Sanitizar texto transcrito
                            texto_transcrito = sanitize_user_input(texto_transcrito)
                            db_mensagem.conteudo_texto = f"[Áudio transcrito]: {texto_transcrito}"
                            fluxi_log.info("mensagem", "audio", "Transcricao concluida", extra={"preview": texto_transcrito[:100]}, session_id=sessao_id)

                            # Verificar se deve apenas responder com transcrição
                            if config_tipo["acao"] == "transcricao_apenas":
                                jid = MensagemService._resolver_jid_destino(info, message_source, telefone_cliente)
                                cliente.send_message(jid, message=f"📝 *Transcrição do áudio:*\n\n{texto_transcrito}")
                                fluxi_log.info("mensagem", "audio", "Transcricao enviada ao usuario", extra={"jid": MensagemService._jid_para_log(jid)}, session_id=sessao_id)
                                # Salvar mensagem sem processar com IA
                                db_mensagem.conteudo_imagem_path = str(audio_path)
                                db_mensagem.conteudo_mime_type = mime_type
                                db.add(db_mensagem)
                                db.commit()
                                return
                        else:
                            # Transcrição falhou
                            db_mensagem.conteudo_texto = "[Áudio não transcrito]"
                            fluxi_log.warning("mensagem", "audio", "Erro na transcricao", extra={"erro": resultado_transcricao.get('erro')}, session_id=sessao_id)

                        # Guardar path do áudio
                        db_mensagem.conteudo_imagem_path = str(audio_path)
                        db_mensagem.conteudo_mime_type = mime_type

            except Exception as e:
                fluxi_log.error("mensagem", "audio", "Erro ao processar audio", exc_info=True, session_id=sessao_id)
                db_mensagem.conteudo_texto = "[Erro ao processar áudio]"
        
        elif tipo_mensagem == "imagem":
            # Mensagem com imagem
            db_mensagem.tipo = "imagem"
            db_mensagem.conteudo_texto = message.imageMessage.caption if hasattr(message.imageMessage, 'caption') and message.imageMessage.caption else ""
            fluxi_log.info("mensagem", "imagem", "Mensagem com imagem recebida", session_id=sessao_id)
            
            # Baixar imagem
            try:
                from sessao.sessao_service import gerenciador_sessoes
                cliente = gerenciador_sessoes.obter_cliente(sessao_id)
                
                if cliente:
                    # Download da imagem usando download_any
                    imagem_bytes = cliente.download_any(message)
                    
                    if imagem_bytes:
                        # Salvar imagem
                        caminho, base64_str = MensagemService.salvar_imagem(
                            imagem_bytes,
                            telefone_cliente,
                            sessao_id,
                            db
                        )

                        if caminho:
                            db_mensagem.conteudo_imagem_path = caminho
                            db_mensagem.conteudo_imagem_base64 = base64_str
                            db_mensagem.conteudo_mime_type = message.imageMessage.mimetype if hasattr(message.imageMessage, 'mimetype') else "image/jpeg"

                        # Registrar tambem na camada `midias` (media_id estavel pro agente).
                        try:
                            from midia import midia_service as _midia_svc
                            _mime = message.imageMessage.mimetype if hasattr(message.imageMessage, 'mimetype') else "image/jpeg"
                            _m = _midia_svc.registrar_midia(
                                db,
                                sessao_id=sessao_id,
                                chat_id=telefone_cliente,
                                conteudo=imagem_bytes,
                                mime=_mime,
                                origem="upload",
                                vinculada_tipo="mensagem",
                            )
                            db_mensagem.media_id = _m.media_id
                            db_mensagem.conteudo_texto = MensagemService._anexar_nota_midia(
                                db_mensagem.conteudo_texto, _m.media_id, "imagem"
                            )
                        except Exception:
                            fluxi_log.warning("mensagem", "imagem", "Falha ao registrar midia (legacy ok)", exc_info=True, session_id=sessao_id)
            except Exception as e:
                fluxi_log.error("mensagem", "imagem", "Erro ao baixar imagem", exc_info=True, session_id=sessao_id)

        elif tipo_mensagem in ("documento", "video"):
            # Documento ou video — baixa bytes via neonize, registra na camada midias.
            # Diferente de imagem/audio, NAO temos pipeline legado pra estes — sao novos.
            db_mensagem.tipo = tipo_mensagem
            caption = ""
            mime_doc = "application/octet-stream"
            try:
                if tipo_mensagem == "documento" and hasattr(message, 'documentMessage'):
                    caption = getattr(message.documentMessage, 'caption', '') or ''
                    if hasattr(message.documentMessage, 'mimetype') and message.documentMessage.mimetype:
                        mime_doc = message.documentMessage.mimetype
                elif tipo_mensagem == "video" and hasattr(message, 'videoMessage'):
                    caption = getattr(message.videoMessage, 'caption', '') or ''
                    if hasattr(message.videoMessage, 'mimetype') and message.videoMessage.mimetype:
                        mime_doc = message.videoMessage.mimetype
            except Exception:
                pass
            db_mensagem.conteudo_texto = sanitize_user_input(caption) if caption else ""

            try:
                from sessao.sessao_service import gerenciador_sessoes
                cliente = gerenciador_sessoes.obter_cliente(sessao_id)
                if cliente:
                    bytes_midia = cliente.download_any(message)
                    if bytes_midia:
                        try:
                            from security import SecurityValidator
                            SecurityValidator.validate_file_size(bytes_midia)
                        except ValueError as e:
                            fluxi_log.warning("mensagem", tipo_mensagem, "Arquivo muito grande", exc_info=True, session_id=sessao_id)
                            db_mensagem.conteudo_texto = (db_mensagem.conteudo_texto or "") + f"\n[Erro: {e}]"
                            bytes_midia = None
                    if bytes_midia:
                        from midia import midia_service as _midia_svc
                        _m = _midia_svc.registrar_midia(
                            db,
                            sessao_id=sessao_id,
                            chat_id=telefone_cliente,
                            conteudo=bytes_midia,
                            mime=mime_doc,
                            origem="upload",
                            vinculada_tipo="mensagem",
                        )
                        db_mensagem.media_id = _m.media_id
                        db_mensagem.conteudo_imagem_path = _m.path
                        db_mensagem.conteudo_mime_type = _m.mime
                        db_mensagem.conteudo_texto = MensagemService._anexar_nota_midia(
                            db_mensagem.conteudo_texto, _m.media_id, tipo_mensagem
                        )
                        fluxi_log.info(
                            "mensagem", tipo_mensagem,
                            "Midia registrada",
                            extra={"media_id": _m.media_id, "tamanho_kb": _m.tamanho_bytes / 1024},
                            session_id=sessao_id,
                        )
            except Exception:
                fluxi_log.error("mensagem", tipo_mensagem, "Erro ao baixar/registrar midia", exc_info=True, session_id=sessao_id)

        elif tipo_mensagem == "texto":
            # Evita fallback para "..." quando evento chega sem texto útil
            fluxi_log.info("mensagem", "roteamento", "Mensagem de texto vazia/sem conteudo util ignorada", session_id=sessao_id)
            return
        
        # Salvar mensagem
        db.add(db_mensagem)
        db.commit()
        db.refresh(db_mensagem)
        
        # Se auto-responder está ativo, processar com agente
        if sessao.auto_responder:
            try:
                # ── Roteamento para o Coding Agent ──────────────────────────
                # Se o texto começa com o prefixo do coding agent (ex: "#code"),
                # rotear para o CodingService em vez do AgenteService normal.
                texto_para_roteamento = (db_mensagem.conteudo_texto or "").strip()
                coding_roteado = False

                try:
                    from coding_agent.coding_service import CodingService
                    from agente.agente_model import Agente as AgenteModel

                    # Busca agente de coding desta sessão
                    agente_coding = db.query(AgenteModel).filter(
                        AgenteModel.sessao_id == sessao_id,
                        AgenteModel.is_coding_agent == True,
                        AgenteModel.ativo == True,
                    ).first()

                    if agente_coding:
                        coding_session = CodingService.obter_sessao_por_agente(db, agente_coding.id)

                        if coding_session:
                            prefixo = (coding_session.routing_prefix or "#code").lower()

                            # Verifica se deve rotear: APENAS se tiver prefixo
                            tem_prefixo = texto_para_roteamento.lower().startswith(prefixo)
                            tarefa_ativa = CodingService.obter_tarefa_ativa(
                                db, coding_session.id, telefone_cliente
                            )

                            if tem_prefixo:
                                coding_roteado = True
                                # Remove o prefixo do texto se presente
                                mensagem_coding = texto_para_roteamento
                                if tem_prefixo:
                                    mensagem_coding = texto_para_roteamento[len(prefixo):].strip()

                                jid_destino = MensagemService._resolver_jid_destino(
                                    info, message_source, telefone_cliente
                                )

                                # Notifica o usuário que o coding agent está trabalhando
                                from sessao.sessao_service import gerenciador_sessoes
                                cliente_notif = gerenciador_sessoes.obter_cliente(sessao_id)
                                if cliente_notif and not tarefa_ativa:
                                    try:
                                        cliente_notif.send_message(
                                            jid_destino,
                                            message="⚙️ *Coding Agent* iniciando tarefa..."
                                        )
                                    except Exception:
                                        pass

                                # Prepara dados para o background task
                                coding_sess_id = coding_session.id
                                tid_ativo = tarefa_ativa.id if tarefa_ativa else None
                                img_b64 = db_mensagem.conteudo_imagem_base64
                                msg_id = db_mensagem.id

                                # Despacha o coding agent para o event loop PRINCIPAL
                                # do FastAPI usando run_coroutine_threadsafe.
                                # O neonize roda cada mensagem numa thread com event loop
                                # isolado que é fechado logo após — rodar aqui causa:
                                # 1) create_task: task destruída quando loop fecha
                                # 2) await direto: funciona mas fica preso na thread
                                #    do neonize, causando lentidão (75s+ em tools simples)
                                # run_coroutine_threadsafe despacha pro loop do uvicorn
                                # que é persistente e performante.

                                # Serializa o jid_destino para passar ao coding service
                                # O jid_destino é um objeto neonize com .User e .Server
                                _jid_dest_user = str(jid_destino.User) if hasattr(jid_destino, 'User') else None
                                _jid_dest_server = str(jid_destino.Server) if hasattr(jid_destino, 'Server') else None

                                async def _processar_coding_bg():
                                    from database import SessionLocal as _CodingSessionLocal
                                    from coding_agent.coding_service import CodingService as _CS
                                    from mensagem.mensagem_model import Mensagem as MensagemModel
                                    bg_db = _CodingSessionLocal()
                                    try:
                                        resultado_coding = await _CS.processar_mensagem(
                                            db=bg_db,
                                            coding_session_id=coding_sess_id,
                                            mensagem=mensagem_coding,
                                            telefone_cliente=telefone_cliente,
                                            task_id=tid_ativo,
                                            imagem_base64=img_b64,
                                            jid_destino_user=_jid_dest_user,
                                            jid_destino_server=_jid_dest_server,
                                        )

                                        # Envia resposta final ao usuário via WhatsApp
                                        resposta_coding = resultado_coding.get("resposta", "")
                                        if resposta_coding and cliente_notif:
                                            try:
                                                cliente_notif.send_message(
                                                    jid_destino,
                                                    message=markdown_para_whatsapp(resposta_coding),
                                                )
                                            except Exception as e_send:
                                                fluxi_log.warning("mensagem", "coding", "Erro ao enviar resposta do coding agent", exc_info=True, session_id=sessao_id)

                                        # Atualiza registro de mensagem original
                                        m_original = bg_db.query(MensagemModel).filter(MensagemModel.id == msg_id).first()
                                        if m_original:
                                            m_original.resposta_texto = resposta_coding
                                            m_original.processada = True
                                            m_original.processado_em = datetime.now()
                                            m_original.respondida = bool(resposta_coding)
                                            bg_db.commit()

                                        fluxi_log.info("mensagem", "coding", "Tarefa coding concluida", extra={
                                            "task_id": resultado_coding.get('task_id'),
                                            "status": resultado_coding.get('status'),
                                            "iteracoes": resultado_coding.get('iteracoes', 0),
                                        }, session_id=sessao_id)
                                    except Exception as e_bg:
                                        fluxi_log.error("mensagem", "coding", "Erro no background task do coding agent", exc_info=True, session_id=sessao_id)
                                    finally:
                                        bg_db.close()

                                # Despacha para o event loop do FastAPI/uvicorn
                                _fl = MensagemService._fastapi_loop
                                if _fl and _fl.is_running():
                                    future = asyncio.run_coroutine_threadsafe(
                                        _processar_coding_bg(), _fl
                                    )
                                    fluxi_log.info("mensagem", "coding", "Tarefa coding despachada para loop FastAPI", extra={"telefone": telefone_cliente}, session_id=sessao_id)
                                else:
                                    # Fallback: await direto na thread do neonize
                                    fluxi_log.warning("mensagem", "coding", "Loop FastAPI indisponivel, usando await direto", session_id=sessao_id)
                                    await _processar_coding_bg()
                except Exception as e_coding:
                    fluxi_log.error("mensagem", "coding", "Erro no roteamento para coding agent", exc_info=True, session_id=sessao_id)
                    coding_roteado = False

                # Se foi roteado para o coding agent, não processa com o agente normal
                if coding_roteado:
                    with MensagemService._lock_processamento:
                        MensagemService._mensagens_em_processamento.discard(
                            f"{sessao_id}_{mensagem_id_whatsapp}"
                        )
                    return
                # ── Fim do roteamento coding ─────────────────────────────────

                # Obter histórico de mensagens do cliente (limite configurável)
                limite_historico = ConfiguracaoService.obter_valor(db, "agente_historico_mensagens", 10)
                historico = MensagemService.listar_por_cliente(
                    db,
                    sessao_id,
                    telefone_cliente,
                    limite=limite_historico
                )

                # Resolver JID de destino uma vez (preserva formato LID)
                jid_destino = MensagemService._resolver_jid_destino(info, message_source, telefone_cliente)

                # Processar com agente
                resposta = await AgenteService.processar_mensagem(
                    db,
                    sessao,
                    db_mensagem,
                    historico,
                    jid_destino=jid_destino
                )
                
                # Atualizar mensagem com resposta
                db_mensagem.resposta_texto = resposta.get("texto")
                db_mensagem.resposta_tokens_input = resposta.get("tokens_input")
                db_mensagem.resposta_tokens_output = resposta.get("tokens_output")
                db_mensagem.resposta_tempo_ms = resposta.get("tempo_ms")
                db_mensagem.resposta_modelo = resposta.get("modelo")
                db_mensagem.ferramentas_usadas = resposta.get("ferramentas")
                db_mensagem.processada = True
                db_mensagem.processado_em = datetime.now()
                
                # Enviar resposta
                if resposta.get("texto"):
                    from sessao.sessao_service import gerenciador_sessoes
                    cliente = gerenciador_sessoes.obter_cliente(sessao_id)
                    
                    if cliente:
                        jid = MensagemService._resolver_jid_destino(info, message_source, telefone_cliente)
                        # Parâmetro correto: message (str ou Message object)
                        try:
                            texto_wa = markdown_para_whatsapp(resposta["texto"])
                            cliente.send_message(jid, message=texto_wa)
                            fluxi_log.info("mensagem", "processamento", "Resposta enviada", extra={"telefone": telefone_cliente, "jid": MensagemService._jid_para_log(jid)}, session_id=sessao_id)
                            db_mensagem.respondida = True
                            db_mensagem.respondido_em = datetime.now()
                        except Exception as send_error:
                            erro_envio = f"Erro ao enviar resposta WhatsApp: {str(send_error)}"
                            fluxi_log.error("mensagem", "processamento", "Erro ao enviar resposta WhatsApp", extra={"erro": erro_envio}, session_id=sessao_id)
                            db_mensagem.resposta_erro = erro_envio
                
                db.commit()
                
            except Exception as e:
                fluxi_log.error("mensagem", "processamento", "Erro ao processar mensagem com agente", exc_info=True, session_id=sessao_id)
                
                # Salvar erro no banco
                db_mensagem.resposta_erro = str(e)
                db_mensagem.processada = True
                db_mensagem.processado_em = datetime.now()
                
                # Enviar mensagem de erro amigável para o usuário
                try:
                    from sessao.sessao_service import gerenciador_sessoes
                    cliente = gerenciador_sessoes.obter_cliente(sessao_id)
                    
                    if cliente:
                        jid = MensagemService._resolver_jid_destino(info, message_source, telefone_cliente)
                        
                        # Mensagem de erro amigável
                        erro_msg = f"❌ *Erro ao processar sua mensagem*\n\n"
                        
                        # Identificar tipo de erro
                        erro_str = str(e).lower()
                        if "api key" in erro_str or "openrouter" in erro_str:
                            erro_msg += "⚙️ O sistema não está configurado corretamente.\n"
                            erro_msg += "Por favor, contate o administrador."
                        elif "timeout" in erro_str or "connection" in erro_str:
                            erro_msg += "🌐 Problema de conexão com o servidor.\n"
                            erro_msg += "Tente novamente em alguns instantes."
                        elif "rate limit" in erro_str:
                            erro_msg += "⏱️ Muitas requisições.\n"
                            erro_msg += "Aguarde um momento e tente novamente."
                        else:
                            erro_msg += f"🔧 Erro técnico: {str(e)[:100]}\n"
                            erro_msg += "Por favor, tente novamente ou contate o suporte."
                        
                        cliente.send_message(jid, message=erro_msg)
                        fluxi_log.info("mensagem", "processamento", "Mensagem de erro enviada ao usuario", session_id=sessao_id)
                        
                        db_mensagem.respondida = True
                        db_mensagem.respondido_em = datetime.now()
                except Exception as send_error:
                    fluxi_log.error("mensagem", "processamento", "Erro ao enviar mensagem de erro", exc_info=True, session_id=sessao_id)
                
                db.commit()
        
        # Limpar lock de processamento em memória
        if mensagem_id_whatsapp:
            with MensagemService._lock_processamento:
                MensagemService._mensagens_em_processamento.discard(f"{sessao_id}_{mensagem_id_whatsapp}")

    @staticmethod
    def contar_mensagens_por_sessao(db: Session, sessao_id: int) -> int:
        """Conta total de mensagens de uma sessão."""
        return db.query(Mensagem)\
            .filter(Mensagem.sessao_id == sessao_id)\
            .count()

    @staticmethod
    def contar_mensagens_por_periodo(
        db: Session,
        sessao_id: int,
        dias: int = 7
    ) -> int:
        """Conta mensagens dos últimos N dias."""
        data_inicio = datetime.now() - timedelta(days=dias)
        return db.query(Mensagem)\
            .filter(
                Mensagem.sessao_id == sessao_id,
                Mensagem.criado_em >= data_inicio
            )\
            .count()

    @staticmethod
    def obter_clientes_unicos(db: Session, sessao_id: int) -> List[str]:
        """Obtém lista de telefones únicos que enviaram mensagens."""
        result = db.query(Mensagem.telefone_cliente)\
            .filter(Mensagem.sessao_id == sessao_id)\
            .distinct()\
            .all()
        return [r[0] for r in result]

    @staticmethod
    def obter_conversas_resumo(db: Session, sessao_id: int) -> List[dict]:
        """
        Obtém resumo de todas as conversas de uma sessão.
        Retorna lista de dicts com telefone, última mensagem, total de mensagens, etc.
        """
        from sqlalchemy import func, desc
        
        # Subquery para última mensagem de cada cliente
        subquery = db.query(
            Mensagem.telefone_cliente,
            func.max(Mensagem.criado_em).label('ultima_msg'),
            func.count(Mensagem.id).label('total_msgs')
        ).filter(
            Mensagem.sessao_id == sessao_id
        ).group_by(
            Mensagem.telefone_cliente
        ).subquery()
        
        # Query principal
        conversas = []
        clientes = db.query(subquery).order_by(desc(subquery.c.ultima_msg)).all()
        
        for cliente in clientes:
            # Buscar última mensagem
            ultima = db.query(Mensagem).filter(
                Mensagem.sessao_id == sessao_id,
                Mensagem.telefone_cliente == cliente.telefone_cliente
            ).order_by(Mensagem.criado_em.desc()).first()
            
            # Contar mensagens não respondidas
            nao_respondidas = db.query(Mensagem).filter(
                Mensagem.sessao_id == sessao_id,
                Mensagem.telefone_cliente == cliente.telefone_cliente,
                Mensagem.direcao == "recebida",
                Mensagem.respondida == False
            ).count()
            
            conversas.append({
                "telefone": cliente.telefone_cliente,
                "nome": ultima.nome_cliente if ultima and ultima.nome_cliente else None,
                "ultima_mensagem": ultima.conteudo_texto[:100] if ultima and ultima.conteudo_texto else "📷 Imagem",
                "ultima_data": ultima.criado_em if ultima else None,
                "total_mensagens": cliente.total_msgs,
                "nao_respondidas": nao_respondidas,
                "tipo_ultima": ultima.tipo if ultima else "texto"
            })
        
        return conversas

    @staticmethod
    def listar_conversa_completa(
        db: Session,
        sessao_id: int,
        telefone_cliente: str,
        limite: int = 100
    ) -> List[Mensagem]:
        """Lista todas as mensagens de uma conversa em ordem cronológica."""
        return db.query(Mensagem)\
            .filter(
                Mensagem.sessao_id == sessao_id,
                Mensagem.telefone_cliente == telefone_cliente
            )\
            .order_by(Mensagem.criado_em.asc())\
            .limit(limite)\
            .all()
