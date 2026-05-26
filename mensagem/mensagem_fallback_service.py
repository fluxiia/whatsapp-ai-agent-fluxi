"""Supervisor explicito do pipeline de mensagens.

Aplica skill `resiliencia-erros`: UNICO try/except generico do pipeline
mora aqui. Tudo que escapar do tratamento interno (excecoes recuperaveis
ja tratadas em camadas mais baixas) chega aqui como IMPREVISTO.

Garantias:
1. Audit imutavel em `agent_failures` — diagnostico nao se perde.
2. Mensagem explicativa ao usuario via canal — "IA muda" nunca acontece.
3. Mensagem marcada como processada — pipeline nao reentrega zumbi.
4. Esta funcao NUNCA propaga — eh o terminus. Falhas internas dela viram
   log de warning e seguem.

Mensagem de fallback eh CONFIG (`sistema_fallback_mensagem`), nao string
hardcoded — editavel sem deploy (skill `resiliencia-erros` regra 6).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from log.log_service import fluxi_log

# logger fica pra DEBUG baixo nivel; fluxi_log pra eventos persistidos.
logger = logging.getLogger(__name__)


# Mensagem ultima-instancia: usada SE config nao puder ser lida.
# NAO eh "a mensagem oficial" — eh o seguro caso o DB esteja inacessivel.
_FALLBACK_HARDCODED = (
    "Desculpe, tive um problema técnico ao processar sua mensagem. "
    "Já registrei o ocorrido. Pode tentar novamente?"
)


def _obter_config_fallback(db: Session) -> tuple[bool, str]:
    """Le config; cai pra default seguro se DB falhar."""
    try:
        from config.config_service import ConfiguracaoService

        ativo = ConfiguracaoService.obter_valor(db, "sistema_fallback_ativo", True)
        msg = ConfiguracaoService.obter_valor(
            db, "sistema_fallback_mensagem", _FALLBACK_HARDCODED
        )
        return bool(ativo), msg or _FALLBACK_HARDCODED
    except Exception:
        fluxi_log.error("mensagem", "fallback", "Falha ao ler config — usando hardcoded", exc_info=True)
        return True, _FALLBACK_HARDCODED


def _enviar_via_canal(sessao_id: int, chat_id: str, texto: str) -> bool:
    """Envia texto pelo canal ativo da sessao. False se nao deu."""
    try:
        from sessao.sessao_service import gerenciador_sessoes

        cliente = gerenciador_sessoes.obter_cliente(sessao_id)
        if cliente is None:
            fluxi_log.warning("mensagem", "fallback", "Canal indisponível — fallback não enviado", session_id=sessao_id)
            return False
        # Interface unificada CanalClient.enviar_texto — funciona pra
        # WA (neonize) e TG. Ambos adapters convertem chat_id internamente.
        if hasattr(cliente, "enviar_texto"):
            return bool(cliente.enviar_texto(chat_id, texto))
        # Shim de compat caso adapter antigo so tenha send_message.
        if hasattr(cliente, "send_message"):
            from neonize.utils import build_jid

            limpo = str(chat_id).split("@")[0].split(":")[0]
            cliente.send_message(build_jid(limpo), message=texto)
            return True
        fluxi_log.warning("mensagem", "fallback", "Canal sem método de envio", session_id=sessao_id)
        return False
    except Exception:
        fluxi_log.error(
            "mensagem", "fallback", "Envio de fallback falhou",
            extra={"chat_id": chat_id}, exc_info=True, session_id=sessao_id,
        )
        return False


def _marcar_mensagem(db: Session, mensagem_db, exc: BaseException, enviou: bool) -> None:
    """Atualiza Mensagem com estado de erro. Engole excecao — supervisor manda."""
    if mensagem_db is None:
        return
    try:
        agora = datetime.now(tz=timezone.utc)
        mensagem_db.processada = True
        mensagem_db.processado_em = agora
        mensagem_db.respondida = enviou
        if enviou:
            mensagem_db.respondido_em = agora
        # Truncar pra nao explodir coluna Text (defensivo).
        mensagem_db.resposta_erro = f"{type(exc).__name__}: {str(exc)[:2000]}"
        db.commit()
    except Exception:
        fluxi_log.error(
            "mensagem", "fallback", "Falha ao marcar Mensagem",
            extra={"mensagem_id": getattr(mensagem_db, "id", None)},
            exc_info=True, session_id=getattr(mensagem_db, "sessao_id", None),
        )
        try:
            db.rollback()
        except Exception:
            pass


async def acionar(
    db: Session,
    *,
    sessao_id: int,
    chat_id: str,
    exc: BaseException,
    mensagem_db=None,
    agente_id: Optional[int] = None,
    tentativas: int = 1,
    contexto_extra: Optional[dict] = None,
) -> bool:
    """Aciona o fallback completo.

    Retorna True se conseguiu entregar mensagem ao usuario; False caso
    contrario (mas auditou). NUNCA levanta excecao.
    """
    # 1) Audit — fonte de verdade pro diagnostico
    try:
        from audit import audit_service

        audit_service.registrar_falha(
            db,
            sessao_id=sessao_id,
            exc=exc,
            chat_id=chat_id,
            mensagem_id=getattr(mensagem_db, "id", None) if mensagem_db else None,
            agente_id=agente_id,
            tentativas=tentativas,
            contexto_extra=contexto_extra,
        )
        db.commit()
    except Exception:
        fluxi_log.error("mensagem", "fallback", "Audit falhou", exc_info=True, session_id=sessao_id)
        try:
            db.rollback()
        except Exception:
            pass

    # 2) Config
    ativo, texto_fallback = _obter_config_fallback(db)
    if not ativo:
        fluxi_log.info("mensagem", "fallback", "Desativado via config — não enviando", session_id=sessao_id)
        _marcar_mensagem(db, mensagem_db, exc, enviou=False)
        return False

    # 3) Envio
    enviou = _enviar_via_canal(sessao_id, chat_id, texto_fallback)
    fluxi_log.warning(
        "mensagem", "fallback", "Fallback acionado",
        extra={
            "chat_id": chat_id,
            "exception_class": type(exc).__name__,
            "exception_code": getattr(exc, "code", None),
            "enviou": enviou,
            "tentativas": tentativas,
        },
        session_id=sessao_id,
    )

    # 4) Atualizar registro da mensagem
    _marcar_mensagem(db, mensagem_db, exc, enviou=enviou)
    return enviou
