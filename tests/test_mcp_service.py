"""
Testes funcionais para MCPService e mcp_presets.
"""
from __future__ import annotations

import json

import pytest

from mcp_client.mcp_service import MCPService
from mcp_client.mcp_schema import (
    MCPClientCriar, MCPClientAtualizar,
    MCPPresetAplicarRequest, MCPOneClickRequest,
)
from mcp_client.mcp_client_model import MCPClient, TransportType
from mcp_client.mcp_tool_model import MCPTool
from mcp_client.mcp_presets import MCP_PRESETS, listar_presets, obter_preset


# ═══════════════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestCrud:
    def test_criar_stdio(self, db, agente_teste):
        c = MCPService.criar(db, MCPClientCriar(
            agente_id=agente_teste.id,
            nome="local_mcp",
            transport_type="stdio",
            command="python",
            args=["server.py"],
        ))
        assert c.id is not None
        assert c.nome == "local_mcp"
        assert c.command == "python"

    def test_criar_streamable_http(self, db, agente_teste):
        c = MCPService.criar(db, MCPClientCriar(
            agente_id=agente_teste.id,
            nome="remote_mcp",
            transport_type="streamable-http",
            url="http://localhost:8080/mcp",
        ))
        assert c.id is not None
        assert c.url == "http://localhost:8080/mcp"

    def test_stdio_aceita_preset_sem_command(self, db, agente_teste):
        # Quando preset_key está presente, command/url podem ser omitidos
        schema = MCPClientCriar(
            agente_id=agente_teste.id,
            nome="via_preset",
            transport_type="stdio",
            preset_key="alguma_chave",
        )
        assert schema.preset_key == "alguma_chave"

    def test_limite_clientes_por_agente(self, db, agente_teste):
        from config.config_service import ConfiguracaoService
        # Usa definir_valor (upsert) pra tolerar caso a config já exista
        # (criada pelo startup do FastAPI em testes que rodam antes).
        ConfiguracaoService.definir_valor(db, "mcp_max_clients_por_agente", 2)
        for i in range(2):
            MCPService.criar(db, MCPClientCriar(
                agente_id=agente_teste.id, nome=f"c{i}",
                transport_type="stdio", command="x",
            ))
        with pytest.raises(ValueError):
            MCPService.criar(db, MCPClientCriar(
                agente_id=agente_teste.id, nome="c_extra",
                transport_type="stdio", command="x",
            ))

    def test_listar_por_agente(self, db, agente_teste):
        for i in range(2):
            MCPService.criar(db, MCPClientCriar(
                agente_id=agente_teste.id, nome=f"x{i}",
                transport_type="stdio", command="y",
            ))
        clientes = MCPService.listar_por_agente(db, agente_teste.id)
        assert len(clientes) == 2

    def test_listar_ativos(self, db, agente_teste):
        a = MCPService.criar(db, MCPClientCriar(
            agente_id=agente_teste.id, nome="ativo", transport_type="stdio",
            command="x", ativo=True,
        ))
        i = MCPService.criar(db, MCPClientCriar(
            agente_id=agente_teste.id, nome="inativo", transport_type="stdio",
            command="x", ativo=False,
        ))
        ativos = MCPService.listar_ativos_por_agente(db, agente_teste.id)
        ids = [c.id for c in ativos]
        assert a.id in ids and i.id not in ids

    def test_contar_por_agente(self, db, agente_teste):
        assert MCPService.contar_por_agente(db, agente_teste.id) == 0
        MCPService.criar(db, MCPClientCriar(
            agente_id=agente_teste.id, nome="x", transport_type="stdio",
            command="y",
        ))
        assert MCPService.contar_por_agente(db, agente_teste.id) == 1

    def test_atualizar(self, db, agente_teste):
        c = MCPService.criar(db, MCPClientCriar(
            agente_id=agente_teste.id, nome="orig", transport_type="stdio",
            command="x",
        ))
        atualizado = MCPService.atualizar(db, c.id, MCPClientAtualizar(
            nome="novo", ativo=False,
        ))
        assert atualizado.nome == "novo"
        assert atualizado.ativo is False

    def test_atualizar_inexistente(self, db):
        assert MCPService.atualizar(db, 9999, MCPClientAtualizar(nome="x")) is None

    def test_deletar(self, db, agente_teste):
        c = MCPService.criar(db, MCPClientCriar(
            agente_id=agente_teste.id, nome="del", transport_type="stdio",
            command="x",
        ))
        cid = c.id
        assert MCPService.deletar(db, cid) is True
        assert MCPService.obter_por_id(db, cid) is None

    def test_deletar_inexistente(self, db):
        assert MCPService.deletar(db, 9999) is False


# ═══════════════════════════════════════════════════════════════════════════
# Presets
# ═══════════════════════════════════════════════════════════════════════════

class TestPresets:
    def test_listar_presets_disponiveis(self):
        presets = MCPService.listar_presets_disponiveis()
        assert len(presets) > 0
        # cada preset deve ter key, name e transport_type
        for p in presets:
            assert p.key
            assert p.name
            assert p.transport_type in {"stdio", "sse", "streamable-http"}

    def test_obter_preset_existente(self):
        p = obter_preset("aio-sandbox")
        assert p is not None
        assert p.key == "aio-sandbox"

    def test_obter_preset_inexistente(self):
        assert obter_preset("nao_existe_xyz") is None

    def test_aplicar_preset_falta_input(self, db, agente_teste):
        # aio-sandbox exige sandbox_url
        with pytest.raises(ValueError):
            MCPService.aplicar_preset(db, MCPPresetAplicarRequest(
                preset_key="aio-sandbox",
                agente_id=agente_teste.id,
                inputs={},
            ))

    def test_aplicar_preset_sucesso(self, db, agente_teste):
        c = MCPService.aplicar_preset(db, MCPPresetAplicarRequest(
            preset_key="aio-sandbox",
            agente_id=agente_teste.id,
            inputs={"sandbox_url": "http://localhost:8080/mcp"},
        ))
        assert c.preset_key == "aio-sandbox"
        assert c.url == "http://localhost:8080/mcp"

    def test_aplicar_preset_inexistente(self, db, agente_teste):
        with pytest.raises(ValueError):
            MCPService.aplicar_preset(db, MCPPresetAplicarRequest(
                preset_key="nao_existe", agente_id=agente_teste.id,
            ))

    def test_substituir_inputs(self):
        r = MCPService._substituir_inputs(
            "http://${input:host}/api?key=${input:key}",
            {"host": "example.com", "key": "abc"}
        )
        assert r == "http://example.com/api?key=abc"

    def test_substituir_inputs_nao_string(self):
        assert MCPService._substituir_inputs(123, {}) == 123


class TestOneClick:
    def test_one_click_json_invalido(self, db, agente_teste):
        with pytest.raises(ValueError):
            MCPService.aplicar_one_click(db, MCPOneClickRequest(
                agente_id=agente_teste.id,
                json_config="{ invalid json",
            ))

    def test_one_click_sem_mcp_servers(self, db, agente_teste):
        with pytest.raises(ValueError):
            MCPService.aplicar_one_click(db, MCPOneClickRequest(
                agente_id=agente_teste.id,
                json_config='{"foo": "bar"}',
            ))

    def test_one_click_mcp_servers_vazio(self, db, agente_teste):
        with pytest.raises(ValueError):
            MCPService.aplicar_one_click(db, MCPOneClickRequest(
                agente_id=agente_teste.id,
                json_config='{"mcpServers": {}}',
            ))


# ═══════════════════════════════════════════════════════════════════════════
# Conversão para OpenAI
# ═══════════════════════════════════════════════════════════════════════════

class TestConverterOpenAI:
    def test_converter_tool_para_openai(self, db, agente_teste):
        c = MCPService.criar(db, MCPClientCriar(
            agente_id=agente_teste.id, nome="meu_mcp",
            transport_type="stdio", command="x",
        ))
        tool = MCPTool(
            mcp_client_id=c.id,
            name="search",
            description="Pesquisa algo",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        )
        db.add(tool); db.commit(); db.refresh(tool)

        schema = MCPService.converter_mcp_tool_para_openai(c, tool)
        assert schema["type"] == "function"
        assert schema["function"]["name"] == f"mcp_{c.id}_search"
        assert "meu_mcp" in schema["function"]["description"]
        assert schema["function"]["parameters"]["properties"]["q"]["type"] == "string"

    def test_listar_tools_ativas(self, db, agente_teste):
        c = MCPService.criar(db, MCPClientCriar(
            agente_id=agente_teste.id, nome="x", transport_type="stdio",
            command="y",
        ))
        ativa = MCPTool(mcp_client_id=c.id, name="a", description="d",
                        input_schema={}, ativa=True)
        inativa = MCPTool(mcp_client_id=c.id, name="b", description="d",
                          input_schema={}, ativa=False)
        db.add_all([ativa, inativa]); db.commit()

        tools = MCPService.listar_tools_ativas(db, c.id)
        nomes = [t.name for t in tools]
        assert "a" in nomes
        assert "b" not in nomes
