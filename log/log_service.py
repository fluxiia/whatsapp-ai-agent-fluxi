"""
Sistema de logging estruturado do Fluxi.

Uso em qualquer módulo:
    from log.log_service import fluxi_log

    fluxi_log.info("agente", "loop", "Processamento iniciado", extra={"agente_id": 1}, session_id=5)
    fluxi_log.error("coding", "roteamento", "Falha", exc_info=True, session_id=5)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import traceback as tb_module
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from log.log_model import LogEntry
from log.log_schema import LogEntryCreate, LogFilterParams

# Diretório para arquivos de log
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════
# LogService — CRUD estático para a tabela log_entries
# ══════════════════════════════════════════════════════════════

class LogService:
    """Operações de leitura/escrita na tabela log_entries."""

    @staticmethod
    def criar(db: Session, entry: LogEntryCreate) -> LogEntry:
        """Insere uma entrada de log no banco."""
        log_entry = LogEntry(
            level=entry.level,
            module=entry.module,
            sub_module=entry.sub_module,
            message=entry.message,
            extra_json=entry.extra_json,
            traceback=entry.traceback,
            session_id=entry.session_id,
            request_id=entry.request_id,
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry

    @staticmethod
    def listar(db: Session, filtros: LogFilterParams) -> Tuple[List[LogEntry], int]:
        """Lista entradas com filtros e paginação. Retorna (entries, total)."""
        query = db.query(LogEntry)

        if filtros.module:
            query = query.filter(LogEntry.module == filtros.module)
        if filtros.sub_module:
            query = query.filter(LogEntry.sub_module == filtros.sub_module)
        if filtros.level:
            query = query.filter(LogEntry.level == filtros.level)
        if filtros.session_id:
            query = query.filter(LogEntry.session_id == filtros.session_id)
        if filtros.search:
            query = query.filter(LogEntry.message.ilike(f"%{filtros.search}%"))
        if filtros.date_from:
            try:
                dt_from = datetime.fromisoformat(filtros.date_from)
                query = query.filter(LogEntry.timestamp >= dt_from)
            except ValueError:
                pass
        if filtros.date_to:
            try:
                dt_to = datetime.fromisoformat(filtros.date_to)
                # Inclui o dia inteiro
                dt_to = dt_to.replace(hour=23, minute=59, second=59)
                query = query.filter(LogEntry.timestamp <= dt_to)
            except ValueError:
                pass

        total = query.count()
        entries = (
            query
            .order_by(desc(LogEntry.timestamp))
            .offset((filtros.page - 1) * filtros.per_page)
            .limit(filtros.per_page)
            .all()
        )
        return entries, total

    @staticmethod
    def obter_stats(db: Session) -> dict:
        """Estatísticas globais de log."""
        total = db.query(func.count(LogEntry.id)).scalar() or 0

        by_level = {}
        for level, count in db.query(LogEntry.level, func.count(LogEntry.id)).group_by(LogEntry.level).all():
            by_level[level] = count

        by_module = {}
        for module, count in db.query(LogEntry.module, func.count(LogEntry.id)).group_by(LogEntry.module).all():
            by_module[module] = count

        uma_hora_atras = datetime.now() - timedelta(hours=1)
        errors_last_hour = (
            db.query(func.count(LogEntry.id))
            .filter(LogEntry.level.in_(["ERROR", "CRITICAL"]))
            .filter(LogEntry.timestamp >= uma_hora_atras)
            .scalar() or 0
        )

        # Erros por módulo (últimas 24h) — para os badges nas abas
        vinte_quatro_h = datetime.now() - timedelta(hours=24)
        errors_by_module = {}
        for module, count in (
            db.query(LogEntry.module, func.count(LogEntry.id))
            .filter(LogEntry.level.in_(["ERROR", "CRITICAL"]))
            .filter(LogEntry.timestamp >= vinte_quatro_h)
            .group_by(LogEntry.module)
            .all()
        ):
            errors_by_module[module] = count

        return {
            "total": total,
            "by_level": by_level,
            "by_module": by_module,
            "errors_last_hour": errors_last_hour,
            "errors_by_module": errors_by_module,
        }

    @staticmethod
    def obter_stats_por_modulo(db: Session, module: str) -> dict:
        """Estatísticas de um módulo específico."""
        by_level = {}
        for level, count in (
            db.query(LogEntry.level, func.count(LogEntry.id))
            .filter(LogEntry.module == module)
            .group_by(LogEntry.level)
            .all()
        ):
            by_level[level] = count
        return {"module": module, "by_level": by_level}

    @staticmethod
    def obter_sub_modulos(db: Session, module: str) -> List[str]:
        """Retorna sub-módulos distintos de um módulo."""
        rows = (
            db.query(LogEntry.sub_module)
            .filter(LogEntry.module == module)
            .filter(LogEntry.sub_module.isnot(None))
            .distinct()
            .all()
        )
        return [r[0] for r in rows if r[0]]

    @staticmethod
    def limpar_antigos(db: Session, dias: int = 30) -> int:
        """Remove entradas mais antigas que N dias. Retorna quantidade removida."""
        limite = datetime.now() - timedelta(days=dias)
        count = db.query(LogEntry).filter(LogEntry.timestamp < limite).delete()
        db.commit()
        return count


# ══════════════════════════════════════════════════════════════
# FluxiLogger — API pública (singleton)
# ══════════════════════════════════════════════════════════════

class FluxiLogger:
    """
    Logger estruturado que escreve simultaneamente em:
    - Arquivo rotativo: logs/{module}.log
    - Banco de dados: tabela log_entries

    Thread-safe. Nunca lança exceção — falhas de escrita são silenciosas.
    """

    _instance: Optional[FluxiLogger] = None
    _lock = threading.Lock()

    def __new__(cls) -> FluxiLogger:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._file_loggers: Dict[str, logging.Logger] = {}
        self._file_lock = threading.Lock()

    def _get_file_logger(self, module: str) -> logging.Logger:
        """Obtém ou cria um logger de arquivo para o módulo."""
        if module in self._file_loggers:
            return self._file_loggers[module]

        with self._file_lock:
            # Double-check
            if module in self._file_loggers:
                return self._file_loggers[module]

            logger = logging.getLogger(f"fluxi.{module}")
            logger.setLevel(logging.DEBUG)
            logger.propagate = False  # Não interfere com logging_config.py

            # Remove handlers existentes (caso de reload)
            for h in logger.handlers[:]:
                logger.removeHandler(h)

            handler = RotatingFileHandler(
                os.path.join(LOGS_DIR, f"{module}.log"),
                maxBytes=5 * 1024 * 1024,  # 5MB
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            logger.addHandler(handler)

            self._file_loggers[module] = logger
            return logger

    def _write(
        self,
        level: str,
        module: str,
        sub_module: Optional[str],
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: bool = False,
        session_id: Optional[int] = None,
        request_id: Optional[str] = None,
    ):
        """Escrita dual: arquivo + banco."""
        # ── Traceback (se solicitado) ──
        traceback_str = None
        if exc_info:
            traceback_str = tb_module.format_exc()
            if traceback_str == "NoneType: None\n":
                traceback_str = None

        # ── Extra JSON ──
        extra_str = None
        if extra:
            try:
                extra_str = json.dumps(extra, ensure_ascii=False, default=str)
            except Exception:
                extra_str = str(extra)

        # ── Arquivo rotativo ──
        try:
            file_logger = self._get_file_logger(module)
            sub_tag = f".{sub_module}" if sub_module else ""
            file_msg = f"[{module}{sub_tag}] {message}"
            if extra:
                file_msg += f" | {extra_str}"
            if traceback_str:
                file_msg += f"\n{traceback_str}"

            log_level = getattr(logging, level, logging.INFO)
            file_logger.log(log_level, file_msg)
        except Exception:
            pass  # Logger nunca crasha o app

        # ── Banco de dados ──
        try:
            from database import SessionLocal
            db = SessionLocal()
            try:
                entry = LogEntry(
                    level=level,
                    module=module,
                    sub_module=sub_module,
                    message=message,
                    extra_json=extra_str,
                    traceback=traceback_str,
                    session_id=session_id,
                    request_id=request_id,
                )
                db.add(entry)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass  # Logger nunca crasha o app

        # ── Console (mantém visibilidade no Docker) ──
        try:
            sub_tag = f".{sub_module}" if sub_module else ""
            icon = {"DEBUG": "🔍", "INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "CRITICAL": "🔥"}.get(level, "📝")
            print(f"{icon} [{level}] {module}{sub_tag}: {message}")
        except Exception:
            pass

    # ── Métodos públicos ─────────────────────────────────────

    def debug(self, module: str, sub_module: Optional[str], message: str, **kwargs):
        self._write("DEBUG", module, sub_module, message, **kwargs)

    def info(self, module: str, sub_module: Optional[str], message: str, **kwargs):
        self._write("INFO", module, sub_module, message, **kwargs)

    def warning(self, module: str, sub_module: Optional[str], message: str, **kwargs):
        self._write("WARNING", module, sub_module, message, **kwargs)

    def error(self, module: str, sub_module: Optional[str], message: str, **kwargs):
        self._write("ERROR", module, sub_module, message, **kwargs)

    def critical(self, module: str, sub_module: Optional[str], message: str, **kwargs):
        self._write("CRITICAL", module, sub_module, message, **kwargs)


# ── Singleton exportado ──────────────────────────────────────
fluxi_log = FluxiLogger()
