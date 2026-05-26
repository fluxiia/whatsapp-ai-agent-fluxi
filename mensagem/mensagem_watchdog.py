"""Watchdog de mensagens orfas no pipeline.

Detecta `Mensagem(processada=False)` mais velha que `sistema_orphan_minutos`
e aciona MensagemFallbackService — cobre o caso onde o pipeline travou
SILENCIOSAMENTE (sem excecao chegar ao supervisor): crash do agente_service,
deadlock, network freeze, OOM seguido de restart.

Sem essa camada, o supervisor explicito so cobre falhas que sobem o stack.
Travamentos silenciosos passariam batido — usuario sem resposta pra sempre.

Aplicacao da skill `resiliencia-erros`:
- Regra 2 (supervisor) — este modulo eh um supervisor de "ultima instancia"
  pra mensagens orfas; complementa o supervisor sincrono do pipeline.
- Regra 8 (constantes operacionais com proveniencia):
  - intervalo 60s — granularidade do tick; menor = mais carga, maior =
    mais demora na deteccao. Default conservador.
  - limite 50 orphans/execucao — defesa contra storm (ex: queda de
    1h gera 100s de mensagens; processar todas de uma vez floods o canal).
- Regra 9 (termometro) — `obter_metricas()` expoe contadores cumulativos
  pro proximo passo (health/metrics endpoint).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from exceptions import FluxiError
from log.log_service import fluxi_log

# logger fica pra DEBUG baixo nivel; fluxi_log pra eventos persistidos.
logger = logging.getLogger(__name__)


class PipelineTimeoutError(FluxiError):
    """Excecao sintetica que o watchdog 'cria' pra acionar o fallback.

    Eh imprevisto (nao recuperavel): se o pipeline travou silenciosamente,
    nao tem retry — o turno acabou. Vai pra audit com tb=None porque nao
    ha tb real (travamento, nao exception).
    """

    code = "pipeline.timeout"
    is_recoverable = False


# ─── Metricas in-memory (termometro do watchdog) ─────────────────────────
# Reset no restart — aceitavel; pra metricas persistentes use tabela
# separada. Pra "esta funcionando?" e suficiente.
_metricas: dict = {
    "execucoes": 0,
    "orphans_detectados_total": 0,
    "fallbacks_enviados_total": 0,
    "fallbacks_falharam_total": 0,
    "erros_execucao": 0,
    "ultima_execucao_iso": None,
    "ultima_deteccao_iso": None,
}


def obter_metricas() -> dict:
    """Snapshot dos contadores. Usado por /health e diagnostico."""
    return dict(_metricas)


# ─── Estado de thread ────────────────────────────────────────────────────
_thread: Optional[threading.Thread] = None
_stop = threading.Event()

# Proveniencia: tick de 60s — checa orphans com granularidade adequada.
# Trade-off: orphan_minutos=5 + tick=60s -> pode demorar ate 6min entre
# travamento e fallback. Aceitavel; abaixo seria carga desnecessaria.
_TICK_SEGUNDOS = 60

# Proveniencia: limite por execucao — defesa contra storm. Se 100 mensagens
# ficarem orfas (queda de 1h), o canal ficaria flooded. 50 por tick limita
# a 50/min, ritmo seguro pra qualquer canal.
_LIMITE_POR_EXECUCAO = 50


def executar_uma_vez() -> dict:
    """Uma passada do watchdog. Retorna stats. NUNCA propaga excecao.

    Exposto separado pra teste unitario direto (sem precisar do loop).
    """
    from config.config_service import ConfiguracaoService
    from database import SessionLocal
    from mensagem import mensagem_fallback_service
    from mensagem.mensagem_model import Mensagem

    stats = {"detectados": 0, "enviados": 0, "falhas": 0, "skipped": False}
    db = SessionLocal()
    try:
        minutos = int(ConfiguracaoService.obter_valor(db, "sistema_orphan_minutos", 5))
        if minutos <= 0:
            logger.debug("mensagem.watchdog.desativado")
            stats["skipped"] = True
            return stats

        corte = datetime.now(tz=timezone.utc) - timedelta(minutes=minutos)
        orphans = (
            db.query(Mensagem)
            .filter(
                Mensagem.direcao == "recebida",
                Mensagem.processada.is_(False),
                Mensagem.criado_em < corte,
            )
            .limit(_LIMITE_POR_EXECUCAO)
            .all()
        )

        stats["detectados"] = len(orphans)
        if not orphans:
            return stats

        fluxi_log.warning(
            "mensagem", "watchdog", "Mensagens órfãs detectadas — acionando fallback",
            extra={"n": len(orphans), "minutos_corte": minutos},
        )

        async def _processar_lote():
            # Um event loop pra todas as orphans desse tick (skill regra 7:
            # NAO criar event loop por mensagem).
            for m in orphans:
                exc = PipelineTimeoutError(
                    f"Mensagem nao processada apos {minutos} minutos",
                    meta={
                        "mensagem_id": m.id,
                        "criado_em": m.criado_em.isoformat() if m.criado_em else None,
                        "minutos_atraso": minutos,
                    },
                )
                ok = await mensagem_fallback_service.acionar(
                    db,
                    sessao_id=m.sessao_id,
                    chat_id=m.chat_id or m.telefone_cliente or "",
                    exc=exc,
                    mensagem_db=m,
                    contexto_extra={"origem": "watchdog"},
                )
                if ok:
                    stats["enviados"] += 1
                else:
                    stats["falhas"] += 1

        asyncio.run(_processar_lote())
        return stats
    except Exception:
        fluxi_log.error("mensagem", "watchdog", "Execução falhou", exc_info=True)
        return stats
    finally:
        db.close()


def _loop():
    while not _stop.is_set():
        try:
            stats = executar_uma_vez()
            _metricas["execucoes"] += 1
            _metricas["ultima_execucao_iso"] = datetime.now(tz=timezone.utc).isoformat()
            _metricas["orphans_detectados_total"] += stats.get("detectados", 0)
            _metricas["fallbacks_enviados_total"] += stats.get("enviados", 0)
            _metricas["fallbacks_falharam_total"] += stats.get("falhas", 0)
            if stats.get("detectados", 0) > 0:
                _metricas["ultima_deteccao_iso"] = _metricas["ultima_execucao_iso"]
                fluxi_log.warning(
                    "mensagem", "watchdog", "Tick recuperou mensagens órfãs",
                    extra={
                        "detectados": stats["detectados"],
                        "enviados": stats["enviados"],
                        "falhas": stats["falhas"],
                    },
                )
        except Exception:
            # Skill regra 2: supervisor pode capturar Exception generica aqui
            # — eh O PONTO. Sem isto o loop morre e o watchdog vira inutil.
            _metricas["erros_execucao"] += 1
            fluxi_log.error("mensagem", "watchdog", "Loop teve erro inesperado", exc_info=True)

        slept = 0
        while slept < _TICK_SEGUNDOS and not _stop.is_set():
            time.sleep(min(10, _TICK_SEGUNDOS - slept))
            slept += 10


def iniciar() -> None:
    """Inicia o loop em thread daemon. Idempotente."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="mensagem-watchdog", daemon=True)
    _thread.start()
    fluxi_log.info("mensagem", "watchdog", "Iniciado", extra={"tick_segundos": _TICK_SEGUNDOS, "limite_por_execucao": _LIMITE_POR_EXECUCAO})


def parar() -> None:
    _stop.set()
    fluxi_log.info("mensagem", "watchdog", "Parado")
