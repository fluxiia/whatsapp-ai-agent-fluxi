"""
Testes funcionais para ConfiguracaoService.

Cobertura:
  - obter_por_chave / obter_valor (com conversão de tipos)
  - listar_todas / listar_por_categoria
  - criar / atualizar / deletar
  - definir_valor (criação automática)
  - inicializar_configuracoes_padrao
  - proteção de configurações não-editáveis
"""
from __future__ import annotations

import pytest

from config.config_service import ConfiguracaoService
from config.config_schema import ConfiguracaoCriar, ConfiguracaoAtualizar


class TestObterValor:
    def test_obter_valor_string(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="chave_string", valor="hello", tipo="string", categoria="geral"
        ))
        assert ConfiguracaoService.obter_valor(db, "chave_string") == "hello"

    def test_obter_valor_int(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="chave_int", valor="42", tipo="int", categoria="geral"
        ))
        valor = ConfiguracaoService.obter_valor(db, "chave_int")
        assert valor == 42
        assert isinstance(valor, int)

    def test_obter_valor_float(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="chave_float", valor="3.14", tipo="float", categoria="geral"
        ))
        valor = ConfiguracaoService.obter_valor(db, "chave_float")
        assert valor == pytest.approx(3.14)
        assert isinstance(valor, float)

    def test_obter_valor_bool_true(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="chave_bool_t", valor="true", tipo="bool", categoria="geral"
        ))
        assert ConfiguracaoService.obter_valor(db, "chave_bool_t") is True

    def test_obter_valor_bool_false(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="chave_bool_f", valor="false", tipo="bool", categoria="geral"
        ))
        assert ConfiguracaoService.obter_valor(db, "chave_bool_f") is False

    def test_obter_valor_json(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="chave_json", valor='{"a": 1, "b": [1, 2]}', tipo="json", categoria="geral"
        ))
        valor = ConfiguracaoService.obter_valor(db, "chave_json")
        assert valor == {"a": 1, "b": [1, 2]}

    def test_obter_valor_inexistente_retorna_padrao(self, db):
        assert ConfiguracaoService.obter_valor(db, "nao_existe", padrao="fallback") == "fallback"
        assert ConfiguracaoService.obter_valor(db, "nao_existe") is None

    def test_obter_valor_tipo_invalido_retorna_padrao(self, db):
        """Valor que não converte para o tipo declarado retorna o padrão."""
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="chave_lixo", valor="nao_eh_int", tipo="int", categoria="geral"
        ))
        assert ConfiguracaoService.obter_valor(db, "chave_lixo", padrao=99) == 99


class TestCrud:
    def test_criar_e_obter_por_chave(self, db):
        novo = ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="nova_chave", valor="x", tipo="string", categoria="teste"
        ))
        assert novo.id is not None

        obtido = ConfiguracaoService.obter_por_chave(db, "nova_chave")
        assert obtido is not None
        assert obtido.valor == "x"

    def test_listar_todas(self, db):
        for i in range(3):
            ConfiguracaoService.criar(db, ConfiguracaoCriar(
                chave=f"chave_{i}", valor=str(i), tipo="string"
            ))
        todas = ConfiguracaoService.listar_todas(db)
        chaves = [c.chave for c in todas]
        assert "chave_0" in chaves
        assert "chave_1" in chaves
        assert "chave_2" in chaves

    def test_listar_por_categoria(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="cat_a_1", valor="x", tipo="string", categoria="cat_a"
        ))
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="cat_a_2", valor="y", tipo="string", categoria="cat_a"
        ))
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="cat_b_1", valor="z", tipo="string", categoria="cat_b"
        ))
        cat_a = ConfiguracaoService.listar_por_categoria(db, "cat_a")
        assert len(cat_a) == 2
        assert all(c.categoria == "cat_a" for c in cat_a)

    def test_atualizar(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="atualizar_me", valor="antigo", tipo="string"
        ))
        atualizado = ConfiguracaoService.atualizar(
            db, "atualizar_me",
            ConfiguracaoAtualizar(valor="novo", descricao="atualizada")
        )
        assert atualizado.valor == "novo"
        assert atualizado.descricao == "atualizada"

    def test_atualizar_inexistente_retorna_none(self, db):
        result = ConfiguracaoService.atualizar(
            db, "nao_existe", ConfiguracaoAtualizar(valor="x")
        )
        assert result is None

    def test_atualizar_nao_editavel_lanca_erro(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="protegida", valor="x", tipo="string", editavel=False
        ))
        with pytest.raises(ValueError):
            ConfiguracaoService.atualizar(
                db, "protegida", ConfiguracaoAtualizar(valor="y")
            )

    def test_deletar(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="deletar_me", valor="x", tipo="string"
        ))
        assert ConfiguracaoService.deletar(db, "deletar_me") is True
        assert ConfiguracaoService.obter_por_chave(db, "deletar_me") is None

    def test_deletar_inexistente(self, db):
        assert ConfiguracaoService.deletar(db, "nunca_existiu") is False

    def test_deletar_protegida_lanca_erro(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="nao_deletavel", valor="x", tipo="string", editavel=False
        ))
        with pytest.raises(ValueError):
            ConfiguracaoService.deletar(db, "nao_deletavel")


class TestDefinirValor:
    def test_definir_valor_cria_se_nao_existir(self, db):
        config = ConfiguracaoService.definir_valor(db, "auto_criada", "valor")
        assert config.valor == "valor"
        assert config.tipo == "string"

    def test_definir_valor_atualiza_existente(self, db):
        ConfiguracaoService.criar(db, ConfiguracaoCriar(
            chave="existe", valor="antigo", tipo="string"
        ))
        config = ConfiguracaoService.definir_valor(db, "existe", "novo")
        assert config.valor == "novo"

    def test_definir_valor_bool(self, db):
        config = ConfiguracaoService.definir_valor(db, "flag", True)
        assert config.tipo == "bool"
        assert ConfiguracaoService.obter_valor(db, "flag") is True

    def test_definir_valor_int(self, db):
        config = ConfiguracaoService.definir_valor(db, "num", 100)
        assert config.tipo == "int"
        assert ConfiguracaoService.obter_valor(db, "num") == 100

    def test_definir_valor_float(self, db):
        config = ConfiguracaoService.definir_valor(db, "pi", 3.14)
        assert config.tipo == "float"

    def test_definir_valor_json_dict(self, db):
        config = ConfiguracaoService.definir_valor(db, "dados", {"k": "v"})
        assert config.tipo == "json"
        assert ConfiguracaoService.obter_valor(db, "dados") == {"k": "v"}

    def test_definir_valor_json_list(self, db):
        config = ConfiguracaoService.definir_valor(db, "lista", [1, 2, 3])
        assert config.tipo == "json"

    def test_definir_valor_sem_criar_lanca_se_nao_existir(self, db):
        with pytest.raises(ValueError):
            ConfiguracaoService.definir_valor(
                db, "inexistente", "x", criar_se_nao_existir=False
            )


class TestInicializarPadrao:
    def test_inicializar_cria_configuracoes_basicas(self, db):
        ConfiguracaoService.inicializar_configuracoes_padrao(db)
        # Verifica que pelo menos as configurações chave existem
        assert ConfiguracaoService.obter_por_chave(db, "openrouter_modelo_padrao") is not None
        assert ConfiguracaoService.obter_por_chave(db, "openrouter_temperatura") is not None
        assert ConfiguracaoService.obter_por_chave(db, "agente_papel_padrao") is not None

    def test_inicializar_idempotente(self, db):
        """Chamar 2x não cria duplicatas."""
        ConfiguracaoService.inicializar_configuracoes_padrao(db)
        total1 = len(ConfiguracaoService.listar_todas(db))
        ConfiguracaoService.inicializar_configuracoes_padrao(db)
        total2 = len(ConfiguracaoService.listar_todas(db))
        assert total1 == total2

    def test_inicializar_valores_tipados_corretos(self, db):
        ConfiguracaoService.inicializar_configuracoes_padrao(db)
        temp = ConfiguracaoService.obter_valor(db, "openrouter_temperatura")
        max_tokens = ConfiguracaoService.obter_valor(db, "openrouter_max_tokens")
        assert isinstance(temp, float)
        assert isinstance(max_tokens, int)
