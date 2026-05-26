"""
Testes funcionais para LogService.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from log.log_service import LogService
from log.log_schema import LogEntryCreate, LogFilterParams
from log.log_model import LogEntry


@pytest.fixture(autouse=True)
def _limpar_log_entries(db):
    """O fluxi_log (singleton) escreve em SessionLocal próprio, contornando o
    rollback da fixture `db`. Isso polui a tabela log_entries com entradas de
    outras suítes. Limpamos via engine direto antes de cada teste.
    """
    import database
    from sqlalchemy import text
    with database.engine.connect() as conn:
        conn.execute(text("DELETE FROM log_entries"))
        conn.commit()


def _criar(db, **kw):
    defaults = dict(level="INFO", module="agente", sub_module=None,
                    message="msg", extra_json=None, traceback=None,
                    session_id=None, request_id=None)
    defaults.update(kw)
    return LogService.criar(db, LogEntryCreate(**defaults))


class TestCriar:
    def test_criar_basico(self, db):
        e = _criar(db, message="primeiro")
        assert e.id is not None
        assert e.message == "primeiro"
        assert e.level == "INFO"

    def test_criar_com_extra(self, db):
        e = _criar(db, extra_json='{"x": 1}', sub_module="loop")
        assert e.extra_json == '{"x": 1}'
        assert e.sub_module == "loop"


class TestListar:
    def test_listar_vazio(self, db):
        entries, total = LogService.listar(db, LogFilterParams())
        assert entries == []
        assert total == 0

    def test_listar_basico(self, db):
        for i in range(5):
            _criar(db, message=f"m{i}")
        entries, total = LogService.listar(db, LogFilterParams())
        assert total == 5
        # ordem decrescente: m4 deve ser o primeiro (mais recente)
        msgs = [e.message for e in entries]
        assert "m0" in msgs and "m4" in msgs

    def test_filtro_module(self, db):
        _criar(db, module="agente", message="agt")
        _criar(db, module="rag", message="rag")
        entries, total = LogService.listar(db, LogFilterParams(module="rag"))
        assert total == 1
        assert entries[0].module == "rag"

    def test_filtro_level(self, db):
        _criar(db, level="ERROR")
        _criar(db, level="INFO")
        entries, total = LogService.listar(db, LogFilterParams(level="ERROR"))
        assert total == 1

    def test_filtro_search(self, db):
        _criar(db, message="busca importante")
        _criar(db, message="outra coisa")
        entries, total = LogService.listar(db, LogFilterParams(search="importante"))
        assert total == 1

    def test_filtro_session_id(self, db):
        _criar(db, session_id=5)
        _criar(db, session_id=10)
        entries, total = LogService.listar(db, LogFilterParams(session_id=5))
        assert total == 1
        assert entries[0].session_id == 5

    def test_paginacao(self, db):
        for i in range(15):
            _criar(db, message=f"m{i}")
        entries, total = LogService.listar(
            db, LogFilterParams(page=2, per_page=5)
        )
        assert total == 15
        assert len(entries) == 5

    def test_filtro_data(self, db):
        e1 = _criar(db, message="recente")
        e2 = _criar(db, message="antiga")
        e2.timestamp = datetime.now() - timedelta(days=10)
        db.commit()

        # filtra a partir de "hoje"
        hoje = datetime.now().strftime("%Y-%m-%d")
        entries, total = LogService.listar(
            db, LogFilterParams(date_from=hoje)
        )
        assert total == 1
        assert entries[0].message == "recente"


class TestStats:
    def test_stats_vazio(self, db):
        stats = LogService.obter_stats(db)
        assert stats["total"] == 0
        assert stats["by_level"] == {}

    def test_stats_com_dados(self, db):
        _criar(db, level="INFO", module="agente")
        _criar(db, level="INFO", module="rag")
        _criar(db, level="ERROR", module="agente")
        stats = LogService.obter_stats(db)
        assert stats["total"] == 3
        assert stats["by_level"]["INFO"] == 2
        assert stats["by_level"]["ERROR"] == 1
        assert stats["by_module"]["agente"] == 2

    def test_errors_last_hour(self, db):
        _criar(db, level="ERROR")
        stats = LogService.obter_stats(db)
        assert stats["errors_last_hour"] == 1

    def test_stats_por_modulo(self, db):
        _criar(db, module="rag", level="INFO")
        _criar(db, module="rag", level="ERROR")
        _criar(db, module="agente")
        r = LogService.obter_stats_por_modulo(db, "rag")
        assert r["module"] == "rag"
        assert r["by_level"]["INFO"] == 1
        assert r["by_level"]["ERROR"] == 1

    def test_obter_sub_modulos(self, db):
        _criar(db, module="agente", sub_module="loop")
        _criar(db, module="agente", sub_module="ferramenta")
        _criar(db, module="agente", sub_module=None)
        subs = LogService.obter_sub_modulos(db, "agente")
        assert "loop" in subs
        assert "ferramenta" in subs


class TestLimpar:
    def test_limpar_antigos(self, db):
        e_nova = _criar(db, message="recente")
        e_antiga = _criar(db, message="antiga")
        e_antiga.timestamp = datetime.now() - timedelta(days=40)
        db.commit()

        n = LogService.limpar_antigos(db, dias=30)
        assert n == 1
        entries, total = LogService.listar(db, LogFilterParams())
        assert total == 1
        assert entries[0].message == "recente"


class TestFluxiLogger:
    """Smoke tests do logger singleton — não verifica banco
    (logger usa SessionLocal próprio, fora da fixture de teste)."""

    def test_singleton(self):
        from log.log_service import FluxiLogger, fluxi_log
        assert fluxi_log is FluxiLogger()

    def test_info_nao_lanca(self):
        from log.log_service import fluxi_log
        # não deve levantar exceção
        fluxi_log.info("sistema", None, "smoke test", extra={"k": "v"})

    def test_error_nao_lanca(self):
        from log.log_service import fluxi_log
        try:
            raise RuntimeError("forçado")
        except RuntimeError:
            fluxi_log.error("sistema", None, "erro smoke", exc_info=True)
