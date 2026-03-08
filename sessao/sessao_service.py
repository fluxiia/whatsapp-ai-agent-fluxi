"""
Serviço de lógica de negócio para sessões WhatsApp.
"""
from sqlalchemy.orm import Session
from typing import Optional, List, Dict
from datetime import datetime
import asyncio
import threading
import segno
import io
import base64
from neonize.client import NewClient
from neonize.events import MessageEv, ConnectedEv, QREv, PairStatusEv, LoggedOutEv
from neonize.utils import build_jid
from sessao.sessao_model import Sessao
from sessao.sessao_schema import SessaoCriar, SessaoAtualizar, SessaoStatusResposta
from config.config_service import ConfiguracaoService


class GerenciadorSessoes:
    """Gerenciador global de sessões WhatsApp."""
    
    def __init__(self):
        self.clientes: Dict[int, NewClient] = {}
        self.threads: Dict[int, threading.Thread] = {}
        self.qr_codes: Dict[int, str] = {}
    
    def obter_cliente(self, sessao_id: int) -> Optional[NewClient]:
        """Obtém o cliente WhatsApp de uma sessão."""
        return self.clientes.get(sessao_id)
    
    def adicionar_cliente(self, sessao_id: int, cliente: NewClient):
        """Adiciona um cliente ao gerenciador."""
        self.clientes[sessao_id] = cliente
    
    def remover_cliente(self, sessao_id: int):
        """Remove um cliente do gerenciador."""
        if sessao_id in self.clientes:
            del self.clientes[sessao_id]
        if sessao_id in self.threads:
            del self.threads[sessao_id]
        if sessao_id in self.qr_codes:
            del self.qr_codes[sessao_id]


# Instância global do gerenciador
gerenciador_sessoes = GerenciadorSessoes()


class SessaoService:
    """Serviço para gerenciar sessões WhatsApp."""

    @staticmethod
    def listar_todas(db: Session, apenas_ativas: bool = False) -> List[Sessao]:
        """Lista todas as sessões."""
        query = db.query(Sessao)
        if apenas_ativas:
            query = query.filter(Sessao.ativa == True)
        return query.all()

    @staticmethod
    def obter_por_id(db: Session, sessao_id: int) -> Optional[Sessao]:
        """Obtém uma sessão pelo ID."""
        return db.query(Sessao).filter(Sessao.id == sessao_id).first()

    @staticmethod
    def obter_por_nome(db: Session, nome: str) -> Optional[Sessao]:
        """Obtém uma sessão pelo nome."""
        return db.query(Sessao).filter(Sessao.nome == nome).first()

    @staticmethod
    def obter_por_telefone(db: Session, telefone: str) -> Optional[Sessao]:
        """Obtém uma sessão pelo telefone."""
        return db.query(Sessao).filter(Sessao.telefone == telefone).first()

    @staticmethod
    def criar(db: Session, sessao: SessaoCriar) -> Sessao:
        """Cria uma nova sessão e um agente padrão."""
        # Verificar se já existe sessão com mesmo nome
        existe = SessaoService.obter_por_nome(db, sessao.nome)
        if existe:
            raise ValueError(f"Já existe uma sessão com o nome '{sessao.nome}'")
        
        db_sessao = Sessao(**sessao.model_dump())
        db_sessao.status = "desconectado"
        db.add(db_sessao)
        db.commit()
        db.refresh(db_sessao)
        
        # Criar agente padrão para a sessão
        from agente.agente_service import AgenteService
        try:
            agente_padrao = AgenteService.criar_agente_padrao(db, db_sessao.id)
            # Definir como agente ativo
            db_sessao.agente_ativo_id = agente_padrao.id
            db.commit()
            db.refresh(db_sessao)
            print(f"✅ Agente padrão criado para sessão {db_sessao.nome}")
        except Exception as e:
            print(f"⚠️ Erro ao criar agente padrão: {e}")
        
        return db_sessao

    @staticmethod
    def atualizar(db: Session, sessao_id: int, sessao: SessaoAtualizar) -> Optional[Sessao]:
        """Atualiza uma sessão existente."""
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            return None

        update_data = sessao.model_dump(exclude_unset=True)
        for campo, valor in update_data.items():
            setattr(db_sessao, campo, valor)

        db.commit()
        db.refresh(db_sessao)
        return db_sessao

    @staticmethod
    def deletar(db: Session, sessao_id: int) -> bool:
        """Deleta uma sessão."""
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            return False

        # Desconectar se estiver conectado
        if db_sessao.status == "conectado":
            SessaoService.desconectar(db, sessao_id)

        db.delete(db_sessao)
        db.commit()
        return True

    @staticmethod
    def conectar(db: Session, sessao_id: int, usar_paircode: bool = False) -> SessaoStatusResposta:
        """Conecta uma sessão WhatsApp usando QR Code."""
        print(f"\n{'='*60}")
        print(f"🔌 CONECTAR SESSÃO {sessao_id}")
        print(f"{'='*60}")
        
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            raise ValueError("Sessão não encontrada")

        if not db_sessao.ativa:
            raise ValueError("Sessão está desativada")

        # Verificar se já existe cliente ativo
        cliente_existente = gerenciador_sessoes.obter_cliente(sessao_id)
        if cliente_existente:
            print(f"⚠️  Cliente já existe para sessão {sessao_id}. Usando cliente existente.")
            # Verificar se há QR Code no gerenciador
            qr_code_existente = gerenciador_sessoes.qr_codes.get(sessao_id)
            if qr_code_existente:
                print(f"✅ QR Code já existe no gerenciador")
                return SessaoStatusResposta(
                    id=db_sessao.id,
                    nome=db_sessao.nome,
                    status=db_sessao.status,
                    telefone=db_sessao.telefone,
                    qr_code=qr_code_existente,
                    mensagem="Cliente já está conectando. Use o QR Code existente."
                )
            else:
                print(f"⚠️  Cliente existe mas sem QR Code. Removendo para gerar novo...")
                gerenciador_sessoes.remover_cliente(sessao_id)

        if db_sessao.status == "conectado":
            return SessaoStatusResposta(
                id=db_sessao.id,
                nome=db_sessao.nome,
                status="conectado",
                telefone=db_sessao.telefone,
                qr_code=None,
                mensagem="Sessão já está conectada"
            )

        try:
            print(f"📦 Criando novo cliente Neonize...")
            
            # Criar diretório se não existir (configurável)
            import os
            sessao_dir = ConfiguracaoService.obter_valor(db, "sessao_diretorio", "./sessoes")
            os.makedirs(sessao_dir, exist_ok=True)
            
            # Usar banco de dados persistente (permite reconexão)
            db_path = f"{sessao_dir}/sessao_{sessao_id}.db"
            print(f"💾 Usando banco de dados: {db_path}")
            
            # Criar cliente Neonize (conforme examples/basic.py)
            cliente = NewClient(db_path)
            print(f"✅ Cliente criado")

            print(f"🎯 Registrando callback de QR Code...")
            # Configurar callback customizado para QR Code
            @cliente.qr
            def custom_qr_handler(cli: NewClient, qr_data: bytes):
                """Captura QR Code e converte para PNG base64."""
                try:
                    qr_string = qr_data.decode('utf-8')
                    print(f"🔍 QR String recebida: {qr_string[:50]}...")
                    
                    # Gerar QR Code como PNG
                    qr = segno.make(qr_string)
                    buffer = io.BytesIO()
                    qr.save(buffer, kind='png', scale=8)
                    buffer.seek(0)
                    
                    # Converter para base64
                    png_data = buffer.read()
                    base64_png = base64.b64encode(png_data).decode('utf-8')
                    print(f"🖼️  PNG gerado: {len(base64_png)} chars")
                    
                    # Salvar no gerenciador
                    gerenciador_sessoes.qr_codes[sessao_id] = base64_png
                    print(f"💾 Salvo no gerenciador: {sessao_id}")
                    
                    # Atualizar banco em nova sessão (thread-safe)
                    from database import SessionLocal
                    db_thread = SessionLocal()
                    try:
                        sessao_db = db_thread.query(Sessao).filter(Sessao.id == sessao_id).first()
                        if sessao_db:
                            sessao_db.qr_code = base64_png
                            sessao_db.qr_code_gerado_em = datetime.now()  # Timestamp
                            sessao_db.status = "conectando_qr"
                            db_thread.commit()
                            print(f"✅ Banco atualizado para sessão {sessao_id}")
                        else:
                            print(f"⚠️  Sessão {sessao_id} não encontrada no banco")
                    finally:
                        db_thread.close()
                    
                    print(f"📱 QR Code gerado para sessão {sessao_id} (PNG base64, {len(base64_png)} chars)")
                except Exception as e:
                    print(f"❌ Erro ao processar QR Code: {e}")
                    import traceback
                    traceback.print_exc()

            # Variável para armazenar telefone do PairStatus
            telefone_pareado = None
            
            @cliente.event(PairStatusEv)
            def on_pair_status(client: NewClient, event: PairStatusEv):
                """Evento de pareamento bem-sucedido."""
                nonlocal telefone_pareado
                print(f"🔗 EVENTO PAIR STATUS DISPARADO!")
                
                # Extrair telefone do JID
                if hasattr(event, 'ID') and hasattr(event.ID, 'User'):
                    telefone_pareado = event.ID.User
                    print(f"📱 Telefone pareado: {telefone_pareado}")
                else:
                    print(f"⚠️  Não foi possível extrair telefone do PairStatus")
            
            @cliente.event(ConnectedEv)
            def on_connected(client: NewClient, event: ConnectedEv):
                """Evento de conexão bem-sucedida."""
                nonlocal telefone_pareado
                print(f"🎉 EVENTO CONNECTED DISPARADO!")
                print(f"📊 Status: {event.status if hasattr(event, 'status') else 'N/A'}")
                
                # IMPORTANTE: Atualizar timestamp de conexão AQUI
                import time
                gerenciador_sessoes.clientes[f"{sessao_id}_connected_at"] = time.time()
                print(f"⏰ Timestamp de conexão atualizado")
                
                # Tentar obter telefone de várias fontes
                telefone = telefone_pareado
                
                # Se não temos telefone do PairStatus, tentar do cliente
                if not telefone:
                    try:
                        # Tentar obter do Store.ID do cliente
                        if hasattr(client, 'me') and client.me:
                            if hasattr(client.me, 'User'):
                                telefone = client.me.User
                                print(f"📱 Telefone obtido de client.me: {telefone}")
                        
                        # Tentar obter via get_me()
                        if not telefone:
                            try:
                                me_info = client.get_me()
                                if hasattr(me_info, 'User'):
                                    telefone = me_info.User
                                    print(f"📱 Telefone obtido de get_me(): {telefone}")
                            except Exception as e2:
                                print(f"⚠️  get_me() falhou: {e2}")
                    except Exception as e:
                        print(f"⚠️  Erro ao obter telefone do cliente: {e}")
                
                print(f"📱 Telefone final: {telefone}")
                
                # Atualizar banco em nova sessão (thread-safe)
                from database import SessionLocal
                db_thread = SessionLocal()
                try:
                    sessao_db = db_thread.query(Sessao).filter(Sessao.id == sessao_id).first()
                    if sessao_db:
                        sessao_db.telefone = telefone
                        sessao_db.status = "conectado"
                        sessao_db.qr_code = None
                        sessao_db.qr_code_gerado_em = None
                        sessao_db.ultima_conexao = datetime.now()
                        db_thread.commit()
                        print(f"✅ Sessão {sessao_db.nome} conectada com sucesso! Telefone: {telefone}")
                    else:
                        print(f"⚠️  Sessão {sessao_id} não encontrada no banco")
                finally:
                    db_thread.close()
                
                # Limpar QR Code do gerenciador
                if sessao_id in gerenciador_sessoes.qr_codes:
                    del gerenciador_sessoes.qr_codes[sessao_id]
                    print(f"🧹 QR Code removido do gerenciador")

            @cliente.event(LoggedOutEv)
            def on_logged_out(client: NewClient, event: LoggedOutEv):
                """Evento de logout/desconexão forçada."""
                print(f"🔴 LOGOUT DETECTADO para sessão {sessao_id}")
                print(f"📊 Razão: {event.Reason if hasattr(event, 'Reason') else 'Desconhecida'}")
                
                # Atualizar banco em nova sessão (thread-safe)
                from database import SessionLocal
                db_thread = SessionLocal()
                try:
                    sessao_db = db_thread.query(Sessao).filter(Sessao.id == sessao_id).first()
                    if sessao_db:
                        sessao_db.status = "desconectado"
                        sessao_db.qr_code = None
                        sessao_db.qr_code_gerado_em = None
                        db_thread.commit()
                        print(f"✅ Sessão {sessao_id} marcada como desconectada no banco")
                    else:
                        print(f"⚠️  Sessão {sessao_id} não encontrada no banco")
                finally:
                    db_thread.close()
                
                # Remover cliente do gerenciador
                gerenciador_sessoes.remover_cliente(sessao_id)
                print(f"🧹 Cliente removido do gerenciador")
                
                # Limpar arquivo de sessão para forçar novo login
                try:
                    import os
                    from database import SessionLocal
                    db_temp = SessionLocal()
                    try:
                        sessao_dir = ConfiguracaoService.obter_valor(db_temp, "sessao_diretorio", "./sessoes")
                    finally:
                        db_temp.close()
                    db_path = f"{sessao_dir}/sessao_{sessao_id}.db"
                    if os.path.exists(db_path):
                        os.remove(db_path)
                        print(f"🗑️  Arquivo de sessão removido: {db_path}")
                except Exception as e:
                    print(f"⚠️  Erro ao remover arquivo de sessão: {e}")

            @cliente.event(MessageEv)
            def on_message(client: NewClient, event: MessageEv):
                """Evento de mensagem recebida."""
                try:
                    # Ignorar mensagens enviadas por mim
                    if hasattr(event.Info, 'IsFromMe') and event.Info.IsFromMe:
                        return
                    
                    # Ignorar mensagens dos primeiros segundos (history sync - configurável)
                    import time
                    from config.config_service import ConfiguracaoService
                    from database import SessionLocal
                    db_config = SessionLocal()
                    try:
                        history_sync_delay = ConfiguracaoService.obter_valor(db_config, "sessao_history_sync_delay", 5)
                    finally:
                        db_config.close()
                    connected_at = gerenciador_sessoes.clientes.get(f"{sessao_id}_connected_at", 0)
                    if time.time() - connected_at < history_sync_delay:
                        print(f"⏭️  Ignorando mensagem (history sync - primeiros {history_sync_delay}s)")
                        return
                    
                    sender_jid = event.Info.MessageSource.Sender
                    print(f"📨 Mensagem NOVA recebida de {sender_jid}")
                    
                    # Processar mensagem em thread separada (síncrona)
                    def processar_thread():
                        from database import SessionLocal
                        from mensagem.mensagem_service import MensagemService
                        
                        # Criar nova sessão do banco (thread-safe)
                        db_thread = SessionLocal()
                        try:
                            # Processar mensagem de forma síncrona
                            import asyncio
                            
                            # Criar event loop para esta thread
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            
                            try:
                                loop.run_until_complete(
                                    MensagemService.processar_mensagem_recebida(
                                        db_thread, sessao_id, event
                                    )
                                )
                            finally:
                                loop.close()
                                
                        except Exception as e:
                            print(f"❌ Erro ao processar mensagem: {e}")
                            import traceback
                            traceback.print_exc()
                        finally:
                            db_thread.close()
                    
                    # Executar em thread separada
                    thread = threading.Thread(target=processar_thread, daemon=True)
                    thread.start()
                    
                except Exception as e:
                    print(f"❌ Erro no handler de mensagem: {e}")
                    import traceback
                    traceback.print_exc()

            # Adicionar cliente ao gerenciador
            gerenciador_sessoes.adicionar_cliente(sessao_id, cliente)
            
            # Timestamp de quando conectou (para ignorar history sync)
            import time
            gerenciador_sessoes.clientes[f"{sessao_id}_connected_at"] = time.time()

            # Conectar em thread separada
            def conectar_thread():
                try:
                    print(f"🔌 Thread de conexão iniciada para sessão {sessao_id}")
                    print(f"📱 Chamando cliente.connect()...")
                    cliente.connect()
                    print(f"✅ cliente.connect() finalizado")
                except Exception as e:
                    print(f"❌ Erro ao conectar sessão {sessao_id}: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # Atualizar banco em nova sessão
                    from database import SessionLocal
                    db_thread = SessionLocal()
                    try:
                        sessao_db = db_thread.query(Sessao).filter(Sessao.id == sessao_id).first()
                        if sessao_db:
                            sessao_db.status = "erro"
                            db_thread.commit()
                    finally:
                        db_thread.close()

            print(f"🚀 Criando thread de conexão para sessão {sessao_id}")
            thread = threading.Thread(target=conectar_thread, daemon=True)
            thread.start()
            gerenciador_sessoes.threads[sessao_id] = thread
            print(f"✅ Thread iniciada: {thread.is_alive()}")

            # Atualizar status inicial
            db_sessao.status = "iniciando"
            db.commit()

            return SessaoStatusResposta(
                id=db_sessao.id,
                nome=db_sessao.nome,
                status="iniciando",
                telefone=None,
                qr_code=None,
                mensagem="Iniciando conexão via QR Code..."
            )

        except Exception as e:
            db_sessao.status = "erro"
            db.commit()
            raise ValueError(f"Erro ao conectar: {str(e)}")

    @staticmethod
    def reconectar_sessao(db: Session, sessao_id: int):
        """Reconecta uma sessão usando o banco de dados salvo (sem gerar QR Code)."""
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            raise ValueError("Sessão não encontrada")
        
        # Verificar se já existe cliente ativo
        cliente_existente = gerenciador_sessoes.obter_cliente(sessao_id)
        if cliente_existente:
            print(f"✅ Sessão {sessao_id} já está conectada")
            return
        
        try:
            import os
            import threading
            
            # Criar cliente Neonize com banco de dados (mantém sessão)
            sessao_dir = ConfiguracaoService.obter_valor(db, "sessao_diretorio", "./sessoes")
            db_path = f"{sessao_dir}/sessao_{sessao_id}.db"
            
            # Verificar se existe banco de dados salvo
            if not os.path.exists(db_path):
                print(f"⚠️  Sem banco de dados salvo para sessão {sessao_id}")
                db_sessao.status = "desconectado"
                db.commit()
                return
            
            print(f"📦 Criando cliente com banco salvo: {db_path}")
            # Criar cliente Neonize (conforme examples/basic.py)
            cliente = NewClient(db_path)
            
            # Configurar eventos (mesmo código do conectar)
            @cliente.qr
            def custom_qr_handler(cli: NewClient, qr_data: bytes):
                """Captura QR Code (não deve ser chamado na reconexão)."""
                print(f"⚠️  QR Code gerado durante reconexão (não esperado)")
            
            # Variável para armazenar telefone do PairStatus
            telefone_pareado = None
            
            @cliente.event(PairStatusEv)
            def on_pair_status(client: NewClient, event: PairStatusEv):
                nonlocal telefone_pareado
                if hasattr(event, 'ID') and hasattr(event.ID, 'User'):
                    telefone_pareado = event.ID.User
            
            @cliente.event(ConnectedEv)
            def on_connected(client: NewClient, event: ConnectedEv):
                nonlocal telefone_pareado
                print(f"🎉 Sessão {sessao_id} reconectada!")
                
                # IMPORTANTE: Atualizar timestamp de conexão AQUI
                import time
                gerenciador_sessoes.clientes[f"{sessao_id}_connected_at"] = time.time()
                print(f"⏰ Timestamp de conexão atualizado")
                
                telefone = telefone_pareado
                if not telefone:
                    try:
                        if hasattr(client, 'me') and client.me:
                            if hasattr(client.me, 'User'):
                                telefone = client.me.User
                        if not telefone:
                            try:
                                me_info = client.get_me()
                                if hasattr(me_info, 'User'):
                                    telefone = me_info.User
                            except:
                                pass
                    except:
                        pass
                
                # Atualizar banco
                from database import SessionLocal
                db_thread = SessionLocal()
                try:
                    sessao_db = db_thread.query(Sessao).filter(Sessao.id == sessao_id).first()
                    if sessao_db:
                        sessao_db.telefone = telefone
                        sessao_db.status = "conectado"
                        sessao_db.ultima_conexao = datetime.now()
                        db_thread.commit()
                finally:
                    db_thread.close()
            
            @cliente.event(LoggedOutEv)
            def on_logged_out(client: NewClient, event: LoggedOutEv):
                """Evento de logout/desconexão forçada (reconexão)."""
                print(f"🔴 LOGOUT DETECTADO para sessão {sessao_id}")
                print(f"📊 Razão: {event.Reason if hasattr(event, 'Reason') else 'Desconhecida'}")
                
                # Atualizar banco
                from database import SessionLocal
                db_thread = SessionLocal()
                try:
                    sessao_db = db_thread.query(Sessao).filter(Sessao.id == sessao_id).first()
                    if sessao_db:
                        sessao_db.status = "desconectado"
                        sessao_db.qr_code = None
                        sessao_db.qr_code_gerado_em = None
                        db_thread.commit()
                        print(f"✅ Sessão {sessao_id} marcada como desconectada")
                finally:
                    db_thread.close()
                
                # Remover cliente do gerenciador
                gerenciador_sessoes.remover_cliente(sessao_id)
                print(f"🧹 Cliente removido do gerenciador")
                
                # Limpar arquivo de sessão
                try:
                    import os
                    from database import SessionLocal
                    db_temp = SessionLocal()
                    try:
                        sessao_dir = ConfiguracaoService.obter_valor(db_temp, "sessao_diretorio", "./sessoes")
                    finally:
                        db_temp.close()
                    db_path = f"{sessao_dir}/sessao_{sessao_id}.db"
                    if os.path.exists(db_path):
                        os.remove(db_path)
                        print(f"🗑️  Arquivo de sessão removido: {db_path}")
                except Exception as e:
                    print(f"⚠️  Erro ao remover arquivo de sessão: {e}")

            @cliente.event(MessageEv)
            def on_message(client: NewClient, event: MessageEv):
                """Evento de mensagem recebida."""
                try:
                    print(f"🔔 EVENTO MessageEv DISPARADO para sessão {sessao_id}")
                    
                    # Verificar se é mensagem própria
                    if hasattr(event.Info, 'IsFromMe') and event.Info.IsFromMe:
                        print(f"⏭️  Mensagem ignorada: IsFromMe=True")
                        return
                    
                    # Verificar filtro de tempo (configurável)
                    import time
                    from database import SessionLocal
                    db_config = SessionLocal()
                    try:
                        history_sync_delay = ConfiguracaoService.obter_valor(db_config, "sessao_history_sync_delay", 5)
                    finally:
                        db_config.close()
                    connected_at = gerenciador_sessoes.clientes.get(f"{sessao_id}_connected_at", 0)
                    tempo_desde_conexao = time.time() - connected_at
                    print(f"⏱️  Tempo desde conexão: {tempo_desde_conexao:.1f}s (limite: {history_sync_delay}s)")
                    
                    if tempo_desde_conexao < history_sync_delay:
                        print(f"⏭️  Mensagem ignorada: history sync ({tempo_desde_conexao:.1f}s < {history_sync_delay}s)")
                        return
                    
                    sender_jid = event.Info.MessageSource.Sender
                    print(f"📨 Mensagem NOVA recebida de {sender_jid}")
                    
                    def processar_thread():
                        from database import SessionLocal
                        from mensagem.mensagem_service import MensagemService
                        
                        db_thread = SessionLocal()
                        try:
                            import asyncio
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(
                                    MensagemService.processar_mensagem_recebida(
                                        db_thread, sessao_id, event
                                    )
                                )
                            finally:
                                loop.close()
                        except Exception as e:
                            print(f"❌ Erro ao processar mensagem: {e}")
                            import traceback
                            traceback.print_exc()
                        finally:
                            db_thread.close()
                    
                    thread = threading.Thread(target=processar_thread, daemon=True)
                    thread.start()
                except Exception as e:
                    print(f"❌ Erro no handler de mensagem: {e}")
            
            # Adicionar cliente ao gerenciador
            gerenciador_sessoes.adicionar_cliente(sessao_id, cliente)
            
            import time
            gerenciador_sessoes.clientes[f"{sessao_id}_connected_at"] = time.time()
            
            # Conectar em thread separada
            def conectar_thread():
                try:
                    cliente.connect()
                except Exception as e:
                    print(f"❌ Erro ao reconectar sessão {sessao_id}: {e}")
                    from database import SessionLocal
                    db_thread = SessionLocal()
                    try:
                        sessao_db = db_thread.query(Sessao).filter(Sessao.id == sessao_id).first()
                        if sessao_db:
                            sessao_db.status = "erro"
                            db_thread.commit()
                    finally:
                        db_thread.close()
            
            thread = threading.Thread(target=conectar_thread, daemon=True)
            thread.start()
            gerenciador_sessoes.threads[sessao_id] = thread
            
        except Exception as e:
            print(f"❌ Erro ao reconectar: {e}")
            db_sessao.status = "erro"
            db.commit()

    @staticmethod
    def desconectar(db: Session, sessao_id: int) -> SessaoStatusResposta:
        """Desconecta uma sessão WhatsApp."""
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            raise ValueError("Sessão não encontrada")

        # Remover cliente do gerenciador
        cliente = gerenciador_sessoes.obter_cliente(sessao_id)
        if cliente:
            try:
                # Desconectar cliente
                # Note: Neonize não tem método disconnect explícito
                # O cliente será desconectado quando a thread terminar
                pass
            except Exception as e:
                print(f"Erro ao desconectar: {e}")

        gerenciador_sessoes.remover_cliente(sessao_id)

        # Atualizar status
        db_sessao.status = "desconectado"
        db_sessao.qr_code = None
        db.commit()

        return SessaoStatusResposta(
            id=db_sessao.id,
            nome=db_sessao.nome,
            status="desconectado",
            telefone=db_sessao.telefone,
            qr_code=None,
            mensagem="Sessão desconectada com sucesso"
        )

    @staticmethod
    def obter_status(db: Session, sessao_id: int) -> SessaoStatusResposta:
        """Obtém o status atual de uma sessão."""
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            raise ValueError("Sessão não encontrada")

        # Verificar se há QR Code disponível
        qr_code = gerenciador_sessoes.qr_codes.get(sessao_id)

        return SessaoStatusResposta(
            id=db_sessao.id,
            nome=db_sessao.nome,
            status=db_sessao.status,
            telefone=db_sessao.telefone,
            qr_code=qr_code or db_sessao.qr_code,
            mensagem=f"Status: {db_sessao.status}"
        )

    @staticmethod
    def enviar_mensagem(
        db: Session,
        sessao_id: int,
        telefone_destino: str,
        texto: str
    ) -> bool:
        """Envia uma mensagem através de uma sessão."""
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            raise ValueError("Sessão não encontrada")

        if db_sessao.status != "conectado":
            raise ValueError("Sessão não está conectada")

        cliente = gerenciador_sessoes.obter_cliente(sessao_id)
        if not cliente:
            raise ValueError("Cliente WhatsApp não encontrado")

        try:
            # Construir JID
            jid = build_jid(telefone_destino)
            
            # Enviar mensagem
            cliente.send_message(jid, message=texto)
            
            return True
        except Exception as e:
            raise ValueError(f"Erro ao enviar mensagem: {str(e)}")
