"""Service de audit (`agent_failures`).

API publica:
- `registrar_falha(...)` — grava linha. Chamado pelo supervisor do
  pipeline (MensagemFallbackService) e pelo watchdog de orphan.
- `listar_recentes(...)` — query pro painel admin.
- `marcar_resolvido(...)` — admin inspecionou.
- `contar_por_tipo_periodo(...)` — metricas (eficacia do watchdog).

Regra de ouro: registrar falha NUNCA pode falhar de forma que derrube o
supervisor. Toda excecao aqui dentro eh engolida com log de warning.
"""
from __future__ import annotations

import logging
import traceback as _tb
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from audit.audit_model import AgentFailure, TipoFalha
from exceptions import FluxiError
from log.log_service import fluxi_log

# logger fica pra DEBUG; fluxi_log pra eventos operacionais persistidos.
logger = logging.getLogger(__name__)


def _categorizar(exc: BaseException) -> TipoFalha:
    """Inferir TipoFalha a partir da exception.

    Estrategia: FluxiError ja sabe sua categoria via classe; fallback usa
    heuristica por nome da classe.
    """
    from exceptions import (
        CanalError,
        IntegrationError,
        LLMError,
        ToolError,
    )

    if isinstance(exc, LLMError):
        return TipoFalha.llm
    if isinstance(exc, CanalError):
        return TipoFalha.canal
    if isinstance(exc, ToolError):
        return TipoFalha.tool
    if isinstance(exc, IntegrationError):
        return TipoFalha.llm  # IntegrationError "solto" no Fluxi quase sempre eh LLM
    if isinstance(exc, FluxiError):
        return TipoFalha.pipeline

    # Heuristica por nome — fallback pra excecoes nao-Fluxi.
    name = type(exc).__name__.lower()
    if any(k in name for k in ("timeout", "connection", "http", "openai", "anthropic")):
        return TipoFalha.llm
    return TipoFalha.outros


def registrar_falha(
    db: Session,
    *,
    sessao_id: int,
    exc: BaseException,
    chat_id: Optional[str] = None,
    mensagem_id: Optional[int] = None,
    agente_id: Optional[int] = None,
    tipo: Optional[TipoFalha] = None,
    tentativas: int = 1,
    contexto_extra: Optional[dict] = None,
) -> Optional[AgentFailure]:
    """Grava AgentFailure. Retorna a instancia ou None se gravacao falhar.

    NUNCA propaga excecao — eh chamado de dentro de supervisor que ja esta
    tratando outro erro; um erro aqui nao pode mascarar o original.
    """
    # Guarda defensiva: chamadores errados nao devem poluir log com traceback.
    if not isinstance(exc, BaseException):
        fluxi_log.warning(
            "audit", "registrar", "Input inválido (não é exception)",
            extra={"tipo_recebido": type(exc).__name__}, session_id=sessao_id,
        )
        return None

    try:
        tipo_final = tipo or _categorizar(exc)
        exception_code: Optional[str] = None
        payload: dict[str, Any] = {}

        if isinstance(exc, FluxiError):
            exception_code = exc.code
            payload.update(exc.to_dict())

        if contexto_extra:
            payload["contexto"] = contexto_extra

        # Traceback so pra imprevistos (FluxiError recuperavel nao precisa).
        tb_str: Optional[str] = None
        if not isinstance(exc, FluxiError) or not exc.is_recoverable:
            tb_str = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))

        failure = AgentFailure(
            sessao_id=sessao_id,
            chat_id=chat_id,
            mensagem_id=mensagem_id,
            agente_id=agente_id,
            tipo=tipo_final,
            exception_class=type(exc).__name__,
            exception_code=exception_code,
            mensagem_erro=str(exc)[:5000],  # limite defensivo
            traceback=tb_str,
            payload=payload or None,
            tentativas=tentativas,
        )
        db.add(failure)
        db.flush()
        fluxi_log.info(
            "audit", "registrar", "Falha registrada em agent_failures",
            extra={
                "failure_id": failure.id,
                "tipo": tipo_final.value,
                "exception_class": type(exc).__name__,
                "exception_code": exception_code,
                "tentativas": tentativas,
            },
            session_id=sessao_id,
        )
        return failure
    except Exception:
        # Audit falhando nao pode derrubar supervisor. So loga e segue.
        fluxi_log.error(
            "audit", "registrar", "Gravação em agent_failures falhou",
            exc_info=True, session_id=sessao_id,
        )
        return None


def listar_recentes(
    db: Session,
    *,
    sessao_id: Optional[int] = None,
    tipo: Optional[TipoFalha] = None,
    nao_resolvidos: bool = False,
    limit: int = 100,
) -> list[AgentFailure]:
    """Query pro painel admin."""
    q = db.query(AgentFailure).order_by(AgentFailure.criado_em.desc())
    if sessao_id is not None:
        q = q.filter(AgentFailure.sessao_id == sessao_id)
    if tipo is not None:
        q = q.filter(AgentFailure.tipo == tipo)
    if nao_resolvidos:
        q = q.filter(AgentFailure.resolvido_em.is_(None))
    return q.limit(limit).all()


def marcar_resolvido(
    db: Session,
    failure_id: int,
    *,
    resolvido_por: str,
    nota: Optional[str] = None,
) -> bool:
    """Admin marca falha como inspecionada. Retorna False se ja resolvida."""
    failure = db.query(AgentFailure).filter(AgentFailure.id == failure_id).first()
    if failure is None or failure.resolvido_em is not None:
        return False
    failure.resolvido_em = datetime.now(tz=timezone.utc)
    failure.resolvido_por = resolvido_por
    failure.resolucao_nota = nota
    db.flush()
    fluxi_log.info(
        "audit", "resolver", "Falha marcada como resolvida",
        extra={"failure_id": failure_id, "resolvido_por": resolvido_por},
        session_id=failure.sessao_id,
    )
    return True


def contar_por_tipo_periodo(
    db: Session,
    *,
    desde: datetime,
    sessao_id: Optional[int] = None,
) -> dict[str, int]:
    """Agregacao por TipoFalha pra metrica de eficacia (skill resiliencia
    diz: watchdog precisa termometro).

    Retorna {"llm": 12, "tool": 3, ...}.
    """
    from sqlalchemy import func as sa_func

    q = db.query(AgentFailure.tipo, sa_func.count(AgentFailure.id)).filter(
        AgentFailure.criado_em >= desde
    )
    if sessao_id is not None:
        q = q.filter(AgentFailure.sessao_id == sessao_id)
    rows = q.group_by(AgentFailure.tipo).all()
    return {tipo.value: count for tipo, count in rows}


def contar_orphan(
    db: Session,
    *,
    desde: datetime,
    sessao_id: Optional[int] = None,
) -> int:
    """Quantas mensagens ainda nao foram respondidas/processadas no periodo.

    Usado pelo watchdog (proxima task) pra detectar travamentos silenciosos.
    Mora aqui porque eh metrica de eficacia da camada de fallback.
    """
    from mensagem.mensagem_model import Mensagem

    q = db.query(Mensagem).filter(
        Mensagem.criado_em >= desde,
        Mensagem.direcao == "recebida",
        Mensagem.processada.is_(False),
    )
    if sessao_id is not None:
        q = q.filter(Mensagem.sessao_id == sessao_id)
    return q.count()
