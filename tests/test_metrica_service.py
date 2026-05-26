"""
Testes funcionais para MetricaService.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from metrica.metrica_service import MetricaService
from mensagem.mensagem_model import Mensagem


def _criar_msg(db, sessao_id, **kw):
    defaults = dict(
        sessao_id=sessao_id,
        telefone_cliente="5511",
        direcao="recebida",
        tipo="texto",
        conteudo_texto="x",
        processada=False,
        respondida=False,
    )
    defaults.update(kw)
    m = Mensagem(**defaults)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


class TestMetricasGerais:
    def test_sem_dados(self, db):
        m = MetricaService.obter_metricas_gerais(db)
        assert m["sessoes"]["total"] == 0
        assert m["mensagens"]["total"] == 0
        assert m["performance"]["taxa_sucesso"] == 0

    def test_com_dados(self, db, sessao_teste):
        # 3 recebidas, 2 respondidas
        _criar_msg(db, sessao_teste.id, telefone_cliente="A", direcao="recebida", respondida=True)
        _criar_msg(db, sessao_teste.id, telefone_cliente="A", direcao="recebida", respondida=True)
        _criar_msg(db, sessao_teste.id, telefone_cliente="B", direcao="recebida", respondida=False)
        _criar_msg(db, sessao_teste.id, telefone_cliente="A", direcao="enviada")

        m = MetricaService.obter_metricas_gerais(db)
        assert m["sessoes"]["total"] == 1
        assert m["mensagens"]["total"] == 4
        assert m["mensagens"]["recebidas"] == 3
        assert m["mensagens"]["enviadas"] == 1
        assert m["mensagens"]["respondidas"] == 2
        assert m["performance"]["clientes_unicos"] == 2
        # 2/3 * 100 = 66.67
        assert m["performance"]["taxa_sucesso"] == pytest.approx(66.67, abs=0.01)


class TestMetricasSessao:
    def test_sem_dados(self, db, sessao_teste):
        m = MetricaService.obter_metricas_sessao(db, sessao_teste.id)
        assert m["mensagens"]["total"] == 0
        assert m["performance"]["taxa_resposta"] == 0
        assert m["tokens"]["total"] == 0

    def test_calculos(self, db, sessao_teste):
        _criar_msg(db, sessao_teste.id, direcao="recebida", respondida=True,
                   resposta_tempo_ms=100, resposta_tokens_input=10, resposta_tokens_output=20)
        _criar_msg(db, sessao_teste.id, direcao="recebida", respondida=True,
                   resposta_tempo_ms=200, resposta_tokens_input=5, resposta_tokens_output=15)
        _criar_msg(db, sessao_teste.id, direcao="recebida", respondida=False)
        _criar_msg(db, sessao_teste.id, direcao="recebida", tipo="imagem")
        _criar_msg(db, sessao_teste.id, direcao="recebida",
                   ferramentas_usadas=[{"nome": "x"}])

        m = MetricaService.obter_metricas_sessao(db, sessao_teste.id)
        assert m["mensagens"]["total"] == 5
        assert m["mensagens"]["respondidas"] == 2
        assert m["mensagens"]["com_imagem"] == 1
        assert m["mensagens"]["com_ferramentas"] == 1
        # tempo_medio = (100+200)/2 = 150
        assert m["performance"]["tempo_medio_ms"] == pytest.approx(150)
        assert m["tokens"]["input_total"] == 15
        assert m["tokens"]["output_total"] == 35
        assert m["tokens"]["total"] == 50


class TestMetricasPeriodo:
    def test_periodo_filtra_antigas(self, db, sessao_teste):
        m_atual = _criar_msg(db, sessao_teste.id, direcao="recebida")
        m_antiga = _criar_msg(db, sessao_teste.id, direcao="recebida")
        m_antiga.criado_em = datetime.now() - timedelta(days=30)
        db.commit()

        r = MetricaService.obter_metricas_periodo(db, dias=7)
        assert r["periodo_dias"] == 7
        # só a mensagem atual conta
        assert r["total_periodo"] == 1

    def test_periodo_filtra_por_sessao(self, db, sessao_teste):
        # Cria 2ª sessão
        from sessao.sessao_model import Sessao
        s2 = Sessao(nome="outra", plataforma="whatsapp", status="desconectado")
        db.add(s2); db.commit()

        _criar_msg(db, sessao_teste.id, direcao="recebida")
        _criar_msg(db, s2.id, direcao="recebida")

        r = MetricaService.obter_metricas_periodo(db, sessao_id=sessao_teste.id)
        assert r["total_periodo"] == 1


class TestTopClientes:
    def test_top_clientes(self, db, sessao_teste):
        for _ in range(3):
            _criar_msg(db, sessao_teste.id, telefone_cliente="A", direcao="recebida")
        for _ in range(2):
            _criar_msg(db, sessao_teste.id, telefone_cliente="B", direcao="recebida")
        _criar_msg(db, sessao_teste.id, telefone_cliente="C", direcao="recebida")

        top = MetricaService.obter_top_clientes(db, sessao_teste.id, limite=3)
        assert top[0]["telefone"] == "A"
        assert top[0]["total_mensagens"] == 3
        assert top[1]["telefone"] == "B"

    def test_top_clientes_so_recebidas(self, db, sessao_teste):
        _criar_msg(db, sessao_teste.id, telefone_cliente="X", direcao="enviada")
        top = MetricaService.obter_top_clientes(db, sessao_teste.id)
        assert top == []


class TestUsoFerramentas:
    def test_uso_ferramentas(self, db, sessao_teste):
        _criar_msg(db, sessao_teste.id, ferramentas_usadas=[{"nome": "calcular"}])
        _criar_msg(db, sessao_teste.id, ferramentas_usadas=[
            {"nome": "calcular"}, {"nome": "buscar"}
        ])

        uso = MetricaService.obter_uso_ferramentas(db, sessao_teste.id)
        # calcular: 2 usos, buscar: 1
        assert uso[0]["nome"] == "calcular"
        assert uso[0]["total_usos"] == 2
        assert uso[1]["nome"] == "buscar"

    def test_uso_ferramentas_vazio(self, db, sessao_teste):
        assert MetricaService.obter_uso_ferramentas(db, sessao_teste.id) == []
