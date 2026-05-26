"""
Testes funcionais para FerramentaService e CurlParser.

Cobertura:
  - CRUD ferramentas
  - substituir_variaveis (com variáveis comuns, ferramenta, aninhadas, segurança env)
  - executar_ferramenta_code (síncrono e via NATIVE)
  - converter_para_openai_format
  - criar_ferramentas_padrao
  - CurlParser: parse, dict_to_curl, extract_variables, validate_curl
"""
from __future__ import annotations

import json
import pytest

from ferramenta.ferramenta_service import FerramentaService
from ferramenta.ferramenta_model import (
    Ferramenta, ToolType, ToolScope, OutputDestination, ChannelType
)
from ferramenta.ferramenta_schema import FerramentaCriar, FerramentaAtualizar
from ferramenta.curl_parser import CurlParser


# ═══════════════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestCrud:
    def test_criar_e_obter_por_id(self, db):
        nova = FerramentaService.criar(db, FerramentaCriar(
            nome="test_crud_1",
            descricao="desc",
            tool_type=ToolType.CODE,
            tool_scope=ToolScope.PRINCIPAL,
            codigo_python="resultado = {'ok': True}",
        ))
        obtida = FerramentaService.obter_por_id(db, nova.id)
        assert obtida is not None
        assert obtida.nome == "test_crud_1"

    def test_obter_por_nome(self, db, ferramenta_teste):
        f = FerramentaService.obter_por_nome(db, "ferramenta_teste")
        assert f is not None
        assert f.id == ferramenta_teste.id

    def test_obter_por_nome_inexistente(self, db):
        assert FerramentaService.obter_por_nome(db, "nunca_existiu") is None

    def test_listar_todas(self, db, ferramenta_teste):
        todas = FerramentaService.listar_todas(db)
        assert any(f.nome == "ferramenta_teste" for f in todas)

    def test_listar_apenas_ativas(self, db):
        FerramentaService.criar(db, FerramentaCriar(
            nome="ativa_1", descricao="x", tool_type=ToolType.CODE, ativa=True,
            codigo_python="resultado = {}",
        ))
        FerramentaService.criar(db, FerramentaCriar(
            nome="inativa_1", descricao="x", tool_type=ToolType.CODE, ativa=False,
            codigo_python="resultado = {}",
        ))
        ativas = FerramentaService.listar_ferramentas_ativas(db)
        nomes = [f.nome for f in ativas]
        assert "ativa_1" in nomes
        assert "inativa_1" not in nomes

    def test_atualizar(self, db, ferramenta_teste):
        atualizada = FerramentaService.atualizar(
            db, ferramenta_teste.id,
            FerramentaAtualizar(descricao="nova descricao")
        )
        assert atualizada.descricao == "nova descricao"

    def test_atualizar_inexistente(self, db):
        r = FerramentaService.atualizar(db, 999999, FerramentaAtualizar(descricao="x"))
        assert r is None

    def test_deletar(self, db, ferramenta_teste):
        fid = ferramenta_teste.id
        assert FerramentaService.deletar(db, fid) is True
        assert FerramentaService.obter_por_id(db, fid) is None

    def test_deletar_inexistente(self, db):
        assert FerramentaService.deletar(db, 999999) is False


# ═══════════════════════════════════════════════════════════════════════════
# substituir_variaveis
# ═══════════════════════════════════════════════════════════════════════════

class TestSubstituirVariaveis:
    def test_substituicao_simples(self):
        r = FerramentaService.substituir_variaveis(
            "Olá {nome}, idade {idade}",
            {"nome": "João", "idade": 30}
        )
        assert r == "Olá João, idade 30"

    def test_substituicao_var_ferramenta(self):
        r = FerramentaService.substituir_variaveis(
            "Bearer {var.API_KEY}",
            {},
            variaveis_ferramenta={"API_KEY": "secret123"}
        )
        assert r == "Bearer secret123"

    def test_substituicao_aninhada(self):
        r = FerramentaService.substituir_variaveis(
            "Cidade: {resultado.local.cidade}",
            {"resultado": {"local": {"cidade": "São Paulo"}}}
        )
        assert r == "Cidade: São Paulo"

    def test_env_bloqueada(self):
        """{env.X} deve ser BLOQUEADA por segurança."""
        r = FerramentaService.substituir_variaveis(
            "Token: {env.SECRET_KEY}",
            {"env": {"SECRET_KEY": "deveria-bloquear"}}
        )
        # Não substitui — retorna a string original
        assert "{env.SECRET_KEY}" in r

    def test_variavel_inexistente_mantida(self):
        r = FerramentaService.substituir_variaveis("Olá {desconhecida}", {})
        assert "{desconhecida}" in r

    def test_dict_value_serializado_como_json(self):
        r = FerramentaService.substituir_variaveis(
            "data={obj}",
            {"obj": {"k": "v"}}
        )
        assert r == 'data={"k": "v"}'

    def test_nao_substitui_chave_invalida(self):
        """Chaves com caracteres não-identificadores não são tratadas como vars."""
        # "Nada {a b c}" -> regex só captura [a-zA-Z_][a-zA-Z0-9_.]*
        r = FerramentaService.substituir_variaveis("teste {a b c}", {"a b c": "X"})
        assert "{a b c}" in r


# ═══════════════════════════════════════════════════════════════════════════
# executar_ferramenta_code (async)
# ═══════════════════════════════════════════════════════════════════════════

class TestExecutarCode:
    async def test_executar_code_basico(self, db):
        f = FerramentaService.criar(db, FerramentaCriar(
            nome="exec_basico", descricao="d",
            tool_type=ToolType.CODE,
            codigo_python="resultado = {'soma': argumentos['a'] + argumentos['b']}",
        ))
        r = await FerramentaService.executar_ferramenta_code(f, {"a": 2, "b": 3}, db)
        assert r == {"soma": 5}

    async def test_executar_code_sem_codigo(self, db):
        f = FerramentaService.criar(db, FerramentaCriar(
            nome="sem_codigo", descricao="d", tool_type=ToolType.CODE,
        ))
        r = await FerramentaService.executar_ferramenta_code(f, {}, db)
        assert "erro" in r

    async def test_executar_code_com_excecao(self, db):
        f = FerramentaService.criar(db, FerramentaCriar(
            nome="com_erro", descricao="d",
            tool_type=ToolType.CODE,
            codigo_python="raise RuntimeError('falhou')",
        ))
        r = await FerramentaService.executar_ferramenta_code(f, {}, db)
        assert "erro" in r
        assert "falhou" in r["erro"]

    async def test_executar_code_substitui_argumentos(self, db):
        f = FerramentaService.criar(db, FerramentaCriar(
            nome="substitui", descricao="d",
            tool_type=ToolType.CODE,
            substituir=True,
            codigo_python="resultado = {'nome': '{nome}'}",
        ))
        r = await FerramentaService.executar_ferramenta_code(f, {"nome": "João"}, db)
        assert r == {"nome": "João"}

    async def test_executar_ferramenta_nao_encontrada(self, db):
        r = await FerramentaService.executar_ferramenta(db, "nunca_existiu", {})
        assert "erro" in r

    async def test_executar_ferramenta_desativada(self, db):
        f = FerramentaService.criar(db, FerramentaCriar(
            nome="desativada", descricao="d", tool_type=ToolType.CODE, ativa=False,
            codigo_python="resultado = {}",
        ))
        r = await FerramentaService.executar_ferramenta(db, "desativada", {})
        assert "erro" in r


# ═══════════════════════════════════════════════════════════════════════════
# converter_para_openai_format
# ═══════════════════════════════════════════════════════════════════════════

class TestConverterOpenAI:
    def test_converte_principal(self, db):
        f = FerramentaService.criar(db, FerramentaCriar(
            nome="tool_ai", descricao="Faz X",
            tool_type=ToolType.CODE, tool_scope=ToolScope.PRINCIPAL,
            params=json.dumps({
                "texto": {"type": "string", "required": True, "description": "Texto"},
                "qtd": {"type": "integer", "required": False, "description": "Quantidade"},
            }),
            codigo_python="resultado = {}",
        ))
        schema = FerramentaService.converter_para_openai_format(f)
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "tool_ai"
        assert schema["function"]["description"] == "Faz X"
        props = schema["function"]["parameters"]["properties"]
        assert props["texto"]["type"] == "string"
        assert "texto" in schema["function"]["parameters"]["required"]
        assert "qtd" not in schema["function"]["parameters"]["required"]

    def test_auxiliar_retorna_none(self, db):
        f = FerramentaService.criar(db, FerramentaCriar(
            nome="aux", descricao="d", tool_type=ToolType.CODE,
            tool_scope=ToolScope.AUXILIAR,
            codigo_python="resultado = {}",
        ))
        assert FerramentaService.converter_para_openai_format(f) is None

    def test_converte_enum_e_array(self, db):
        f = FerramentaService.criar(db, FerramentaCriar(
            nome="tool_enum", descricao="d", tool_type=ToolType.CODE,
            params=json.dumps({
                "modo": {"type": "enum", "options": ["a", "b"], "description": "Modo"},
                "tags": {"type": "array", "item_type": "string"},
            }),
            codigo_python="resultado = {}",
        ))
        schema = FerramentaService.converter_para_openai_format(f)
        props = schema["function"]["parameters"]["properties"]
        assert props["modo"]["type"] == "string"
        assert props["modo"]["enum"] == ["a", "b"]
        assert props["tags"]["type"] == "array"
        assert props["tags"]["items"]["type"] == "string"

    def test_sem_params(self, db):
        f = FerramentaService.criar(db, FerramentaCriar(
            nome="tool_no_params", descricao="d", tool_type=ToolType.CODE,
            codigo_python="resultado = {}",
        ))
        schema = FerramentaService.converter_para_openai_format(f)
        assert schema["function"]["parameters"]["properties"] == {}
        assert schema["function"]["parameters"]["required"] == []


# ═══════════════════════════════════════════════════════════════════════════
# criar_ferramentas_padrao
# ═══════════════════════════════════════════════════════════════════════════

class TestCriarPadrao:
    def test_cria_ferramentas_padrao(self, db):
        FerramentaService.criar_ferramentas_padrao(db)
        todas = FerramentaService.listar_todas(db)
        nomes = {f.nome for f in todas}
        # Verifica que pelo menos as ferramentas básicas existem
        assert "obter_data_hora_atual" in nomes
        assert "calcular" in nomes

    def test_padrao_idempotente(self, db):
        FerramentaService.criar_ferramentas_padrao(db)
        n1 = len(FerramentaService.listar_todas(db))
        FerramentaService.criar_ferramentas_padrao(db)
        n2 = len(FerramentaService.listar_todas(db))
        assert n1 == n2


# ═══════════════════════════════════════════════════════════════════════════
# Ferramentas padrão executáveis
# ═══════════════════════════════════════════════════════════════════════════

class TestFerramentasPadraoExecutaveis:
    async def test_obter_data_hora_atual(self, db):
        FerramentaService.criar_ferramentas_padrao(db)
        f = FerramentaService.obter_por_nome(db, "obter_data_hora_atual")
        assert f is not None
        r = await FerramentaService.executar_ferramenta_code(f, {}, db)
        assert "data" in r and "hora" in r
        assert "/" in r["data"]

    async def test_calcular_simples(self, db):
        FerramentaService.criar_ferramentas_padrao(db)
        f = FerramentaService.obter_por_nome(db, "calcular")
        r = await FerramentaService.executar_ferramenta_code(
            f, {"expressao": "2 + 3 * 4"}, db
        )
        assert r["resultado"] == 14

    async def test_calcular_caracteres_invalidos(self, db):
        FerramentaService.criar_ferramentas_padrao(db)
        f = FerramentaService.obter_por_nome(db, "calcular")
        r = await FerramentaService.executar_ferramenta_code(
            f, {"expressao": "__import__('os')"}, db
        )
        assert "erro" in r


# ═══════════════════════════════════════════════════════════════════════════
# CurlParser
# ═══════════════════════════════════════════════════════════════════════════

class TestCurlParser:
    def test_get_simples(self):
        r = CurlParser.parse_curl("curl https://api.example.com/users")
        assert r["method"] == "GET"
        assert r["url"] == "https://api.example.com/users"

    def test_get_com_query_params(self):
        r = CurlParser.parse_curl("curl https://api.example.com/users?page=1&size=10")
        assert r["url"] == "https://api.example.com/users"
        assert r["query_params"]["page"] == "1"
        assert r["query_params"]["size"] == "10"

    def test_post_com_json(self):
        curl = 'curl -X POST https://api.example.com/users -H "Content-Type: application/json" -d \'{"nome": "João"}\''
        r = CurlParser.parse_curl(curl)
        assert r["method"] == "POST"
        assert r["headers"]["Content-Type"] == "application/json"
        assert json.loads(r["body"]) == {"nome": "João"}
        assert r["body_type"] == "json"

    def test_method_inferido_de_body(self):
        """Sem -X, mas com -d, deve inferir POST."""
        r = CurlParser.parse_curl('curl https://api.example.com -d \'{"x": 1}\'')
        assert r["method"] == "POST"

    def test_multiplos_headers(self):
        curl = ('curl https://api.example.com '
                '-H "Authorization: Bearer abc" '
                '-H "X-Custom: value"')
        r = CurlParser.parse_curl(curl)
        assert r["headers"]["Authorization"] == "Bearer abc"
        assert r["headers"]["X-Custom"] == "value"

    def test_basic_auth(self):
        r = CurlParser.parse_curl('curl https://api.example.com -u user:pass')
        assert r["auth"]["type"] == "basic"
        # Authorization header foi adicionado
        assert "Authorization" in r["headers"]
        assert r["headers"]["Authorization"].startswith("Basic ")

    def test_dict_to_curl_e_volta(self):
        original_curl = (
            'curl -X POST "https://api.example.com/users" '
            '-H "Authorization: Bearer xyz" '
            '-d \'{"name": "Maria"}\''
        )
        parsed = CurlParser.parse_curl(original_curl)
        rebuilt = CurlParser.dict_to_curl(parsed)
        assert "POST" in rebuilt
        assert "https://api.example.com/users" in rebuilt
        assert "Authorization: Bearer xyz" in rebuilt

    def test_extract_variables(self):
        curl = (
            'curl https://api.com/{user_id}?token={var.TOKEN} '
            '-H "X-Email: {email}"'
        )
        vars_found = CurlParser.extract_variables(curl)
        assert "user_id" in vars_found
        assert "var.TOKEN" in vars_found
        assert "email" in vars_found

    def test_validate_curl_valido(self):
        ok, _ = CurlParser.validate_curl("curl https://api.example.com")
        assert ok is True

    def test_validate_curl_vazio(self):
        ok, msg = CurlParser.validate_curl("")
        assert ok is False
        assert "vazio" in msg.lower() or "empty" in msg.lower()

    def test_validate_curl_sem_curl(self):
        ok, msg = CurlParser.validate_curl("wget https://api.example.com")
        assert ok is False

    def test_validate_curl_sem_url(self):
        ok, msg = CurlParser.validate_curl("curl -X GET")
        assert ok is False
