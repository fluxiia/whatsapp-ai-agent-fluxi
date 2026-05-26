"""
Serviço de lógica de negócio para sessões (multi-canal: WhatsApp + Telegram).

A conexão de fato é delegada para um `CanalClient` (canal/canal_*.py). O
GerenciadorSessoes mantém um adapter por sessão e roteia callbacks
(`on_mensagem`, `on_status`) para MensagemService e atualização de banco.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from canal.canal_base import CanalClient, EventoMensagem, Plataforma, StatusConexao
from canal.canal_factory import criar_canal
from config.config_service import ConfiguracaoService
from sessao.sessao_model import Sessao
from sessao.sessao_schema import SessaoAtualizar, SessaoCriar, SessaoStatusResposta

logger = logging.getLogger(__name__)


class GerenciadorSessoes:
    """Gerenciador global de adapters de canal por sessão."""

    def __init__(self):
        self.clientes: Dict[int, CanalClient] = {}
        self._lock = threading.Lock()

    def obter_cliente(self, sessao_id: int) -> Optional[CanalClient]:
        """Obtém o adapter de canal de uma sessão (genérico, qualquer plataforma)."""
        return self.clientes.get(sessao_id)

    def adicionar_cliente(self, sessao_id: int, canal: CanalClient):
        with self._lock:
            self.clientes[sessao_id] = canal

    def remover_cliente(self, sessao_id: int):
        with self._lock:
            self.clientes.pop(sessao_id, None)


gerenciador_sessoes = GerenciadorSessoes()


def _build_on_mensagem(sessao_id: int):
    """Callback chamado pelo adapter quando uma mensagem chega.

    Roda em thread/loop do próprio adapter — abre sessão de DB própria.
    """

    def on_mensagem(evento: EventoMensagem):
        from database import SessionLocal
        from mensagem.mensagem_service import MensagemService

        db = SessionLocal()
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    MensagemService.processar_evento_canal(db, evento)
                )
            finally:
                loop.close()
        except Exception:
            logger.exception("Erro ao processar evento canal (sessão %s)", sessao_id)
        finally:
            db.close()

    return on_mensagem


def _build_on_status(sessao_id: int):
    """Callback chamado pelo adapter ao mudar status de conexão."""

    def on_status(status: StatusConexao, info: Optional[str]):
        from database import SessionLocal

        db = SessionLocal()
        try:
            sessao_db = db.query(Sessao).filter(Sessao.id == sessao_id).first()
            if not sessao_db:
                logger.warning("Sessão %s não encontrada ao atualizar status", sessao_id)
                return

            if status == StatusConexao.CONECTANDO_QR:
                sessao_db.status = "conectando_qr"
                sessao_db.qr_code = info  # info = base64 PNG
                sessao_db.qr_code_gerado_em = datetime.now()
            elif status == StatusConexao.CONECTADO:
                sessao_db.status = "conectado"
                sessao_db.qr_code = None
                sessao_db.qr_code_gerado_em = None
                sessao_db.ultima_conexao = datetime.now()
                # info = identificador (telefone p/ WA, @username p/ TG)
                if info:
                    sessao_db.identificador = info
                    if sessao_db.plataforma == "whatsapp":
                        sessao_db.telefone = info
            elif status == StatusConexao.INICIANDO:
                sessao_db.status = "iniciando"
            elif status == StatusConexao.DESCONECTADO:
                sessao_db.status = "desconectado"
                sessao_db.qr_code = None
                sessao_db.qr_code_gerado_em = None
                gerenciador_sessoes.remover_cliente(sessao_id)
            elif status == StatusConexao.ERRO:
                sessao_db.status = "erro"
                logger.error("Sessão %s em erro: %s", sessao_id, info)

            db.commit()
        except Exception:
            logger.exception("Erro ao atualizar status da sessão %s", sessao_id)
        finally:
            db.close()

    return on_status


class SessaoService:
    """Serviço para gerenciar sessões multi-canal."""

    # ----- CRUD -----

    @staticmethod
    def listar_todas(db: Session, apenas_ativas: bool = False) -> List[Sessao]:
        query = db.query(Sessao)
        if apenas_ativas:
            query = query.filter(Sessao.ativa == True)
        return query.all()

    @staticmethod
    def obter_por_id(db: Session, sessao_id: int) -> Optional[Sessao]:
        return db.query(Sessao).filter(Sessao.id == sessao_id).first()

    @staticmethod
    def obter_por_nome(db: Session, nome: str) -> Optional[Sessao]:
        return db.query(Sessao).filter(Sessao.nome == nome).first()

    @staticmethod
    def obter_por_telefone(db: Session, telefone: str) -> Optional[Sessao]:
        return db.query(Sessao).filter(Sessao.telefone == telefone).first()

    @staticmethod
    def criar(db: Session, sessao: SessaoCriar) -> Sessao:
        """Cria uma nova sessão e um agente padrão."""
        existe = SessaoService.obter_por_nome(db, sessao.nome)
        if existe:
            raise ValueError(f"Já existe uma sessão com o nome '{sessao.nome}'")

        plataforma = (sessao.plataforma or "whatsapp").lower()
        if plataforma not in ("whatsapp", "telegram", "webchat"):
            raise ValueError(f"Plataforma inválida: {plataforma}")

        dados = sessao.model_dump(exclude={"telegram_bot_token"})
        dados["plataforma"] = plataforma

        if plataforma == "telegram":
            if not sessao.telegram_bot_token:
                raise ValueError("telegram_bot_token é obrigatório para plataforma=telegram")
            from canal.canal_credenciais import criptografar, descriptografar

            # Telegram: bot_token único por sessão ativa (polling duplo dá conflito 409).
            for outra in db.query(Sessao).filter(
                Sessao.plataforma == "telegram", Sessao.ativa == True
            ).all():
                creds = descriptografar(outra.credenciais)
                if creds.get("bot_token") == sessao.telegram_bot_token:
                    raise ValueError(
                        f"Esse bot_token já está em uso na sessão '{outra.nome}'"
                    )
            dados["credenciais"] = criptografar({"bot_token": sessao.telegram_bot_token})

        db_sessao = Sessao(**dados)
        db_sessao.status = "desconectado"
        db.add(db_sessao)
        db.commit()
        db.refresh(db_sessao)

        from agente.agente_service import AgenteService
        try:
            agente_padrao = AgenteService.criar_agente_padrao(db, db_sessao.id)
            db_sessao.agente_ativo_id = agente_padrao.id
            db.commit()
            db.refresh(db_sessao)
            logger.info("Agente padrão criado para sessão %s", db_sessao.nome)
        except Exception as e:
            logger.warning("Erro ao criar agente padrão: %s", e)

        try:
            from coding_agent.coding_service import CodingService
            CodingService.criar_agente_coding_padrao(db, db_sessao.id)
            logger.info("Agente de coding criado para sessão %s", db_sessao.nome)
        except Exception as e:
            logger.warning("Erro ao criar agente de coding: %s", e)

        return db_sessao

    @staticmethod
    def atualizar(db: Session, sessao_id: int, sessao: SessaoAtualizar) -> Optional[Sessao]:
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            return None
        for campo, valor in sessao.model_dump(exclude_unset=True).items():
            setattr(db_sessao, campo, valor)
        db.commit()
        db.refresh(db_sessao)
        return db_sessao

    @staticmethod
    def deletar(db: Session, sessao_id: int) -> bool:
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            return False
        if db_sessao.status == "conectado":
            SessaoService.desconectar(db, sessao_id)
        db.delete(db_sessao)
        db.commit()
        return True

    # ----- conexão -----

    @staticmethod
    def _criar_e_conectar(db: Session, db_sessao: Sessao, *, reconectar: bool) -> Optional[CanalClient]:
        sessao_dir = ConfiguracaoService.obter_valor(db, "sessao_diretorio", "./sessoes")
        history_sync_delay = ConfiguracaoService.obter_valor(db, "sessao_history_sync_delay", 5)
        canal = criar_canal(
            sessao=db_sessao,
            sessao_dir=sessao_dir,
            on_mensagem=_build_on_mensagem(db_sessao.id),
            on_status=_build_on_status(db_sessao.id),
            history_sync_delay=history_sync_delay,
        )
        if not canal:
            db_sessao.status = "erro"
            db.commit()
            return None

        gerenciador_sessoes.adicionar_cliente(db_sessao.id, canal)
        # WA aceita o parâmetro reconectar; TG ignora (não tem efeito).
        try:
            if db_sessao.plataforma == "whatsapp":
                canal.conectar(reconectar=reconectar)  # type: ignore[call-arg]
            else:
                canal.conectar()
        except Exception:
            logger.exception("Falha ao conectar sessão %s", db_sessao.id)
            db_sessao.status = "erro"
            db.commit()
            gerenciador_sessoes.remover_cliente(db_sessao.id)
            return None
        return canal

    @staticmethod
    def conectar(db: Session, sessao_id: int, usar_paircode: bool = False) -> SessaoStatusResposta:
        """Inicia conexão de uma sessão (WA: QR; TG: polling)."""
        logger.info("Conectando sessão %s", sessao_id)
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            raise ValueError("Sessão não encontrada")
        if not db_sessao.ativa:
            raise ValueError("Sessão está desativada")

        cliente_existente = gerenciador_sessoes.obter_cliente(sessao_id)
        if cliente_existente:
            qr = getattr(cliente_existente, "qr_code", None)
            return SessaoStatusResposta(
                id=db_sessao.id,
                nome=db_sessao.nome,
                status=db_sessao.status,
                telefone=db_sessao.telefone,
                qr_code=qr,
                mensagem="Cliente já está conectando.",
            )

        if db_sessao.status == "conectado":
            return SessaoStatusResposta(
                id=db_sessao.id,
                nome=db_sessao.nome,
                status="conectado",
                telefone=db_sessao.telefone,
                qr_code=None,
                mensagem="Sessão já está conectada",
            )

        canal = SessaoService._criar_e_conectar(db, db_sessao, reconectar=False)
        if not canal:
            raise ValueError("Falha ao criar adapter de canal")

        db_sessao.status = "iniciando"
        db.commit()

        return SessaoStatusResposta(
            id=db_sessao.id,
            nome=db_sessao.nome,
            status="iniciando",
            telefone=None,
            qr_code=None,
            mensagem=f"Iniciando conexão {db_sessao.plataforma}...",
        )

    @staticmethod
    def reconectar_sessao(db: Session, sessao_id: int):
        """Reconecta usando credenciais já armazenadas (WA: sessao_X.db; TG: bot_token)."""
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            raise ValueError("Sessão não encontrada")
        if gerenciador_sessoes.obter_cliente(sessao_id):
            logger.debug("Sessão %s já tem adapter ativo; ignorando reconexão", sessao_id)
            return
        SessaoService._criar_e_conectar(db, db_sessao, reconectar=True)

    @staticmethod
    def desconectar(db: Session, sessao_id: int) -> SessaoStatusResposta:
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            raise ValueError("Sessão não encontrada")

        canal = gerenciador_sessoes.obter_cliente(sessao_id)
        if canal:
            try:
                canal.desconectar()
            except Exception:
                logger.exception("Erro ao desconectar adapter da sessão %s", sessao_id)
        gerenciador_sessoes.remover_cliente(sessao_id)

        db_sessao.status = "desconectado"
        db_sessao.qr_code = None
        db.commit()

        return SessaoStatusResposta(
            id=db_sessao.id,
            nome=db_sessao.nome,
            status="desconectado",
            telefone=db_sessao.telefone,
            qr_code=None,
            mensagem="Sessão desconectada com sucesso",
        )

    @staticmethod
    def obter_status(db: Session, sessao_id: int) -> SessaoStatusResposta:
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            raise ValueError("Sessão não encontrada")
        canal = gerenciador_sessoes.obter_cliente(sessao_id)
        qr_code = getattr(canal, "qr_code", None) if canal else None
        return SessaoStatusResposta(
            id=db_sessao.id,
            nome=db_sessao.nome,
            status=db_sessao.status,
            telefone=db_sessao.telefone,
            qr_code=qr_code or db_sessao.qr_code,
            mensagem=f"Status: {db_sessao.status}",
        )

    # ----- envio -----

    @staticmethod
    def enviar_mensagem(
        db: Session,
        sessao_id: int,
        telefone_destino: str,
        texto: str,
        jid_server: str = None,
    ) -> bool:
        """Envia uma mensagem de texto através de uma sessão.

        `telefone_destino` aceita formato bruto (telefone p/ WA, chat_id p/ TG)
        ou "user@server" pra WA com server explícito.
        """
        db_sessao = SessaoService.obter_por_id(db, sessao_id)
        if not db_sessao:
            raise ValueError("Sessão não encontrada")
        if db_sessao.status != "conectado":
            raise ValueError("Sessão não está conectada")

        canal = gerenciador_sessoes.obter_cliente(sessao_id)
        if not canal:
            raise ValueError("Adapter de canal não encontrado")

        chat_id = telefone_destino
        if jid_server and "@" not in str(telefone_destino):
            chat_id = f"{telefone_destino}@{jid_server}"

        ok = canal.enviar_texto(chat_id, texto)
        if not ok:
            raise ValueError("Falha ao enviar mensagem")
        return True
