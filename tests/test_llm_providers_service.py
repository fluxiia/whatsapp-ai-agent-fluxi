"""
Testes funcionais para ProvedorLLMService (CRUD + estatísticas).

Não testa conexão real com APIs externas.
"""
from __future__ import annotations

import pytest

from llm_providers.llm_providers_service import ProvedorLLMService
from llm_providers.llm_providers_schema import (
    ProvedorLLMCriar, ProvedorLLMAtualizar
)
from llm_providers.llm_providers_model import (
    ProvedorLLM, EstatisticasProvedor
)


def _criar_provedor(db, nome="ProvA", url="http://localhost:1234", **kw):
    schema = ProvedorLLMCriar(
        nome=nome, base_url=url, api_key=kw.get("api_key"),
        descricao=kw.get("descricao"), ativo=kw.get("ativo", True),
    )
    return ProvedorLLMService.criar(db, schema)


class TestCrud:
    def test_criar(self, db):
        p = _criar_provedor(db, nome="LM Studio Local")
        assert p.id is not None
        assert p.nome == "LM Studio Local"
        # Estatísticas criadas automaticamente
        stats = db.query(EstatisticasProvedor).filter(
            EstatisticasProvedor.provedor_id == p.id
        ).first()
        assert stats is not None

    def test_listar_todos(self, db):
        _criar_provedor(db, nome="p1")
        _criar_provedor(db, nome="p2")
        todos = ProvedorLLMService.listar_todos(db)
        nomes = [p.nome for p in todos]
        assert "p1" in nomes and "p2" in nomes

    def test_listar_ativos(self, db):
        a = _criar_provedor(db, nome="ativo", ativo=True)
        i = _criar_provedor(db, nome="inativo", ativo=False)
        ativos = ProvedorLLMService.listar_ativos(db)
        ids = [p.id for p in ativos]
        assert a.id in ids and i.id not in ids

    def test_obter_por_id(self, db):
        p = _criar_provedor(db)
        assert ProvedorLLMService.obter_por_id(db, p.id).id == p.id
        assert ProvedorLLMService.obter_por_id(db, 9999) is None

    def test_atualizar(self, db):
        p = _criar_provedor(db, nome="orig")
        a = ProvedorLLMService.atualizar(db, p.id, ProvedorLLMAtualizar(
            descricao="nova", ativo=False
        ))
        assert a.descricao == "nova"
        assert a.ativo is False

    def test_atualizar_inexistente(self, db):
        assert ProvedorLLMService.atualizar(
            db, 9999, ProvedorLLMAtualizar(descricao="x")
        ) is None

    def test_deletar(self, db):
        p = _criar_provedor(db)
        pid = p.id
        assert ProvedorLLMService.deletar(db, pid) is True
        assert ProvedorLLMService.obter_por_id(db, pid) is None
        # estatísticas também removidas
        stats = db.query(EstatisticasProvedor).filter(
            EstatisticasProvedor.provedor_id == pid
        ).count()
        assert stats == 0

    def test_deletar_inexistente(self, db):
        assert ProvedorLLMService.deletar(db, 9999) is False


class TestEstatisticas:
    def test_obter_estatisticas_inicial(self, db):
        p = _criar_provedor(db)
        stats = ProvedorLLMService.obter_estatisticas(db, p.id)
        assert stats is not None
        assert stats.total_requisicoes == 0
        assert stats.requisicoes_sucesso == 0
        assert stats.requisicoes_erro == 0

    def test_obter_estatisticas_inexistente(self, db):
        assert ProvedorLLMService.obter_estatisticas(db, 99999) is None

    def test_atualizar_estatisticas_sucesso(self, db):
        p = _criar_provedor(db)
        ProvedorLLMService._atualizar_estatisticas(db, p.id, sucesso=True, tempo_ms=100)
        ProvedorLLMService._atualizar_estatisticas(db, p.id, sucesso=True, tempo_ms=300)
        stats = ProvedorLLMService.obter_estatisticas(db, p.id)
        assert stats.total_requisicoes == 2
        assert stats.requisicoes_sucesso == 2

    def test_atualizar_estatisticas_misto(self, db):
        p = _criar_provedor(db)
        ProvedorLLMService._atualizar_estatisticas(db, p.id, sucesso=True, tempo_ms=100)
        ProvedorLLMService._atualizar_estatisticas(db, p.id, sucesso=False, tempo_ms=200)
        stats = ProvedorLLMService.obter_estatisticas(db, p.id)
        assert stats.total_requisicoes == 2
        assert stats.requisicoes_sucesso == 1
        assert stats.requisicoes_erro == 1
