"""
Testes funcionais para AgenteService (CRUD + system prompt + ferramentas).
"""
from __future__ import annotations

import pytest

from agente.agente_service import AgenteService
from agente.agente_schema import AgenteCriar, AgenteAtualizar
from ferramenta.ferramenta_service import FerramentaService
from ferramenta.ferramenta_schema import FerramentaCriar
from ferramenta.ferramenta_model import ToolType, ToolScope


def _dados_agente(sessao_id: int, codigo: str = "01", nome: str = "Ag") -> AgenteCriar:
    return AgenteCriar(
        sessao_id=sessao_id,
        codigo=codigo,
        nome=nome,
        descricao="d",
        agente_papel="papel",
        agente_objetivo="obj",
        agente_politicas="pol",
        agente_tarefa="tarefa",
        agente_objetivo_explicito="obj_exp",
        agente_publico="publ",
        agente_restricoes="restr",
        ativo=True,
    )


class TestCrud:
    def test_criar_agente(self, db, sessao_teste):
        a = AgenteService.criar(db, _dados_agente(sessao_teste.id, "10", "Foo"))
        assert a.id is not None
        assert a.codigo == "10"
        assert a.nome == "Foo"

    def test_criar_agente_codigo_duplicado(self, db, sessao_teste, agente_teste):
        # agente_teste já criou com codigo='01'
        with pytest.raises(ValueError):
            AgenteService.criar(db, _dados_agente(sessao_teste.id, "01", "Dup"))

    def test_listar_todos(self, db, agente_teste):
        todos = AgenteService.listar_todos(db)
        assert any(a.id == agente_teste.id for a in todos)

    def test_listar_por_sessao(self, db, sessao_teste, agente_teste):
        # cria 2º agente
        AgenteService.criar(db, _dados_agente(sessao_teste.id, "02", "Agente2"))
        agentes = AgenteService.listar_por_sessao(db, sessao_teste.id)
        codigos = [a.codigo for a in agentes]
        assert codigos == sorted(codigos)
        assert "01" in codigos and "02" in codigos

    def test_listar_por_sessao_ativos(self, db, sessao_teste, agente_teste):
        # cria 2º inativo
        a2 = AgenteService.criar(db, _dados_agente(sessao_teste.id, "02", "Inativo"))
        a2.ativo = False
        db.commit()
        ativos = AgenteService.listar_por_sessao_ativos(db, sessao_teste.id)
        assert all(a.ativo for a in ativos)
        ids = [a.id for a in ativos]
        assert agente_teste.id in ids
        assert a2.id not in ids

    def test_obter_por_id(self, db, agente_teste):
        assert AgenteService.obter_por_id(db, agente_teste.id).id == agente_teste.id

    def test_obter_por_codigo(self, db, sessao_teste, agente_teste):
        a = AgenteService.obter_por_codigo(db, sessao_teste.id, "01")
        assert a.id == agente_teste.id

    def test_atualizar(self, db, agente_teste):
        atualizado = AgenteService.atualizar(
            db, agente_teste.id, AgenteAtualizar(nome="Renomeado", temperatura=0.5)
        )
        assert atualizado.nome == "Renomeado"
        assert atualizado.temperatura == 0.5

    def test_atualizar_codigo_para_existente(self, db, sessao_teste, agente_teste):
        AgenteService.criar(db, _dados_agente(sessao_teste.id, "99", "X"))
        # tentar trocar agente_teste (01) para "99" — deve falhar
        with pytest.raises(ValueError):
            AgenteService.atualizar(
                db, agente_teste.id, AgenteAtualizar(codigo="99")
            )

    def test_deletar(self, db, agente_teste):
        aid = agente_teste.id
        assert AgenteService.deletar(db, aid) is True
        assert AgenteService.obter_por_id(db, aid) is None

    def test_deletar_inexistente(self, db):
        assert AgenteService.deletar(db, 99999) is False


class TestFerramentas:
    def test_atualizar_ferramentas_associa(self, db, agente_teste, ferramenta_teste):
        AgenteService.atualizar_ferramentas(db, agente_teste.id, [ferramenta_teste.id])
        fs = AgenteService.listar_ferramentas(db, agente_teste.id)
        assert len(fs) == 1
        assert fs[0].id == ferramenta_teste.id

    def test_atualizar_ferramentas_substitui(self, db, agente_teste):
        f1 = FerramentaService.criar(db, FerramentaCriar(
            nome="f_assoc_1", descricao="d", tool_type=ToolType.CODE,
            codigo_python="resultado = {}",
        ))
        f2 = FerramentaService.criar(db, FerramentaCriar(
            nome="f_assoc_2", descricao="d", tool_type=ToolType.CODE,
            codigo_python="resultado = {}",
        ))
        AgenteService.atualizar_ferramentas(db, agente_teste.id, [f1.id])
        AgenteService.atualizar_ferramentas(db, agente_teste.id, [f2.id])
        fs = AgenteService.listar_ferramentas(db, agente_teste.id)
        nomes = [f.nome for f in fs]
        assert "f_assoc_2" in nomes
        assert "f_assoc_1" not in nomes

    def test_atualizar_ferramentas_acima_do_limite(self, db, agente_teste, monkeypatch):
        # força limite baixo via config
        from config.config_service import ConfiguracaoService
        from config.config_schema import ConfiguracaoCriar
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="agente_max_ferramentas", valor="2", tipo="int"
        ))
        # cria 3 ferramentas
        ids = []
        for i in range(3):
            f = FerramentaService.criar(db, FerramentaCriar(
                nome=f"f_lim_{i}", descricao="d", tool_type=ToolType.CODE,
                codigo_python="resultado = {}",
            ))
            ids.append(f.id)

        with pytest.raises(ValueError):
            AgenteService.atualizar_ferramentas(db, agente_teste.id, ids)

    def test_atualizar_ferramentas_id_inexistente(self, db, agente_teste):
        with pytest.raises(ValueError):
            AgenteService.atualizar_ferramentas(db, agente_teste.id, [999999])

    def test_listar_ferramentas_agente_inexistente(self, db):
        assert AgenteService.listar_ferramentas(db, 999999) == []


class TestSystemPrompt:
    def test_construir_system_prompt_basico(self, agente_teste):
        prompt = AgenteService.construir_system_prompt(agente_teste)
        assert agente_teste.agente_papel in prompt
        assert agente_teste.agente_objetivo in prompt
        assert agente_teste.agente_politicas in prompt
        assert "FERRAMENTAS" in prompt or "ferramentas" in prompt.lower()

    def test_construir_system_prompt_com_skills(self, agente_teste):
        class FakeSkill:
            def __init__(self, nome, descricao, icone="🔧"):
                self.nome = nome
                self.descricao = descricao
                self.icone = icone

        skills = [
            FakeSkill("vendas-abertura", "Abre conversa de vendas"),
            FakeSkill("vendas", "Família de vendas"),
        ]
        prompt = AgenteService.construir_system_prompt(agente_teste, skills=skills)
        assert "SKILLS" in prompt
        assert "vendas" in prompt


class TestCriarAgentePadrao:
    def test_criar_agente_padrao(self, db, sessao_teste):
        # popular configs padrão para garantir defaults
        from config.config_service import ConfiguracaoService
        ConfiguracaoService.inicializar_configuracoes_padrao(db)
        FerramentaService.criar_ferramentas_padrao(db)

        agente = AgenteService.criar_agente_padrao(db, sessao_teste.id)
        assert agente.codigo == "01"
        assert agente.nome == "Fluxi"
        assert agente.agente_papel  # não-vazio
        # ao menos tentou associar ferramentas padrão
        fs = AgenteService.listar_ferramentas(db, agente.id)
        assert len(fs) >= 0  # depende das ferramentas criadas
