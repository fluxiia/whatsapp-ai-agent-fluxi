"""
Testes funcionais para RAGService, RAGMetricaService e RAGCustomService.

Notas: testes evitam chamadas reais a APIs de embeddings — RAGCustomService só
é testado via método puro `_create_chunks`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from rag.rag_service import RAGService
from rag.rag_schema import RAGCriar, RAGAtualizar
from rag.rag_metrica_service import RAGMetricaService


# ═══════════════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestRAGCrud:
    def test_criar_rag(self, db):
        r = RAGService.criar(db, RAGCriar(
            nome="rag_test_crud",
            descricao="x",
            provider="openai",
            api_key_embed="sk-fake",
        ))
        assert r.id is not None
        assert r.nome == "rag_test_crud"
        assert r.treinado is False

    def test_criar_rag_duplicado(self, db):
        RAGService.criar(db, RAGCriar(nome="dup_rag"))
        with pytest.raises(ValueError):
            RAGService.criar(db, RAGCriar(nome="dup_rag"))

    def test_listar_todos(self, db):
        RAGService.criar(db, RAGCriar(nome="rag_l1"))
        RAGService.criar(db, RAGCriar(nome="rag_l2"))
        todos = RAGService.listar_todos(db)
        nomes = [r.nome for r in todos]
        assert "rag_l1" in nomes
        assert "rag_l2" in nomes

    def test_listar_ativos(self, db):
        a = RAGService.criar(db, RAGCriar(nome="ativ_1"))
        i = RAGService.criar(db, RAGCriar(nome="inat_1", ativo=False))
        ativos = RAGService.listar_ativos(db)
        ids = [r.id for r in ativos]
        assert a.id in ids
        assert i.id not in ids

    def test_obter_por_id_inexistente(self, db):
        assert RAGService.obter_por_id(db, 99999) is None

    def test_obter_por_nome(self, db):
        r = RAGService.criar(db, RAGCriar(nome="por_nome"))
        assert RAGService.obter_por_nome(db, "por_nome").id == r.id

    def test_atualizar(self, db):
        r = RAGService.criar(db, RAGCriar(nome="atualizar_rag"))
        a = RAGService.atualizar(db, r.id, RAGAtualizar(descricao="nova", top_k=5))
        assert a.descricao == "nova"
        assert a.top_k == 5

    def test_atualizar_inexistente(self, db):
        assert RAGService.atualizar(db, 999, RAGAtualizar(descricao="x")) is None

    def test_atualizar_nome_para_existente(self, db):
        r1 = RAGService.criar(db, RAGCriar(nome="rag_a"))
        r2 = RAGService.criar(db, RAGCriar(nome="rag_b"))
        with pytest.raises(ValueError):
            RAGService.atualizar(db, r2.id, RAGAtualizar(nome="rag_a"))

    def test_deletar(self, db):
        r = RAGService.criar(db, RAGCriar(nome="deletar_rag"))
        rid = r.id
        assert RAGService.deletar(db, rid) is True
        assert RAGService.obter_por_id(db, rid) is None

    def test_deletar_inexistente(self, db):
        assert RAGService.deletar(db, 9999) is False

    def test_buscar_em_rag_nao_treinado(self, db):
        r = RAGService.criar(db, RAGCriar(nome="nao_treinado"))
        with pytest.raises(ValueError):
            RAGService.buscar(db, r.id, "qualquer")

    def test_buscar_em_rag_inexistente(self, db):
        with pytest.raises(ValueError):
            RAGService.buscar(db, 999, "qualquer")


# ═══════════════════════════════════════════════════════════════════════════
# RAGCustomService — testar apenas chunking (não exige API/dependências de rede)
# ═══════════════════════════════════════════════════════════════════════════

class TestChunking:
    @pytest.fixture
    def rag_service_obj(self, tmp_path):
        """Cria instância de RAGCustomService apenas para chunking — pula init ChromaDB."""
        from rag.rag_custom_service import RAGCustomService

        # Subclasse que pula ChromaDB
        class FakeRAG(RAGCustomService):
            def _init_chromadb(self):
                self.collection = None

        return FakeRAG(rag_id=999, storage_path=str(tmp_path), api_key="fake")

    def test_chunks_simples(self, rag_service_obj):
        texto = "palavra " * 100  # ~800 chars
        chunks = rag_service_obj._create_chunks(texto, chunk_size=100, chunk_overlap=20)
        assert len(chunks) > 1
        for c in chunks:
            assert "text" in c
            assert "id" in c
            assert len(c["text"]) <= 100

    def test_chunks_texto_pequeno(self, rag_service_obj):
        chunks = rag_service_obj._create_chunks("oi", chunk_size=1000)
        assert len(chunks) == 1
        assert chunks[0]["text"] == "oi"

    def test_chunks_overlap(self, rag_service_obj):
        # Texto longo para garantir múltiplos chunks com overlap
        texto = " ".join(f"w{i}" for i in range(200))
        chunks = rag_service_obj._create_chunks(texto, chunk_size=80, chunk_overlap=20)
        assert len(chunks) >= 2

    def test_chunks_ids_unicos(self, rag_service_obj):
        texto = "palavra " * 50
        chunks = rag_service_obj._create_chunks(texto, chunk_size=50, chunk_overlap=10)
        ids = [c["id"] for c in chunks]
        assert len(ids) == len(set(ids))


# ═══════════════════════════════════════════════════════════════════════════
# RAGMetricaService
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def rag_simples(db):
    return RAGService.criar(db, RAGCriar(nome="rag_metricas"))


class TestMetricaService:
    def test_registrar_busca(self, db, rag_simples):
        m = RAGMetricaService.registrar_busca(
            db=db, rag_id=rag_simples.id,
            query="o que é fluxi?",
            resultados=[{"text": "..."}, {"text": "..."}],
            num_solicitados=3,
            tempo_ms=120,
        )
        assert m is not None
        assert m.num_resultados_retornados == 2
        assert m.tempo_ms == 120

    def test_listar_por_rag(self, db, rag_simples):
        for i in range(3):
            RAGMetricaService.registrar_busca(
                db=db, rag_id=rag_simples.id, query=f"q{i}",
                resultados=[], num_solicitados=1, tempo_ms=10
            )
        metricas = RAGMetricaService.listar_por_rag(db, rag_simples.id)
        assert len(metricas) == 3

    def test_listar_por_agente(self, db, rag_simples, agente_teste):
        RAGMetricaService.registrar_busca(
            db=db, rag_id=rag_simples.id, query="x",
            resultados=[], num_solicitados=1, tempo_ms=5, agente_id=agente_teste.id
        )
        ms = RAGMetricaService.listar_por_agente(db, agente_teste.id)
        assert len(ms) == 1

    def test_listar_por_sessao(self, db, rag_simples, sessao_teste):
        RAGMetricaService.registrar_busca(
            db=db, rag_id=rag_simples.id, query="x",
            resultados=[], num_solicitados=1, tempo_ms=5, sessao_id=sessao_teste.id
        )
        ms = RAGMetricaService.listar_por_sessao(db, sessao_teste.id)
        assert len(ms) == 1

    def test_estatisticas_sem_dados(self, db, rag_simples):
        stats = RAGMetricaService.obter_estatisticas_rag(db, rag_simples.id)
        assert stats["total_buscas"] == 0
        assert stats["tempo_medio_ms"] == 0

    def test_estatisticas_com_dados(self, db, rag_simples):
        for tempo in [100, 200, 300]:
            RAGMetricaService.registrar_busca(
                db=db, rag_id=rag_simples.id, query="igual",
                resultados=[{"x": 1}], num_solicitados=1, tempo_ms=tempo
            )
        stats = RAGMetricaService.obter_estatisticas_rag(db, rag_simples.id)
        assert stats["total_buscas"] == 3
        assert stats["tempo_medio_ms"] == 200
        assert stats["tempo_minimo_ms"] == 100
        assert stats["tempo_maximo_ms"] == 300
        assert stats["queries_unicas"] == 1

    def test_queries_mais_frequentes(self, db, rag_simples):
        for _ in range(3):
            RAGMetricaService.registrar_busca(
                db=db, rag_id=rag_simples.id, query="comum",
                resultados=[], num_solicitados=1, tempo_ms=10
            )
        RAGMetricaService.registrar_busca(
            db=db, rag_id=rag_simples.id, query="rara",
            resultados=[], num_solicitados=1, tempo_ms=10
        )
        top = RAGMetricaService.obter_queries_mais_frequentes(db, rag_simples.id)
        assert top[0]["query"] == "comum"
        assert top[0]["frequencia"] == 3

    def test_deletar_metricas_antigas(self, db, rag_simples):
        m_antiga = RAGMetricaService.registrar_busca(
            db=db, rag_id=rag_simples.id, query="antiga",
            resultados=[], num_solicitados=1, tempo_ms=1
        )
        m_antiga.criado_em = datetime.now() - timedelta(days=120)
        db.commit()

        RAGMetricaService.registrar_busca(
            db=db, rag_id=rag_simples.id, query="nova",
            resultados=[], num_solicitados=1, tempo_ms=1
        )

        deletadas = RAGMetricaService.deletar_metricas_antigas(db, dias=90)
        assert deletadas == 1
        assert len(RAGMetricaService.listar_por_rag(db, rag_simples.id)) == 1
