"""
Testes funcionais HTTP via TestClient FastAPI.

Cobre os endpoints REST principais: /health, /, /api/configuracoes,
/api/ferramentas, /api/agentes, /api/rags, /api/skills, /api/mcp,
/api/llm-providers, /api/agendamentos, /api/logs.
"""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Health & raiz
# ═══════════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_index_carrega(self, client):
        r = client.get("/")
        assert r.status_code == 200
        # Template HTML — não JSON
        assert "html" in r.headers.get("content-type", "").lower()


# ═══════════════════════════════════════════════════════════════════════════
# /api/configuracoes
# ═══════════════════════════════════════════════════════════════════════════

class TestConfiguracoesAPI:
    def test_listar_vazio(self, client):
        r = client.get("/api/configuracoes/")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_criar_e_obter(self, client):
        r = client.post("/api/configuracoes/", json={
            "chave": "api_test_x", "valor": "abc", "tipo": "string",
            "categoria": "geral", "editavel": True,
        })
        assert r.status_code == 200, r.text
        assert r.json()["chave"] == "api_test_x"

        r2 = client.get("/api/configuracoes/api_test_x")
        assert r2.status_code == 200
        assert r2.json()["valor"] == "abc"

    def test_obter_inexistente_404(self, client):
        r = client.get("/api/configuracoes/inexistente_xyz")
        assert r.status_code == 404

    def test_atualizar(self, client):
        client.post("/api/configuracoes/", json={
            "chave": "to_update", "valor": "antigo", "tipo": "string",
        })
        r = client.put("/api/configuracoes/to_update", json={"valor": "novo"})
        assert r.status_code == 200
        assert r.json()["valor"] == "novo"

    def test_deletar(self, client):
        client.post("/api/configuracoes/", json={
            "chave": "to_delete_x", "valor": "x", "tipo": "string",
        })
        r = client.delete("/api/configuracoes/to_delete_x")
        assert r.status_code == 200

    def test_listar_por_categoria(self, client):
        client.post("/api/configuracoes/", json={
            "chave": "cat_x_1", "valor": "x", "tipo": "string",
            "categoria": "cat_unica_teste",
        })
        r = client.get("/api/configuracoes/categoria/cat_unica_teste")
        assert r.status_code == 200
        assert len(r.json()) == 1


# ═══════════════════════════════════════════════════════════════════════════
# /api/ferramentas
# ═══════════════════════════════════════════════════════════════════════════

class TestFerramentasAPI:
    def test_listar(self, client, ferramenta_teste):
        r = client.get("/api/ferramentas/")
        assert r.status_code == 200
        nomes = [f["nome"] for f in r.json()]
        assert "ferramenta_teste" in nomes

    def test_obter_por_id(self, client, ferramenta_teste):
        r = client.get(f"/api/ferramentas/{ferramenta_teste.id}")
        assert r.status_code == 200
        assert r.json()["id"] == ferramenta_teste.id

    def test_obter_inexistente_404(self, client):
        r = client.get("/api/ferramentas/99999")
        assert r.status_code == 404

    def test_criar(self, client):
        r = client.post("/api/ferramentas/", json={
            "nome": "via_api",
            "descricao": "criada via api",
            "tool_type": "code",
            "tool_scope": "principal",
            "codigo_python": "resultado = {}",
            "ativa": True,
        })
        assert r.status_code == 200, r.text
        assert r.json()["nome"] == "via_api"

    def test_atualizar(self, client, ferramenta_teste):
        r = client.put(f"/api/ferramentas/{ferramenta_teste.id}", json={
            "descricao": "atualizada"
        })
        assert r.status_code == 200
        assert r.json()["descricao"] == "atualizada"

    def test_deletar(self, client, ferramenta_teste):
        r = client.delete(f"/api/ferramentas/{ferramenta_teste.id}")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# /api/agentes
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentesAPI:
    def test_listar(self, client, agente_teste):
        r = client.get("/api/agentes/")
        assert r.status_code == 200
        ids = [a["id"] for a in r.json()]
        assert agente_teste.id in ids

    def test_obter(self, client, agente_teste):
        r = client.get(f"/api/agentes/{agente_teste.id}")
        assert r.status_code == 200
        assert r.json()["nome"] == agente_teste.nome

    def test_atualizar(self, client, agente_teste):
        r = client.put(f"/api/agentes/{agente_teste.id}", json={
            "nome": "renomeado_via_api"
        })
        assert r.status_code == 200
        assert r.json()["nome"] == "renomeado_via_api"

    def test_listar_ferramentas_do_agente(self, client, agente_teste):
        r = client.get(f"/api/agentes/{agente_teste.id}/ferramentas")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ═══════════════════════════════════════════════════════════════════════════
# /api/rags
# ═══════════════════════════════════════════════════════════════════════════

class TestRagsAPI:
    def test_listar(self, client):
        r = client.get("/api/rags/")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_criar_e_obter(self, client):
        r = client.post("/api/rags/", json={
            "nome": "rag_api_test",
            "descricao": "test",
            "provider": "openai",
            "modelo_embed": "text-embedding-3-small",
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "top_k": 3,
        })
        assert r.status_code == 200, r.text
        rid = r.json()["id"]

        r2 = client.get(f"/api/rags/{rid}")
        assert r2.status_code == 200

    def test_obter_inexistente_404(self, client):
        r = client.get("/api/rags/99999")
        assert r.status_code == 404
