"""
Serviço de lógica de negócio para mensagens.
"""
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
from config.config_service import ConfiguracaoService


class MensagemService:
    """Serviço para gerenciar mensagens."""

    @staticmethod
    def _resolver_jid_destino(info, message_source, telefone_cliente):
        """Resolve o JID de destino priorizando o chat real do evento (inclui LID)."""
        from neonize.utils import build_jid

        chat_jid = getattr(info, 'Chat', None)
        if chat_jid and hasattr(chat_jid, 'User') and chat_jid.User and hasattr(chat_jid, 'Server') and chat_jid.Server:
            return chat_jid

        sender_alt = getattr(message_source, 'SenderAlt', None)
        if sender_alt and hasattr(sender_alt, 'User') and sender_alt.User and hasattr(sender_alt, 'Server') and sender_alt.Server:
            if sender_alt.Server == "s.whatsapp.net":
                return build_jid(sender_alt.User)
            return sender_alt

        sender = getattr(message_source, 'Sender', None)
        if sender and hasattr(sender, 'User') and sender.User and hasattr(sender, 'Server') and sender.Server:
            if sender.Server == "s.whatsapp.net":
                return build_jid(sender.User)
            return sender

        return build_jid(telefone_cliente)

    @staticmethod
    def _jid_para_log(jid) -> str:
        """Formata JID para logs de roteamento."""
        user = getattr(jid, 'User', '?')
        server = getattr(jid, 'Server', '?')
        return f"{user}@{server}"

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
            img = Image.open(io.BytesIO(imagem_bytes))
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            # Salvar com qualidade configurável
            img.save(filepath, 'JPEG', quality=int(qualidade_jpeg))
            
            # Converter para base64
            base64_string = base64.b64encode(imagem_bytes).decode('utf-8')
            
            return str(filepath), base64_string
        except Exception as e:
            print(f"Erro ao salvar imagem: {e}")
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
            print(f"⚠️ Sender em formato LID detectado. SenderAlt usado={bool(getattr(message_source, 'SenderAlt', None))}")
        
        # Obter sessão
        sessao = SessaoService.obter_por_id(db, sessao_id)
        if not sessao or not sessao.ativa:
            return

        # Ignorar mensagens duplicadas (idempotência)
        mensagem_id_whatsapp = getattr(info, 'ID', None)
        if mensagem_id_whatsapp:
            mensagem_existente = db.query(Mensagem).filter(
                Mensagem.sessao_id == sessao_id,
                Mensagem.mensagem_id_whatsapp == mensagem_id_whatsapp
            ).first()
            if mensagem_existente:
                print(f"⏭️ Mensagem duplicada ignorada: {mensagem_id_whatsapp}")
                return
        
        # Detectar tipo de mensagem e verificar configuração
        tipo_mensagem = MensagemService._detectar_tipo_mensagem(message)
        texto_recebido = MensagemService._extrair_texto_mensagem(message)
        config_tipo = SessaoTipoMensagemService.obter_acao(db, sessao_id, tipo_mensagem)
        
        # Se for ignorar e não for texto, retornar
        if tipo_mensagem != "texto" and config_tipo["acao"] == "ignorar":
            print(f"🚫 Ignorando mensagem do tipo: {tipo_mensagem}")
            return
        
        # Se for resposta fixa, enviar e retornar
        if tipo_mensagem != "texto" and config_tipo["acao"] == "resposta_fixa" and config_tipo["resposta_fixa"]:
            from sessao.sessao_service import gerenciador_sessoes
            cliente = gerenciador_sessoes.obter_cliente(sessao_id)
            if cliente:
                jid = MensagemService._resolver_jid_destino(info, message_source, telefone_cliente)
                cliente.send_message(jid, message=config_tipo["resposta_fixa"])
                print(f"📤 Resposta fixa enviada para {tipo_mensagem} em {MensagemService._jid_para_log(jid)}")
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
            # Mensagem de texto
            db_mensagem.conteudo_texto = texto_recebido
            db_mensagem.tipo = "texto"
            print(f"📝 Mensagem de texto: {texto_recebido[:50]}...")
            
            # Verificar comandos personalizáveis
            from sessao.sessao_comando_service import SessaoComandoService
            comando_encontrado = SessaoComandoService.obter_por_gatilho(db, sessao_id, texto_recebido)
            
            if comando_encontrado:
                from sessao.sessao_service import gerenciador_sessoes
                cliente = gerenciador_sessoes.obter_cliente(sessao_id)
                jid = MensagemService._resolver_jid_destino(info, message_source, telefone_cliente) if cliente else None
                
                # Processar comando baseado no tipo
                if comando_encontrado.comando_id == "ativar":
                    print(f"🤖 Comando {comando_encontrado.gatilho} - Ativando IA")
                    sessao.auto_responder = True
                    db.commit()
                    
                    if cliente and jid:
                        resposta = comando_encontrado.resposta or "🤖 *IA Ativada!*"
                        cliente.send_message(jid, message=resposta)
                    return
                
                elif comando_encontrado.comando_id == "desativar":
                    print(f"😴 Comando {comando_encontrado.gatilho} - Desativando IA")
                    sessao.auto_responder = False
                    db.commit()
                    
                    if cliente and jid:
                        resposta = comando_encontrado.resposta or "😴 *IA Desativada!*"
                        cliente.send_message(jid, message=resposta)
                    return
                
                elif comando_encontrado.comando_id == "limpar":
                    print(f"🧹 Comando {comando_encontrado.gatilho} recebido de {telefone_cliente}")
                    
                    # Deletar histórico
                    mensagens_deletadas = db.query(Mensagem)\
                        .filter(
                            Mensagem.sessao_id == sessao_id,
                            Mensagem.telefone_cliente == telefone_cliente
                        )\
                        .delete()
                    db.commit()
                    print(f"✅ {mensagens_deletadas} mensagem(ns) deletada(s)")
                    
                    if cliente and jid:
                        resposta = comando_encontrado.resposta or "🧹 *Histórico limpo!*\n\nSeu histórico de conversas foi apagado."
                        cliente.send_message(jid, message=resposta)
                    return
                
                elif comando_encontrado.comando_id == "ajuda":
                    print(f"ℹ️  Comando {comando_encontrado.gatilho} recebido de {telefone_cliente}")
                    if cliente and jid:
                        ajuda_texto = SessaoComandoService.gerar_texto_ajuda(db, sessao_id)
                        cliente.send_message(jid, message=ajuda_texto)
                    return
                
                elif comando_encontrado.comando_id == "status":
                    print(f"📊 Comando {comando_encontrado.gatilho} recebido de {telefone_cliente}")
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
                        cliente.send_message(jid, message=status_texto)
                    return
                
                elif comando_encontrado.comando_id == "listar":
                    print(f"📋 Comando {comando_encontrado.gatilho} recebido de {telefone_cliente}")
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
                        
                        cliente.send_message(jid, message=lista_texto)
                    return
                
                elif comando_encontrado.comando_id == "trocar_agente":
                    codigo_agente = SessaoComandoService.extrair_codigo_agente(
                        texto_recebido,
                        comando_encontrado.gatilho
                    )
                    print(f"🔄 Comando de troca de agente: {codigo_agente}")
                    
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
                            cliente.send_message(jid, message=confirmacao)
                        print(f"✅ Agente {agente.codigo} ativado")
                    elif cliente and jid:
                        cliente.send_message(jid, message=f"❌ Agente *{codigo_agente}* não encontrado")
                    return
            
        
        elif tipo_mensagem == "audio":
            # Mensagem com áudio
            db_mensagem.tipo = "audio"
            print(f"🎵 Mensagem com áudio")
            
            # Baixar e transcrever áudio
            try:
                from sessao.sessao_service import gerenciador_sessoes
                from audio.transcription_service import TranscriptionService
                
                cliente = gerenciador_sessoes.obter_cliente(sessao_id)
                
                if cliente:
                    # Download do áudio
                    audio_bytes = cliente.download_any(message)
                    
                    if audio_bytes:
                        # Obter mime type (pode vir como "audio/ogg; codecs=opus")
                        mime_type = "audio/ogg"
                        if hasattr(message.audioMessage, 'mimetype'):
                            mime_type = message.audioMessage.mimetype
                        
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
                        
                        print(f"💾 Áudio salvo: {audio_path}")
                        
                        # Transcrever áudio
                        resultado_transcricao = await TranscriptionService.transcrever(
                            db,
                            audio_bytes,
                            filename=f"audio.{ext}",
                            mime_type=mime_type
                        )
                        
                        if resultado_transcricao["sucesso"]:
                            texto_transcrito = resultado_transcricao["texto"]
                            db_mensagem.conteudo_texto = f"[Áudio transcrito]: {texto_transcrito}"
                            print(f"📝 Transcrição: {texto_transcrito[:100]}...")
                            
                            # Verificar se deve apenas responder com transcrição
                            if config_tipo["acao"] == "transcricao_apenas":
                                jid = MensagemService._resolver_jid_destino(info, message_source, telefone_cliente)
                                cliente.send_message(jid, message=f"📝 *Transcrição do áudio:*\n\n{texto_transcrito}")
                                print(f"📤 Transcrição enviada ao usuário em {MensagemService._jid_para_log(jid)}")
                                # Salvar mensagem sem processar com IA
                                db_mensagem.conteudo_imagem_path = str(audio_path)
                                db_mensagem.conteudo_mime_type = mime_type
                                db.add(db_mensagem)
                                db.commit()
                                return
                        else:
                            # Transcrição falhou
                            db_mensagem.conteudo_texto = "[Áudio não transcrito]"
                            print(f"⚠️ Erro na transcrição: {resultado_transcricao.get('erro')}")
                        
                        # Guardar path do áudio
                        db_mensagem.conteudo_imagem_path = str(audio_path)
                        db_mensagem.conteudo_mime_type = mime_type
                        
            except Exception as e:
                print(f"Erro ao processar áudio: {e}")
                import traceback
                traceback.print_exc()
                db_mensagem.conteudo_texto = "[Erro ao processar áudio]"
        
        elif tipo_mensagem == "imagem":
            # Mensagem com imagem
            db_mensagem.tipo = "imagem"
            db_mensagem.conteudo_texto = message.imageMessage.caption if hasattr(message.imageMessage, 'caption') and message.imageMessage.caption else ""
            print(f"🖼️  Mensagem com imagem")
            
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
            except Exception as e:
                print(f"Erro ao baixar imagem: {e}")

        elif tipo_mensagem == "texto":
            # Evita fallback para "..." quando evento chega sem texto útil
            print("⏭️ Mensagem de texto vazia/sem conteúdo útil ignorada")
            return
        
        # Salvar mensagem
        db.add(db_mensagem)
        db.commit()
        db.refresh(db_mensagem)
        
        # Se auto-responder está ativo, processar com agente
        if sessao.auto_responder:
            try:
                # Obter histórico de mensagens do cliente (limite configurável)
                limite_historico = ConfiguracaoService.obter_valor(db, "agente_historico_mensagens", 10)
                historico = MensagemService.listar_por_cliente(
                    db,
                    sessao_id,
                    telefone_cliente,
                    limite=limite_historico
                )
                
                # Processar com agente
                resposta = await AgenteService.processar_mensagem(
                    db,
                    sessao,
                    db_mensagem,
                    historico
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
                            cliente.send_message(jid, message=resposta["texto"])
                            print(f"📤 Resposta enviada para {telefone_cliente} via {MensagemService._jid_para_log(jid)}")
                            db_mensagem.respondida = True
                            db_mensagem.respondido_em = datetime.now()
                        except Exception as send_error:
                            erro_envio = f"Erro ao enviar resposta WhatsApp: {str(send_error)}"
                            print(f"❌ {erro_envio}")
                            db_mensagem.resposta_erro = erro_envio
                
                db.commit()
                
            except Exception as e:
                print(f"Erro ao processar mensagem com agente: {e}")
                
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
                        print(f"📤 Mensagem de erro enviada ao usuário")
                        
                        db_mensagem.respondida = True
                        db_mensagem.respondido_em = datetime.now()
                except Exception as send_error:
                    print(f"❌ Erro ao enviar mensagem de erro: {send_error}")
                
                db.commit()

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
