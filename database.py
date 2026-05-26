"""
Configuração do banco de dados SQLAlchemy.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# URL do banco de dados
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fluxi.db")

_IS_SQLITE = "sqlite" in DATABASE_URL

# Criar engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _IS_SQLITE else {},
    echo=False
)


if _IS_SQLITE:
    # PRAGMAs aplicados em toda nova conexão. WAL libera leituras concorrentes
    # com a escrita do scheduler/neonize; synchronous=NORMAL é seguro com WAL
    # e ~3x mais rápido que FULL; busy_timeout evita SQLITE_BUSY em contenção;
    # cache_size negativo = KB (aqui ~40MB); foreign_keys=ON garante ON DELETE CASCADE.
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA cache_size=-40000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

# Session local
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para os modelos
Base = declarative_base()


def get_db():
    """
    Dependency para obter sessão do banco de dados.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def criar_tabelas():
    """
    Cria todas as tabelas no banco de dados.
    Executa migrações incrementais para colunas novas.
    """
    # Garante que os models novos foram importados antes do create_all.
    # Sem isto, Base.metadata nao conhece a tabela e ela nao eh criada.
    from midia import midia_model  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Migrações incrementais para colunas novas em tabelas existentes
    with engine.connect() as conn:
        # Agente: provedor_llm_id
        try:
            conn.execute(
                __import__('sqlalchemy').text(
                    "ALTER TABLE agentes ADD COLUMN provedor_llm_id INTEGER"
                )
            )
            conn.commit()
        except Exception:
            pass  # Coluna ja existe

        # Agente: frequency_penalty
        try:
            conn.execute(
                __import__('sqlalchemy').text(
                    "ALTER TABLE agentes ADD COLUMN frequency_penalty FLOAT"
                )
            )
            conn.commit()
        except Exception:
            pass

        # Agente: presence_penalty
        try:
            conn.execute(
                __import__('sqlalchemy').text(
                    "ALTER TABLE agentes ADD COLUMN presence_penalty FLOAT"
                )
            )
            conn.commit()
        except Exception:
            pass

        # Mensagem: media_id — FK leve pra tabela midias (string, sem constraint).
        # Mantemos `conteudo_imagem_path` por compat — `media_id` eh o caminho novo.
        try:
            conn.execute(
                __import__('sqlalchemy').text(
                    "ALTER TABLE mensagens ADD COLUMN media_id VARCHAR(120)"
                )
            )
            conn.commit()
        except Exception:
            pass
