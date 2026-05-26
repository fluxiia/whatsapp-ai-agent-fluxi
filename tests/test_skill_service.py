"""
Testes funcionais para SkillService.
"""
from __future__ import annotations

import json

import pytest

from skill.skill_service import SkillService
from skill.skill_schema import SkillCriar, SkillAtualizar
from ferramenta.ferramenta_service import FerramentaService
from ferramenta.ferramenta_schema import FerramentaCriar
from ferramenta.ferramenta_model import ToolType


def _dados_skill(nome="skill_x", descricao="d", instrucao="# t", **extras) -> SkillCriar:
    return SkillCriar(
        nome=nome, descricao=descricao, instrucao_completa=instrucao, **extras
    )


class TestCrud:
    def test_criar_e_obter(self, db):
        s = SkillService.criar(db, _dados_skill("nova", "alguma", "# Inst"))
        assert s.id is not None
        assert SkillService.obter_por_id(db, s.id).id == s.id
        assert SkillService.obter_por_nome(db, "nova").id == s.id

    def test_listar_todas_e_ativas(self, db):
        SkillService.criar(db, _dados_skill("ativa_a", "x", "y", categoria="z"))
        SkillService.criar(db, _dados_skill("inativa_a", "x", "y", ativa=False))
        todas = SkillService.listar_todas(db)
        ativas = SkillService.listar_ativas(db)
        nomes_todas = {s.nome for s in todas}
        nomes_ativas = {s.nome for s in ativas}
        assert {"ativa_a", "inativa_a"}.issubset(nomes_todas)
        assert "inativa_a" not in nomes_ativas

    def test_atualizar(self, db):
        s = SkillService.criar(db, _dados_skill("atualizar", "d", "x"))
        a = SkillService.atualizar(db, s.id, SkillAtualizar(descricao="nova"))
        assert a.descricao == "nova"

    def test_atualizar_inexistente(self, db):
        assert SkillService.atualizar(db, 999, SkillAtualizar(descricao="x")) is None

    def test_deletar(self, db):
        s = SkillService.criar(db, _dados_skill("del", "d", "x"))
        sid = s.id
        assert SkillService.deletar(db, sid) is True
        assert SkillService.obter_por_id(db, sid) is None

    def test_deletar_inexistente(self, db):
        assert SkillService.deletar(db, 999) is False


class TestExecutarScript:
    def test_sem_script_retorna_vazio(self, db):
        s = SkillService.criar(db, _dados_skill("sem_script", "d", "x"))
        r = SkillService.executar_script(s, {})
        assert r == {}

    def test_script_define_resultado_dict(self, db):
        s = SkillService.criar(db, _dados_skill(
            "tem_script", "d", "x",
            script_codigo="resultado = {'a': argumentos.get('nome', 'anon')}",
        ))
        r = SkillService.executar_script(s, {"nome": "Ana"})
        assert r == {"a": "Ana"}

    def test_script_retorna_nao_dict_vira_output(self, db):
        s = SkillService.criar(db, _dados_skill(
            "string_script", "d", "x",
            script_codigo="resultado = 'plain string'",
        ))
        r = SkillService.executar_script(s, {})
        assert r == {"output": "plain string"}

    def test_script_com_erro_retorna_erro_script(self, db):
        s = SkillService.criar(db, _dados_skill(
            "broken_script", "d", "x",
            script_codigo="raise RuntimeError('falhou')",
        ))
        r = SkillService.executar_script(s, {})
        assert "erro_script" in r


class TestAssociacaoAgente:
    def test_atualizar_skills_agente(self, db, agente_teste):
        s1 = SkillService.criar(db, _dados_skill("a1", "d", "i"))
        s2 = SkillService.criar(db, _dados_skill("a2", "d", "i"))
        SkillService.atualizar_skills_agente(db, agente_teste.id, [s1.id, s2.id])
        skills = SkillService.listar_skills_agente(db, agente_teste.id)
        assert len(skills) == 2

    def test_atualizar_substitui(self, db, agente_teste):
        s1 = SkillService.criar(db, _dados_skill("p1", "d", "i"))
        s2 = SkillService.criar(db, _dados_skill("p2", "d", "i"))
        SkillService.atualizar_skills_agente(db, agente_teste.id, [s1.id])
        SkillService.atualizar_skills_agente(db, agente_teste.id, [s2.id])
        skills = SkillService.listar_skills_agente(db, agente_teste.id)
        assert len(skills) == 1
        assert skills[0].nome == "p2"

    def test_atualizar_skills_id_invalido(self, db, agente_teste):
        with pytest.raises(ValueError):
            SkillService.atualizar_skills_agente(db, agente_teste.id, [99999])


class TestFerramentasExtras:
    def test_skill_sem_ferramentas_ids(self, db):
        s = SkillService.criar(db, _dados_skill("sem_tools", "d", "i"))
        assert SkillService.obter_ferramentas_extras_da_skill(db, s) == []

    def test_skill_com_ferramentas_ids(self, db):
        f = FerramentaService.criar(db, FerramentaCriar(
            nome="extra_t", descricao="d", tool_type=ToolType.CODE,
            codigo_python="resultado = {}",
        ))
        s = SkillService.criar(db, _dados_skill(
            "com_tools", "d", "i", ferramentas_ids=json.dumps([f.id]),
        ))
        ferramentas = SkillService.obter_ferramentas_extras_da_skill(db, s)
        assert len(ferramentas) == 1
        assert ferramentas[0].id == f.id

    def test_skill_ferramentas_ids_invalido(self, db):
        s = SkillService.criar(db, _dados_skill(
            "tools_invalido", "d", "i", ferramentas_ids="nao eh json",
        ))
        # Não levanta — retorna lista vazia
        assert SkillService.obter_ferramentas_extras_da_skill(db, s) == []


class TestSkillsPadrao:
    def test_criar_skills_padrao(self, db):
        # criar ferramentas padrão antes para o auto-wiring
        FerramentaService.criar_ferramentas_padrao(db)
        SkillService.criar_skills_padrao(db)
        todas = SkillService.listar_todas(db)
        nomes = {s.nome for s in todas}
        # várias skills padrão devem existir
        assert "atendimento-educado" in nomes
        assert "vendas" in nomes
        assert "meta_ferramentas" in nomes

    def test_skills_padrao_idempotente(self, db):
        FerramentaService.criar_ferramentas_padrao(db)
        SkillService.criar_skills_padrao(db)
        n1 = len(SkillService.listar_todas(db))
        SkillService.criar_skills_padrao(db)
        n2 = len(SkillService.listar_todas(db))
        assert n1 == n2
