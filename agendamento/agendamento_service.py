"""
Serviço de tarefas agendadas.

Usa APScheduler (AsyncIOScheduler) rodando no mesmo event loop do FastAPI.
Persistência canônica no SQLite (tabela `tarefas_agendadas`) — o scheduler
mantém apenas estado em memória e é repopulado no startup a partir do DB.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from database import SessionLocal
from agendamento.agendamento_model import (
    TarefaAgendada,
    TipoAgendamento,
    AcaoAgendamento,
    StatusAgendamento,
)
from agendamento.agendamento_schema import TarefaAgendadaCriar

logger = logging.getLogger(__name__)


class AgendamentoService:
    """Gerencia o ciclo de vida das tarefas agendadas."""

    _scheduler: Optional[AsyncIOScheduler] = None

    # ────────────────────────────────────────────────────────────────
    # Ciclo de vida
    # ────────────────────────────────────────────────────────────────
    @classmethod
    def iniciar(cls) -> None:
        """Inicia o scheduler. Chamado uma vez no startup do FastAPI."""
        if cls._scheduler and cls._scheduler.running:
            logger.info("Scheduler já iniciado, ignorando")
            return

        cls._scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
        cls._scheduler.start()
        logger.info("Scheduler de agendamentos iniciado")

        cls._reagendar_pendentes()

    @classmethod
    def parar(cls) -> None:
        """Para o scheduler. Chamado no shutdown do FastAPI."""
        if cls._scheduler and cls._scheduler.running:
            cls._scheduler.shutdown(wait=False)
            logger.info("Scheduler de agendamentos parado")

    @classmethod
    def _reagendar_pendentes(cls) -> None:
        """Recarrega tarefas pendentes do DB e re-registra no scheduler."""
        db = SessionLocal()
        try:
            pendentes = db.query(TarefaAgendada).filter(
                TarefaAgendada.status == StatusAgendamento.PENDENTE
            ).all()
            reagendadas = 0
            for tarefa in pendentes:
                try:
                    cls._registrar_no_scheduler(tarefa)
                    reagendadas += 1
                except Exception as e:
                    logger.warning("Falha ao reagendar tarefa %d: %s", tarefa.id, e)
                    tarefa.status = StatusAgendamento.FALHOU
                    tarefa.erro = f"Falha ao reagendar: {e}"
            if reagendadas:
                db.commit()
                logger.info("Reagendadas %d tarefa(s) pendentes", reagendadas)
        finally:
            db.close()

    # ────────────────────────────────────────────────────────────────
    # CRUD
    # ────────────────────────────────────────────────────────────────
    @staticmethod
    def listar(
        db: Session,
        status: Optional[StatusAgendamento] = None,
        telefone: Optional[str] = None,
        sessao_id: Optional[int] = None,
    ) -> List[TarefaAgendada]:
        q = db.query(TarefaAgendada)
        if status:
            q = q.filter(TarefaAgendada.status == status)
        if telefone:
            q = q.filter(TarefaAgendada.telefone_destino == telefone)
        if sessao_id:
            q = q.filter(TarefaAgendada.sessao_id == sessao_id)
        return q.order_by(TarefaAgendada.proxima_execucao.asc().nullslast()).all()

    @staticmethod
    def obter_por_id(db: Session, tarefa_id: int) -> Optional[TarefaAgendada]:
        return db.query(TarefaAgendada).filter(TarefaAgendada.id == tarefa_id).first()

    @classmethod
    def criar(cls, db: Session, dados: TarefaAgendadaCriar) -> TarefaAgendada:
        """Cria a tarefa no DB e registra no scheduler."""
        payload_json = json.dumps(dados.payload, ensure_ascii=False) if dados.payload else None

        tarefa = TarefaAgendada(
            titulo=dados.titulo,
            descricao=dados.descricao,
            sessao_id=dados.sessao_id,
            agente_id=dados.agente_id,
            telefone_destino=dados.telefone_destino,
            tipo=dados.tipo,
            quando=dados.quando,
            acao=dados.acao,
            payload_json=payload_json,
            status=StatusAgendamento.PENDENTE,
            max_execucoes=dados.max_execucoes,
        )
        db.add(tarefa)
        db.commit()
        db.refresh(tarefa)

        try:
            cls._registrar_no_scheduler(tarefa)
            db.commit()
            db.refresh(tarefa)
        except Exception as e:
            tarefa.status = StatusAgendamento.FALHOU
            tarefa.erro = f"Falha ao registrar no scheduler: {e}"
            db.commit()
            raise

        return tarefa

    @classmethod
    def cancelar(cls, db: Session, tarefa_id: int) -> bool:
        tarefa = cls.obter_por_id(db, tarefa_id)
        if not tarefa:
            return False
        if tarefa.job_id and cls._scheduler:
            try:
                cls._scheduler.remove_job(tarefa.job_id)
            except Exception:
                pass
        tarefa.status = StatusAgendamento.CANCELADA
        db.commit()
        return True

    @classmethod
    async def disparar_agora(cls, db: Session, tarefa_id: int) -> Dict[str, Any]:
        """Força execução imediata da tarefa (útil pra teste).

        Não mexe no schedule recorrente — apenas executa a ação uma vez.
        Retorna o dict com o resultado da ação.
        """
        tarefa = cls.obter_por_id(db, tarefa_id)
        if not tarefa:
            return {"erro": "Tarefa não encontrada"}

        await cls._executar_tarefa(tarefa.id)
        # Recarrega para devolver o estado atualizado
        db.expire(tarefa)
        return {
            "executada": True,
            "status": tarefa.status.value if tarefa.status else None,
            "resultado": tarefa.resultado,
            "erro": tarefa.erro,
        }

    @classmethod
    def deletar(cls, db: Session, tarefa_id: int) -> bool:
        tarefa = cls.obter_por_id(db, tarefa_id)
        if not tarefa:
            return False
        if tarefa.job_id and cls._scheduler:
            try:
                cls._scheduler.remove_job(tarefa.job_id)
            except Exception:
                pass
        db.delete(tarefa)
        db.commit()
        return True

    # ────────────────────────────────────────────────────────────────
    # Registro no APScheduler
    # ────────────────────────────────────────────────────────────────
    @classmethod
    def _registrar_no_scheduler(cls, tarefa: TarefaAgendada) -> None:
        if not cls._scheduler:
            raise RuntimeError("Scheduler não iniciado")

        trigger = cls._construir_trigger(tarefa)
        job_id = f"tarefa_{tarefa.id}"

        # Remove job anterior se existir (idempotência)
        try:
            cls._scheduler.remove_job(job_id)
        except Exception:
            pass

        job = cls._scheduler.add_job(
            cls._executar_tarefa,
            trigger=trigger,
            args=[tarefa.id],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=300,  # 5 min de tolerância
            coalesce=True,
        )
        tarefa.job_id = job.id
        tarefa.proxima_execucao = job.next_run_time

    @staticmethod
    def _construir_trigger(tarefa: TarefaAgendada):
        if tarefa.tipo == TipoAgendamento.ONCE:
            # Aceita ISO 8601 ou "YYYY-MM-DD HH:MM:SS"
            run_date = datetime.fromisoformat(tarefa.quando.replace("Z", "+00:00"))
            return DateTrigger(run_date=run_date)

        if tarefa.tipo == TipoAgendamento.INTERVAL:
            segundos = int(tarefa.quando)
            if segundos < 10:
                raise ValueError("Intervalo mínimo é 10 segundos")
            return IntervalTrigger(seconds=segundos)

        if tarefa.tipo == TipoAgendamento.CRON:
            return CronTrigger.from_crontab(tarefa.quando)

        raise ValueError(f"Tipo de agendamento desconhecido: {tarefa.tipo}")

    # ────────────────────────────────────────────────────────────────
    # Execução
    # ────────────────────────────────────────────────────────────────
    @classmethod
    async def _executar_tarefa(cls, tarefa_id: int) -> None:
        """Callback que o APScheduler invoca. Abre sua própria sessão de DB."""
        db = SessionLocal()
        try:
            tarefa = db.query(TarefaAgendada).filter(TarefaAgendada.id == tarefa_id).first()
            if not tarefa:
                logger.warning("Tarefa %d não encontrada na execução", tarefa_id)
                return

            if tarefa.status in (StatusAgendamento.CANCELADA, StatusAgendamento.CONCLUIDA):
                return

            tarefa.status = StatusAgendamento.EXECUTANDO
            db.commit()

            logger.info("Executando tarefa agendada %d (%s)", tarefa.id, tarefa.acao.value)

            try:
                resultado = await cls._despachar_acao(db, tarefa)
                tarefa.resultado = json.dumps(resultado, ensure_ascii=False, default=str)[:5000]
                tarefa.erro = None
                tarefa.total_execucoes = (tarefa.total_execucoes or 0) + 1
                tarefa.ultima_execucao = datetime.now()

                if tarefa.tipo == TipoAgendamento.ONCE:
                    tarefa.status = StatusAgendamento.CONCLUIDA
                elif tarefa.max_execucoes and tarefa.total_execucoes >= tarefa.max_execucoes:
                    tarefa.status = StatusAgendamento.CONCLUIDA
                    if cls._scheduler and tarefa.job_id:
                        try:
                            cls._scheduler.remove_job(tarefa.job_id)
                        except Exception:
                            pass
                else:
                    tarefa.status = StatusAgendamento.PENDENTE
                    # Atualiza proxima_execucao
                    if cls._scheduler and tarefa.job_id:
                        job = cls._scheduler.get_job(tarefa.job_id)
                        if job:
                            tarefa.proxima_execucao = job.next_run_time
            except Exception as e:
                logger.exception("Erro ao executar tarefa %d", tarefa.id)
                tarefa.erro = str(e)[:2000]
                tarefa.status = StatusAgendamento.FALHOU
                tarefa.ultima_execucao = datetime.now()

            db.commit()
        finally:
            db.close()

    @classmethod
    async def _despachar_acao(cls, db: Session, tarefa: TarefaAgendada) -> Dict[str, Any]:
        payload = json.loads(tarefa.payload_json) if tarefa.payload_json else {}

        if tarefa.acao == AcaoAgendamento.ENVIAR_MENSAGEM:
            return await cls._acao_enviar_mensagem(db, tarefa, payload)
        if tarefa.acao == AcaoAgendamento.RODAR_FERRAMENTA:
            return await cls._acao_rodar_ferramenta(db, tarefa, payload)
        if tarefa.acao == AcaoAgendamento.CALLBACK_AGENTE:
            return await cls._acao_callback_agente(db, tarefa, payload)
        return {"erro": f"Ação não suportada: {tarefa.acao}"}

    # ── Handlers de ação ────────────────────────────────────────────
    @staticmethod
    async def _acao_enviar_mensagem(db: Session, tarefa: TarefaAgendada, payload: dict) -> Dict[str, Any]:
        from sessao.sessao_service import SessaoService

        if not tarefa.sessao_id or not tarefa.telefone_destino:
            return {"erro": "sessao_id e telefone_destino são obrigatórios"}
        texto = payload.get("texto")
        if not texto:
            return {"erro": "payload.texto ausente"}

        ok = SessaoService.enviar_mensagem(
            db, tarefa.sessao_id, tarefa.telefone_destino, texto
        )
        return {"enviado": ok, "telefone": tarefa.telefone_destino}

    @staticmethod
    async def _acao_rodar_ferramenta(db: Session, tarefa: TarefaAgendada, payload: dict) -> Dict[str, Any]:
        from ferramenta.ferramenta_service import FerramentaService

        nome = payload.get("nome_ferramenta")
        argumentos = payload.get("argumentos", {})
        if not nome:
            return {"erro": "payload.nome_ferramenta ausente"}

        resultado = await FerramentaService.executar_ferramenta(
            db, nome, argumentos,
            sessao_id=tarefa.sessao_id,
            telefone_cliente=tarefa.telefone_destino,
        )
        return {"ferramenta": nome, "resultado": resultado}

    @staticmethod
    async def _acao_callback_agente(db: Session, tarefa: TarefaAgendada, payload: dict) -> Dict[str, Any]:
        """
        Injeta um prompt sintético no agente como se viesse do usuário.
        O agente responde normalmente — a resposta é mandada para o telefone via WhatsApp.
        """
        from agente.agente_service import AgenteService
        from sessao.sessao_service import SessaoService, gerenciador_sessoes
        from mensagem.mensagem_service import MensagemService
        from mensagem.mensagem_model import Mensagem
        from mensagem.markdown_whatsapp import markdown_para_whatsapp
        from neonize.utils import build_jid

        if not tarefa.sessao_id or not tarefa.telefone_destino:
            return {"erro": "sessao_id e telefone_destino são obrigatórios"}

        prompt = payload.get("prompt")
        if not prompt:
            return {"erro": "payload.prompt ausente"}

        sessao = SessaoService.obter_por_id(db, tarefa.sessao_id)
        if not sessao:
            return {"erro": "Sessão não encontrada"}

        agente = None
        if tarefa.agente_id:
            from agente.agente_service import AgenteService as _A
            agente = _A.obter_por_id(db, tarefa.agente_id)

        # Mensagem sintética persistida para entrar no histórico
        mensagem = Mensagem(
            sessao_id=tarefa.sessao_id,
            telefone_cliente=tarefa.telefone_destino,
            tipo="texto",
            direcao="recebida",
            conteudo_texto=f"[agendamento] {prompt}",
            processada=False,
            respondida=False,
        )
        db.add(mensagem)
        db.commit()
        db.refresh(mensagem)

        historico = MensagemService.listar_por_cliente(
            db, tarefa.sessao_id, tarefa.telefone_destino, limite=10
        )

        telefone_limpo = str(tarefa.telefone_destino).split("@")[0].split(":")[0]
        jid_destino = build_jid(telefone_limpo)

        resposta = await AgenteService.processar_mensagem(
            db, sessao, mensagem, historico, agente=agente, jid_destino=jid_destino
        )

        # Envia resposta no WhatsApp
        enviado = False
        if resposta.get("texto"):
            cliente = gerenciador_sessoes.obter_cliente(tarefa.sessao_id)
            if cliente:
                try:
                    texto_wa = markdown_para_whatsapp(resposta["texto"])
                    cliente.send_message(jid_destino, message=texto_wa)
                    enviado = True
                    mensagem.resposta_texto = resposta["texto"]
                    mensagem.respondida = True
                    mensagem.respondido_em = datetime.now()
                except Exception as e:
                    mensagem.resposta_erro = str(e)
        mensagem.processada = True
        mensagem.processado_em = datetime.now()
        db.commit()

        return {"enviado": enviado, "resposta_preview": (resposta.get("texto") or "")[:200]}
