"""
Configuração global do pytest para o projeto Fluxi.

Garante que TODOS os testes rodam contra um SQLite em arquivo temporário
isolado do banco de produção (fluxi.db). Define DATABASE_URL ANTES de qualquer
import de `database` ou de modelos para que `database.engine` seja criado
apontando para o banco temporário.
"""
from __future__ import annotations

import os
import sys
import tempfile

# 1) Adiciona o root do projeto ao path para imports sem instalação
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 2) Aponta DATABASE_URL para um arquivo temporário (SQLite em :memory: não
#    suporta múltiplas conexões abertas em paralelo, o que quebraria o
#    SessionLocal/engine compartilhado).
_TMP_DIR = tempfile.mkdtemp(prefix="fluxi_test_")
_DB_PATH = os.path.join(_TMP_DIR, "fluxi_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.setdefault("SESSION_SECRET_KEY", "test-secret-key-not-for-prod")

# 3) Agora pode importar pytest + database + modelos com segurança
import pytest  # noqa: E402

import database  # noqa: E402

# Importar TODOS os modelos para que Base.metadata.create_all crie as tabelas.
# Esses imports têm side effects: registram as classes em Base.metadata.
import config.config_model  # noqa: E402, F401
import sessao.sessao_model  # noqa: E402, F401
import sessao.sessao_comando_model  # noqa: E402, F401
import sessao.sessao_tipo_mensagem_model  # noqa: E402, F401
import agente.agente_model  # noqa: E402, F401
import ferramenta.ferramenta_model  # noqa: E402, F401
import ferramenta.ferramenta_variavel_model  # noqa: E402, F401
import mensagem.mensagem_model  # noqa: E402, F401
import rag.rag_model  # noqa: E402, F401
import rag.rag_metrica_model  # noqa: E402, F401
import mcp_client.mcp_client_model  # noqa: E402, F401
import mcp_client.mcp_tool_model  # noqa: E402, F401
import llm_providers.llm_providers_model  # noqa: E402, F401
import skill.skill_model  # noqa: E402, F401
import coding_agent.coding_model  # noqa: E402, F401
import log.log_model  # noqa: E402, F401
import agendamento.agendamento_model  # noqa: E402, F401
import auth.auth_model  # noqa: E402, F401


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async (pytest-asyncio)"
    )


@pytest.fixture(scope="session", autouse=True)
def _criar_tabelas_uma_vez():
    """Cria todas as tabelas no banco de teste uma única vez por sessão de testes.

    O drop_all final é defensivo (silencia erros de dependência cíclica em SQLite)
    porque o banco temporário é descartado junto com o diretório no fim do processo.
    """
    database.Base.metadata.create_all(bind=database.engine)
    yield
    try:
        database.Base.metadata.drop_all(bind=database.engine)
    except Exception:
        pass


@pytest.fixture
def db():
    """
    Sessão SQLAlchemy isolada por teste: tudo é rolled-back ao final,
    deixando o banco limpo para o próximo teste.

    Usa o padrão "savepoint per test": cria conexão, inicia transação externa,
    associa Session a essa conexão e fecha tudo no teardown. Isso evita que
    commits em código de produção persistam dados entre testes.
    """
    connection = database.engine.connect()
    transaction = connection.begin()
    SessionLocal = database.sessionmaker(
        autocommit=False, autoflush=False, bind=connection
    )
    session = SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db, monkeypatch):
    """
    TestClient FastAPI com o `get_db` sobrescrito para usar a fixture `db`,
    e bypass do AuthMiddleware (rotas privadas exigem login normalmente).
    """
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret-key-not-for-prod")

    from fastapi.testclient import TestClient

    import main as main_module

    def _override_get_db():
        yield db

    # Desativa o AuthMiddleware para testes — substitui dispatch por passthrough
    from auth import auth_dependencies as auth_deps
    original_dispatch = auth_deps.AuthMiddleware.dispatch

    async def _passthrough(self, request, call_next):
        # injeta um user_id fictício na sessão para não quebrar Depends
        try:
            request.scope.setdefault("session", {})
            request.session["user_id"] = 1
        except Exception:
            pass
        return await call_next(request)

    monkeypatch.setattr(auth_deps.AuthMiddleware, "dispatch", _passthrough)

    main_module.app.dependency_overrides[database.get_db] = _override_get_db
    with TestClient(main_module.app) as c:
        yield c
    main_module.app.dependency_overrides.clear()


@pytest.fixture
def sessao_teste(db):
    """Cria uma Sessao de teste persistida e retorna o objeto."""
    from sessao.sessao_model import Sessao

    s = Sessao(
        nome="sessao_teste",
        plataforma="whatsapp",
        status="desconectado",
        ativa=True,
        auto_responder=True,
        salvar_historico=True,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture
def agente_teste(db, sessao_teste):
    """Cria um Agente de teste vinculado a uma sessão."""
    from agente.agente_model import Agente

    a = Agente(
        sessao_id=sessao_teste.id,
        codigo="01",
        nome="AgenteTeste",
        descricao="Agente para testes",
        agente_papel="Você é um assistente de teste",
        agente_objetivo="Responder às perguntas dos testes",
        agente_politicas="Seja conciso",
        agente_tarefa="Auxiliar nos testes",
        agente_objetivo_explicito="Validar comportamento",
        agente_publico="Desenvolvedores",
        agente_restricoes="Não invente dados",
        ativo=True,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@pytest.fixture
def ferramenta_teste(db):
    """Cria uma Ferramenta CODE de teste."""
    from ferramenta.ferramenta_model import Ferramenta, ToolType, ToolScope, OutputDestination

    f = Ferramenta(
        nome="ferramenta_teste",
        descricao="Ferramenta de teste",
        tool_type=ToolType.CODE,
        tool_scope=ToolScope.PRINCIPAL,
        codigo_python="resultado = {'ok': True, 'echo': argumentos.get('texto', '')}",
        output=OutputDestination.LLM,
        ativa=True,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f
