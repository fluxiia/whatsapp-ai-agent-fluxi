"""Cron de purga de midias expiradas.

Roda em thread daemon a cada N horas (config `sistema_midia_purga_intervalo_horas`).
Nao usa Celery — a memory `plano-celery.md` diz pra adiar essa migracao.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _loop():
    from database import SessionLocal
    from config.config_service import ConfiguracaoService
    from midia import midia_service

    while not _stop.is_set():
        db = SessionLocal()
        try:
            intervalo_h = int(ConfiguracaoService.obter_valor(db, "sistema_midia_purga_intervalo_horas", 24))
            if intervalo_h <= 0:
                # Desativado via config — checa de novo daqui 1h.
                intervalo_h = 1
                logger.debug("midia.cron.desativado")
            else:
                try:
                    n = midia_service.purgar_expiradas(db)
                    db.commit()
                    if n:
                        logger.info("midia.cron.purgou n=%d", n)
                except Exception:
                    logger.exception("midia.cron.erro_purga")
                    db.rollback()
        finally:
            db.close()

        # Sleep responsivo (acorda a cada 60s pra checar _stop sem dormir horas).
        slept = 0
        intervalo_s = max(intervalo_h * 3600, 60)
        while slept < intervalo_s and not _stop.is_set():
            time.sleep(min(60, intervalo_s - slept))
            slept += 60


def iniciar() -> None:
    """Inicia o loop em thread daemon. Idempotente."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="midia-cron", daemon=True)
    _thread.start()
    logger.info("midia.cron.iniciado")


def parar() -> None:
    """Sinaliza pro loop encerrar. Nao bloqueia esperando a thread."""
    _stop.set()
    logger.info("midia.cron.parado")
