"""
Fluxi - Seu Assistente Pessoal WhatsApp
Aplicação principal FastAPI
"""
import os
import secrets
import logging
import sys
import asyncio

from dotenv import load_dotenv
load_dotenv()

# Configuração de subprocessos no Windows para asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

logger = logging.getLogger(__name__)

# Importar configuração de logging
import logging_config

# Importar database
from database import criar_tabelas, get_db

# Importar skill_model antes de criar_tabelas para registrar no Base.metadata
import skill.skill_model  # noqa: F401

# Importar coding_model antes de criar_tabelas para registrar no Base.metadata
import coding_agent.coding_model  # noqa: F401

# Importar log_model antes de criar_tabelas para registrar no Base.metadata
import log.log_model  # noqa: F401

# Importar agendamento_model antes de criar_tabelas para registrar no Base.metadata
import agendamento.agendamento_model  # noqa: F401

# Importar auth_model antes de criar_tabelas para registrar no Base.metadata
import auth.auth_model  # noqa: F401

# Importar routers API
from config.config_router import router as config_api_router
from sessao.sessao_router import router as sessao_api_router
from mensagem.mensagem_router import router as mensagem_api_router
from ferramenta.ferramenta_router import router as ferramenta_api_router
from agente.agente_router import router as agente_api_router
from metrica.metrica_router import router as metrica_api_router
from rag.rag_router import router as rag_api_router
from mcp_client.mcp_router import router as mcp_api_router
from llm_providers.llm_providers_router import router as llm_providers_api_router
from agendamento.agendamento_router import router as agendamento_api_router

# Importar routers Frontend
from config.config_frontend_router import router as config_frontend_router
from sessao.sessao_frontend_router import router as sessao_frontend_router
from mensagem.mensagem_frontend_router import router as mensagem_frontend_router
from ferramenta.ferramenta_frontend_router import router as ferramenta_frontend_router
from ferramenta.ferramenta_wizard_router import router as ferramenta_wizard_router
from agente.agente_frontend_router import router as agente_frontend_router
from metrica.metrica_frontend_router import router as metrica_frontend_router
from rag.rag_frontend_router import router as rag_frontend_router
from mcp_client.mcp_frontend_router import router as mcp_frontend_router
from llm_providers.llm_providers_frontend_router import router as llm_providers_frontend_router
from agendamento.agendamento_frontend_router import router as agendamento_frontend_router
from skill.skill_router import router as skill_api_router
from skill.skill_frontend_router import router as skill_frontend_router
from internal_sandbox.frontend_router import router as internal_sandbox_frontend_router
from internal_sandbox.ws_router import router as internal_sandbox_ws_router
from coding_agent.coding_router import router as coding_api_router
from coding_agent.coding_ws_router import router as coding_ws_router
from coding_agent.coding_frontend_router import router as coding_frontend_router
from webchat.webchat_router import router as webchat_router
from auth.auth_frontend_router import router as auth_frontend_router
from auth.auth_dependencies import AuthMiddleware

# Importar routers do sistema de logging
from log.log_router import router as log_api_router
from log.log_frontend_router import router as log_frontend_router

# Onboarding guiado
from onboarding.onboarding_router import router as onboarding_router

# Importar serviços para inicialização
from config.config_service import ConfiguracaoService
from ferramenta.ferramenta_service import FerramentaService
from metrica.metrica_service import MetricaService
from sessao.sessao_service import SessaoService

# Criar aplicação FastAPI
app = FastAPI(
    title="Fluxi - Assistente WhatsApp",
    description="Seu assistente pessoal WhatsApp com LLM",
    version="1.0.0"
)

# Chave de sessão: obrigatoriamente via env var; em dev gera uma aleatória e avisa
_session_secret = os.getenv("SESSION_SECRET_KEY")
if not _session_secret:
    _session_secret = secrets.token_urlsafe(32)
    logger.warning(
        "SESSION_SECRET_KEY não definida. Usando chave gerada aleatoriamente. "
        "Sessões serão invalidadas a cada reinício. Defina SESSION_SECRET_KEY no .env para produção."
    )

# Middleware de proteção de rotas (precisa rodar APÓS o SessionMiddleware, logo
# é registrado antes — Starlette aplica em ordem reversa).
app.add_middleware(AuthMiddleware)

# Adicionar middleware de sessão para o wizard
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    max_age=60 * 60 * 24 * 7,  # 1 semana — login persistente
    same_site="lax",  # Permite cookies em redirects
    https_only=False  # Para desenvolvimento local
)

# CORS - permite chamadas da mesma origem e de configurações explícitas
_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates
templates = Jinja2Templates(directory="templates")

# Criar diretórios necessários
os.makedirs("uploads", exist_ok=True)
os.makedirs("sessoes", exist_ok=True)
os.makedirs("rags", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("workspaces", exist_ok=True)
os.makedirs("logs", exist_ok=True)

# Montar arquivos estáticos (CSS, JS, imagens)
app.mount("/static", StaticFiles(directory="static"), name="static")


# Suprimir RuntimeError: Event loop is closed do Playwright (callbacks de limpeza benignos)
@app.on_event("startup")
async def configurar_asyncio_exception_handler():
    import asyncio

    loop = asyncio.get_running_loop()

    def _handler(loop, context):
        exc = context.get("exception")
        if isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
            return
        loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)

    # Captura o event loop do FastAPI para o MensagemService poder despachar
    # coding tasks da thread do neonize para o loop principal (performante).
    from mensagem.mensagem_service import MensagemService
    MensagemService.set_fastapi_loop(loop)


# Evento de inicialização
@app.on_event("startup")
def startup_event():
    """Inicializa o banco de dados e configurações padrão."""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    logger.info("Iniciando Fluxi...")

    # Criar tabelas
    criar_tabelas()
    logger.info("Tabelas criadas")

    # Migração: adicionar colunas que podem não existir em bancos antigos
    from sqlalchemy import inspect, text
    from database import engine
    insp = inspect(engine)
    colunas_agentes = [c["name"] for c in insp.get_columns("agentes")]
    with engine.connect() as conn:
        if "internal_sandbox_ativo" not in colunas_agentes:
            conn.execute(text("ALTER TABLE agentes ADD COLUMN internal_sandbox_ativo BOOLEAN DEFAULT 0"))
            conn.commit()
            logger.info("Migração: coluna internal_sandbox_ativo adicionada")
        if "is_coding_agent" not in colunas_agentes:
            conn.execute(text("ALTER TABLE agentes ADD COLUMN is_coding_agent BOOLEAN DEFAULT 0"))
            conn.commit()
            logger.info("Migração: coluna is_coding_agent adicionada")

    # Migração: criar tabelas de skills se não existirem
    tabelas_existentes = insp.get_table_names()
    if "skills" not in tabelas_existentes:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome VARCHAR(100) NOT NULL UNIQUE,
                    descricao VARCHAR(250) NOT NULL,
                    instrucao_completa TEXT NOT NULL,
                    script_codigo TEXT NULL,
                    script_parametros TEXT NULL,
                    ferramentas_ids TEXT NULL,
                    categoria VARCHAR(50) NOT NULL DEFAULT 'utilitário',
                    icone VARCHAR(20) NULL DEFAULT '🔧',
                    versao VARCHAR(10) NOT NULL DEFAULT '1.0',
                    ativa BOOLEAN NOT NULL DEFAULT 1,
                    criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                    atualizado_em DATETIME NULL
                )
            """))
            conn.commit()
        logger.info("Migração: tabela 'skills' criada")
    if "agente_skill" not in tabelas_existentes:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE agente_skill (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agente_id INTEGER NOT NULL REFERENCES agentes(id) ON DELETE CASCADE,
                    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                    posicao INTEGER NOT NULL DEFAULT 0,
                    ativa BOOLEAN NOT NULL DEFAULT 1,
                    UNIQUE(agente_id, skill_id)
                )
            """))
            conn.commit()
        logger.info("Migração: tabela 'agente_skill' criada")

    # Migração: tabelas do Coding Agent
    if "coding_sessions" not in tabelas_existentes:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE coding_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agente_id INTEGER NOT NULL UNIQUE REFERENCES agentes(id) ON DELETE CASCADE,
                    workspace_path VARCHAR(500) NOT NULL DEFAULT './workspaces/default',
                    workspace_mode VARCHAR(20) NOT NULL DEFAULT 'sandbox',
                    extra_read_paths TEXT NULL,
                    memory_content TEXT NULL,
                    routing_prefix VARCHAR(20) NOT NULL DEFAULT '#code',
                    modelo_coding VARCHAR(100) NULL,
                    max_iteracoes INTEGER NOT NULL DEFAULT 200,
                    timeout_shell_rapido INTEGER NOT NULL DEFAULT 30,
                    timeout_shell_background INTEGER NOT NULL DEFAULT 300,
                    ativa BOOLEAN NOT NULL DEFAULT 1,
                    criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                    atualizado_em DATETIME NULL
                )
            """))
            conn.commit()
        logger.info("Migração: tabela 'coding_sessions' criada")

    if "coding_tasks" not in tabelas_existentes:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE coding_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    coding_session_id INTEGER NOT NULL REFERENCES coding_sessions(id) ON DELETE CASCADE,
                    titulo VARCHAR(200) NOT NULL DEFAULT 'Tarefa',
                    objetivo TEXT NULL,
                    telefone_cliente VARCHAR(50) NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    messages TEXT NOT NULL DEFAULT '[]',
                    shell_sessions TEXT NOT NULL DEFAULT '{}',
                    artifacts TEXT NOT NULL DEFAULT '[]',
                    tokens_input_total INTEGER NOT NULL DEFAULT 0,
                    tokens_output_total INTEGER NOT NULL DEFAULT 0,
                    iteracoes INTEGER NOT NULL DEFAULT 0,
                    error TEXT NULL,
                    criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completado_em DATETIME NULL
                )
            """))
            conn.commit()
        logger.info("Migração: tabela 'coding_tasks' criada")

    # Migração: adicionar coluna thinking_mode em coding_sessions
    # (conn dos blocos acima já foi fechado — usar nova conexão)
    insp_cs = inspect(engine)
    if "coding_sessions" in insp_cs.get_table_names():
        with engine.connect() as conn:
            colunas_cs = [
                row[1]
                for row in conn.execute(text("PRAGMA table_info(coding_sessions)")).fetchall()
            ]
            if "thinking_mode" not in colunas_cs:
                conn.execute(
                    text(
                        "ALTER TABLE coding_sessions ADD COLUMN thinking_mode BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
                conn.commit()
                logger.info("Migração: coluna 'thinking_mode' adicionada a coding_sessions")

    # Migração: atualizar max_iteracoes de 30 (antigo default) para 200
    if "coding_sessions" in insp_cs.get_table_names():
        with engine.connect() as conn:
            conn.execute(text(
                "UPDATE coding_sessions SET max_iteracoes = 200 WHERE max_iteracoes = 30"
            ))
            conn.commit()

    # Migração: multi-canal (WhatsApp + Telegram).
    # Sessoes ganham plataforma/identificador/credenciais; Mensagens ganham
    # plataforma/chat_id/mensagem_id_externo. Backfill = 'whatsapp' copiando
    # dos campos antigos.
    insp_canal = inspect(engine)
    if "sessoes" in insp_canal.get_table_names():
        with engine.connect() as conn:
            colunas_sessoes = [
                row[1]
                for row in conn.execute(text("PRAGMA table_info(sessoes)")).fetchall()
            ]
            if "plataforma" not in colunas_sessoes:
                conn.execute(text(
                    "ALTER TABLE sessoes ADD COLUMN plataforma VARCHAR(20) NOT NULL DEFAULT 'whatsapp'"
                ))
                conn.commit()
                logger.info("Migração: coluna 'plataforma' adicionada a sessoes")
            if "identificador" not in colunas_sessoes:
                conn.execute(text("ALTER TABLE sessoes ADD COLUMN identificador VARCHAR(100)"))
                conn.execute(text(
                    "UPDATE sessoes SET identificador = telefone WHERE identificador IS NULL AND telefone IS NOT NULL"
                ))
                conn.commit()
                logger.info("Migração: coluna 'identificador' adicionada a sessoes (backfill de telefone)")
            if "credenciais" not in colunas_sessoes:
                conn.execute(text("ALTER TABLE sessoes ADD COLUMN credenciais TEXT"))
                conn.commit()
                logger.info("Migração: coluna 'credenciais' adicionada a sessoes")

    if "mensagens" in insp_canal.get_table_names():
        with engine.connect() as conn:
            colunas_mensagens = [
                row[1]
                for row in conn.execute(text("PRAGMA table_info(mensagens)")).fetchall()
            ]
            if "plataforma" not in colunas_mensagens:
                conn.execute(text(
                    "ALTER TABLE mensagens ADD COLUMN plataforma VARCHAR(20) NOT NULL DEFAULT 'whatsapp'"
                ))
                conn.commit()
                logger.info("Migração: coluna 'plataforma' adicionada a mensagens")
            if "chat_id" not in colunas_mensagens:
                conn.execute(text("ALTER TABLE mensagens ADD COLUMN chat_id VARCHAR(100)"))
                conn.execute(text(
                    "UPDATE mensagens SET chat_id = telefone_cliente WHERE chat_id IS NULL"
                ))
                conn.commit()
                logger.info("Migração: coluna 'chat_id' adicionada a mensagens (backfill de telefone_cliente)")
            if "mensagem_id_externo" not in colunas_mensagens:
                conn.execute(text("ALTER TABLE mensagens ADD COLUMN mensagem_id_externo VARCHAR(100)"))
                conn.execute(text(
                    "UPDATE mensagens SET mensagem_id_externo = mensagem_id_whatsapp WHERE mensagem_id_externo IS NULL"
                ))
                conn.commit()
                logger.info("Migração: coluna 'mensagem_id_externo' adicionada a mensagens (backfill de mensagem_id_whatsapp)")

    # Obter sessão do banco
    from database import SessionLocal
    db = SessionLocal()

    try:
        # Reset de senha via .env (FLUXI_ADMIN_RESET_EMAIL + FLUXI_ADMIN_RESET_PASSWORD).
        # Útil quando o único admin esquece a senha. Operador define as 2 envs,
        # reinicia o container, faz login e DEVE remover as envs do .env.
        try:
            from auth.auth_service import resetar_senha_via_env
            resetar_senha_via_env(db)
        except Exception as e:
            logger.warning("Erro ao processar reset de senha via env: %s", e)

        # Inicializar configurações padrão
        ConfiguracaoService.inicializar_configuracoes_padrao(db)
        logger.info("Configurações padrão inicializadas")

        # Inicializar ferramentas padrão
        FerramentaService.criar_ferramentas_padrao(db)
        logger.info("Ferramentas padrão criadas")

        # Inicializar skills padrão
        from skill.skill_service import SkillService
        SkillService.criar_skills_padrao(db)
        logger.info("Skills padrão criadas")

        # Ativar thinking_mode (reasoning tokens) em coding sessions existentes
        try:
            from coding_agent.coding_model import CodingSession as _CS
            _updated = db.query(_CS).filter(_CS.thinking_mode == False).update({"thinking_mode": True})
            if _updated:
                db.commit()
                logger.info("Reasoning tokens ativado em %d coding session(s)", _updated)
        except Exception as _e:
            logger.warning("Erro ao ativar thinking_mode: %s", _e)

        # Reconectar sessões que estavam conectadas
        logger.info("Reconectando sessões ativas...")
        sessoes_ativas = SessaoService.listar_todas(db, apenas_ativas=True)
        sessoes_reconectadas = 0

        for sessao in sessoes_ativas:
            # Só reconectar se estava conectado antes
            if sessao.status == "conectado":
                try:
                    logger.info("Reconectando sessão: %s", sessao.nome)
                    SessaoService.reconectar_sessao(db, sessao.id)
                    sessoes_reconectadas += 1
                except Exception as e:
                    logger.warning("Erro ao reconectar %s: %s", sessao.nome, e)

        if sessoes_reconectadas > 0:
            logger.info("%d sessão(ões) reconectada(s)", sessoes_reconectadas)

        # Limpeza de logs antigos (>30 dias)
        try:
            from log.log_service import LogService, fluxi_log
            deleted = LogService.limpar_antigos(db, dias=30)
            if deleted > 0:
                logger.info(f"Limpeza: {deleted} log entries antigos removidos")
            fluxi_log.info("sistema", None, "Fluxi iniciado com sucesso")
        except Exception as e_log:
            logger.warning(f"Erro na limpeza de logs: {e_log}")

        # Inicia o scheduler de tarefas agendadas (heartbeat / lembretes).
        # Roda aqui no fim do startup pra garantir que a tabela tarefas_agendadas
        # já foi criada por criar_tabelas() acima antes de _reagendar_pendentes() rodar.
        try:
            from agendamento.agendamento_service import AgendamentoService
            AgendamentoService.iniciar()
            logger.info("Scheduler de agendamentos iniciado")
        except Exception as e_sched:
            logger.warning(f"Erro ao iniciar scheduler de agendamentos: {e_sched}")

        logger.info("Fluxi iniciado com sucesso! Acesse: http://localhost:8000")
    finally:
        db.close()


@app.on_event("shutdown")
async def shutdown_event():
    """Encerramento da aplicação — para serviços em background."""
    try:
        from agendamento.agendamento_service import AgendamentoService
        AgendamentoService.parar()
    except Exception as e:
        logger.warning("Erro ao parar scheduler: %s", e)


# Registrar routers API
app.include_router(config_api_router)
app.include_router(sessao_api_router)
app.include_router(mensagem_api_router)
app.include_router(ferramenta_api_router)
app.include_router(agente_api_router)
app.include_router(metrica_api_router)
app.include_router(rag_api_router)
app.include_router(mcp_api_router)
app.include_router(llm_providers_api_router)
app.include_router(skill_api_router)
app.include_router(agendamento_api_router)

# Registrar routers Frontend
app.include_router(config_frontend_router)
app.include_router(sessao_frontend_router)
app.include_router(mensagem_frontend_router)
app.include_router(ferramenta_frontend_router)
app.include_router(ferramenta_wizard_router)  # Wizard de criação de ferramentas
app.include_router(agente_frontend_router)
app.include_router(metrica_frontend_router)
app.include_router(rag_frontend_router)
app.include_router(mcp_frontend_router)
app.include_router(llm_providers_frontend_router)
app.include_router(internal_sandbox_frontend_router)
app.include_router(internal_sandbox_ws_router)
app.include_router(skill_frontend_router)
app.include_router(coding_api_router)
app.include_router(coding_ws_router)
app.include_router(coding_frontend_router)
app.include_router(webchat_router)
app.include_router(auth_frontend_router)
app.include_router(agendamento_frontend_router)
app.include_router(onboarding_router)

# Registrar routers de Logging
app.include_router(log_api_router)
app.include_router(log_frontend_router)


@app.get("/health")
def health_check():
    """Health check para Docker e load balancers."""
    return JSONResponse({"status": "ok"})


@app.get("/sw-cliente.js")
def service_worker():
    return FileResponse("static/sw-cliente.js", media_type="application/javascript")


# Rota principal
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    """Página inicial - Dashboard.

    Redireciona pro onboarding se o sistema está virgem (sem sessões e sem
    provedores LLM cadastrados). Usuário sempre pode pular pelo botão da tela.
    """
    from onboarding.onboarding_service import sistema_ja_configurado
    if not sistema_ja_configurado(db):
        return RedirectResponse(url="/onboarding/", status_code=303)

    # Obter métricas gerais
    metricas = MetricaService.obter_metricas_gerais(db)

    # Obter sessões
    sessoes = SessaoService.listar_todas(db)

    # Verificar se API está configurada
    api_key = ConfiguracaoService.obter_valor(db, "openrouter_api_key")
    api_configurada = api_key is not None and api_key != ""

    return templates.TemplateResponse("index.html", {
        "request": request,
        "metricas": metricas,
        "sessoes": sessoes,
        "api_configurada": api_configurada,
        "titulo": "Dashboard"
    })

# Rota Exemplo Moderno
@app.get("/exemplo-moderno", response_class=HTMLResponse)
def exemplo_moderno(request: Request, db: Session = Depends(get_db)):
    """Demonstração da nova UI/UX baseada no modern.css."""
    metricas = MetricaService.obter_metricas_gerais(db)
    sessoes = SessaoService.listar_todas(db)
    return templates.TemplateResponse("exemplo_modern.html", {
        "request": request,
        "metricas": metricas,
        "sessoes": sessoes,
        "titulo": "Dashboard Moderno"
    })

# Rota Exemplo Wizard Agente
@app.get("/exemplo-moderno-agente", response_class=HTMLResponse)
def exemplo_moderno_agente(request: Request):
    """Demonstração da UX do construtor de Agentes."""
    return templates.TemplateResponse("exemplo_modern_agente.html", {
        "request": request,
        "titulo": "Criar Novo Agente"
    })


# Executar aplicação
if __name__ == "__main__":
    import uvicorn
    
    # Configurações do servidor
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    debug = os.getenv("DEBUG", "True").lower() == "true"
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info",
        reload_excludes=["sessoes/*", "*.db", "rags/*", "uploads/*", "*.log"] if debug else None
    )
