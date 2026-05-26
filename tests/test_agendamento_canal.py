"""
Testes funcionais para AgendamentoService, canal_credenciais e canal_factory.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import pytest

from agendamento.agendamento_service import AgendamentoService
from agendamento.agendamento_model import (
    TarefaAgendada, TipoAgendamento, AcaoAgendamento, StatusAgendamento
)
from agendamento.agendamento_schema import TarefaAgendadaCriar


@pytest.fixture(autouse=True)
def _stub_scheduler(monkeypatch):
    """Evita iniciar o AsyncIOScheduler (precisa de event loop) — mocka registro/remoção."""
    monkeypatch.setattr(AgendamentoService, "_registrar_no_scheduler",
                        classmethod(lambda cls, tarefa: None))
    # Garante que _scheduler atributos não disparem remove_job
    AgendamentoService._scheduler = None


# ═══════════════════════════════════════════════════════════════════════════
# Trigger construction
# ═══════════════════════════════════════════════════════════════════════════

class TestTrigger:
    def test_trigger_once(self):
        tarefa = TarefaAgendada(
            tipo=TipoAgendamento.ONCE,
            quando=(datetime.now() + timedelta(hours=1)).isoformat(),
            acao=AcaoAgendamento.ENVIAR_MENSAGEM,
            titulo="x",
        )
        trigger = AgendamentoService._construir_trigger(tarefa)
        # DateTrigger tem atributo run_date
        assert hasattr(trigger, "run_date")

    def test_trigger_interval(self):
        tarefa = TarefaAgendada(
            tipo=TipoAgendamento.INTERVAL,
            quando="60",
            acao=AcaoAgendamento.ENVIAR_MENSAGEM,
            titulo="x",
        )
        trigger = AgendamentoService._construir_trigger(tarefa)
        assert trigger is not None

    def test_trigger_interval_muito_curto(self):
        tarefa = TarefaAgendada(
            tipo=TipoAgendamento.INTERVAL,
            quando="5",
            acao=AcaoAgendamento.ENVIAR_MENSAGEM,
            titulo="x",
        )
        with pytest.raises(ValueError):
            AgendamentoService._construir_trigger(tarefa)

    def test_trigger_cron(self):
        tarefa = TarefaAgendada(
            tipo=TipoAgendamento.CRON,
            quando="0 9 * * *",
            acao=AcaoAgendamento.ENVIAR_MENSAGEM,
            titulo="x",
        )
        trigger = AgendamentoService._construir_trigger(tarefa)
        assert trigger is not None


# ═══════════════════════════════════════════════════════════════════════════
# CRUD básico
# ═══════════════════════════════════════════════════════════════════════════

class TestCrud:
    def test_listar_vazio(self, db):
        assert AgendamentoService.listar(db) == []

    def test_criar_e_listar(self, db):
        when = (datetime.now() + timedelta(hours=1)).isoformat()
        t = AgendamentoService.criar(db, TarefaAgendadaCriar(
            titulo="Test",
            tipo=TipoAgendamento.ONCE,
            quando=when,
            acao=AcaoAgendamento.ENVIAR_MENSAGEM,
            payload={"texto": "oi"},
            telefone_destino="123",
        ))
        assert t.id is not None
        assert t.titulo == "Test"
        assert t.payload_json is not None
        assert json.loads(t.payload_json) == {"texto": "oi"}

        # listar deve incluí-la
        todas = AgendamentoService.listar(db)
        assert any(x.id == t.id for x in todas)

    def test_obter_por_id(self, db):
        when = (datetime.now() + timedelta(hours=1)).isoformat()
        t = AgendamentoService.criar(db, TarefaAgendadaCriar(
            titulo="x", tipo=TipoAgendamento.ONCE, quando=when,
            acao=AcaoAgendamento.ENVIAR_MENSAGEM, payload={"texto": "a"},
            telefone_destino="9",
        ))
        assert AgendamentoService.obter_por_id(db, t.id).id == t.id
        assert AgendamentoService.obter_por_id(db, 99999) is None

    def test_cancelar(self, db):
        when = (datetime.now() + timedelta(hours=1)).isoformat()
        t = AgendamentoService.criar(db, TarefaAgendadaCriar(
            titulo="cancelar", tipo=TipoAgendamento.ONCE, quando=when,
            acao=AcaoAgendamento.ENVIAR_MENSAGEM, payload={"texto": "x"},
            telefone_destino="9",
        ))
        assert AgendamentoService.cancelar(db, t.id) is True
        db.refresh(t)
        assert t.status == StatusAgendamento.CANCELADA

    def test_cancelar_inexistente(self, db):
        assert AgendamentoService.cancelar(db, 999) is False

    def test_deletar(self, db):
        when = (datetime.now() + timedelta(hours=1)).isoformat()
        t = AgendamentoService.criar(db, TarefaAgendadaCriar(
            titulo="del", tipo=TipoAgendamento.ONCE, quando=when,
            acao=AcaoAgendamento.ENVIAR_MENSAGEM, payload={"texto": "x"},
            telefone_destino="9",
        ))
        tid = t.id
        assert AgendamentoService.deletar(db, tid) is True
        assert AgendamentoService.obter_por_id(db, tid) is None

    def test_deletar_inexistente(self, db):
        assert AgendamentoService.deletar(db, 9999) is False

    def test_listar_filtros(self, db):
        when = (datetime.now() + timedelta(hours=2)).isoformat()
        t1 = AgendamentoService.criar(db, TarefaAgendadaCriar(
            titulo="t1", tipo=TipoAgendamento.ONCE, quando=when,
            acao=AcaoAgendamento.ENVIAR_MENSAGEM, payload={"texto": "x"},
            telefone_destino="55A",
        ))
        t2 = AgendamentoService.criar(db, TarefaAgendadaCriar(
            titulo="t2", tipo=TipoAgendamento.ONCE, quando=when,
            acao=AcaoAgendamento.ENVIAR_MENSAGEM, payload={"texto": "y"},
            telefone_destino="55B",
        ))

        so_A = AgendamentoService.listar(db, telefone="55A")
        ids = [t.id for t in so_A]
        assert t1.id in ids and t2.id not in ids


# ═══════════════════════════════════════════════════════════════════════════
# canal_credenciais — criptografia
# ═══════════════════════════════════════════════════════════════════════════

class TestCanalCredenciais:
    def test_round_trip(self):
        from canal.canal_credenciais import criptografar, descriptografar
        payload = {"bot_token": "abc123", "outro": "x"}
        token = criptografar(payload)
        assert token  # não vazio
        assert "abc123" not in token  # deve estar criptografado
        recovered = descriptografar(token)
        assert recovered == payload

    def test_descriptografar_none(self):
        from canal.canal_credenciais import descriptografar
        assert descriptografar(None) == {}
        assert descriptografar("") == {}

    def test_descriptografar_token_invalido(self):
        from canal.canal_credenciais import descriptografar
        # token mal-formado retorna {} (não levanta)
        assert descriptografar("invalido_xxx") == {}


# ═══════════════════════════════════════════════════════════════════════════
# canal_factory
# ═══════════════════════════════════════════════════════════════════════════

class TestCanalFactory:
    def test_plataforma_desconhecida(self, tmp_path):
        from canal.canal_factory import criar_canal

        class Fake:
            id = 1
            plataforma = "desconhecida"
            credenciais = None

        result = criar_canal(
            sessao=Fake(),
            sessao_dir=str(tmp_path),
            on_mensagem=lambda e: None,
            on_status=lambda s, i: None,
        )
        assert result is None

    def test_telegram_sem_token(self, tmp_path):
        pytest.importorskip("telegram")
        from canal.canal_factory import criar_canal

        class Fake:
            id = 1
            plataforma = "telegram"
            credenciais = None  # vazio → descriptografar retorna {}

        result = criar_canal(
            sessao=Fake(),
            sessao_dir=str(tmp_path),
            on_mensagem=lambda e: None,
            on_status=lambda s, i: None,
        )
        assert result is None
