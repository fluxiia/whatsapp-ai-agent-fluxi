"""
Fluxi - Seu Assistente Pessoal WhatsApp
Aplicação principal FastAPI
"""
import os
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

# Importar configuração de logging
import logging_config

# Importar database
from database import criar_tabelas, get_db

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

# Adicionar middleware de sessão para o wizard
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "fluxi-secret-key-change-in-production-2024"),
    max_age=3600,  # 1 hora
    same_site="lax",  # Permite cookies em redirects
    https_only=False  # Para desenvolvimento local
)

# Templates
templates = Jinja2Templates(directory="templates")

# Criar diretórios necessários
os.makedirs("uploads", exist_ok=True)
os.makedirs("sessoes", exist_ok=True)
os.makedirs("rags", exist_ok=True)
os.makedirs("static", exist_ok=True)

# Montar arquivos estáticos (CSS, JS, imagens)
app.mount("/static", StaticFiles(directory="static"), name="static")


# Evento de inicialização
@app.on_event("startup")
def startup_event():
    """Inicializa o banco de dados e configurações padrão."""
    print("🚀 Iniciando Fluxi...")
    
    # Criar tabelas
    criar_tabelas()
    print("✅ Tabelas criadas")
    
    # Migração: adicionar colunas sandbox_ativo e sandbox_url se não existirem
    from sqlalchemy import inspect, text
    from database import engine
    insp = inspect(engine)
    colunas_agentes = [c["name"] for c in insp.get_columns("agentes")]
    with engine.connect() as conn:
        if "sandbox_ativo" not in colunas_agentes:
            conn.execute(text("ALTER TABLE agentes ADD COLUMN sandbox_ativo BOOLEAN DEFAULT 0"))
            conn.commit()
            print("✅ Migração: coluna sandbox_ativo adicionada")
        if "sandbox_url" not in colunas_agentes:
            conn.execute(text("ALTER TABLE agentes ADD COLUMN sandbox_url VARCHAR(255)"))
            conn.commit()
            print("✅ Migração: coluna sandbox_url adicionada")
    
    # Obter sessão do banco
    from database import SessionLocal
    db = SessionLocal()
    
    try:
        # Inicializar configurações padrão
        ConfiguracaoService.inicializar_configuracoes_padrao(db)
        print("✅ Configurações padrão inicializadas")
        
        # Inicializar ferramentas padrão
        FerramentaService.criar_ferramentas_padrao(db)
        print("✅ Ferramentas padrão criadas")
        
        # Reconectar sessões que estavam conectadas
        print("🔄 Reconectando sessões ativas...")
        sessoes_ativas = SessaoService.listar_todas(db, apenas_ativas=True)
        sessoes_reconectadas = 0
        
        for sessao in sessoes_ativas:
            # Só reconectar se estava conectado antes
            if sessao.status == "conectado":
                try:
                    print(f"🔌 Reconectando sessão: {sessao.nome}")
                    # Usar usar_paircode=False para não gerar novo QR
                    SessaoService.reconectar_sessao(db, sessao.id)
                    sessoes_reconectadas += 1
                except Exception as e:
                    print(f"⚠️  Erro ao reconectar {sessao.nome}: {e}")
        
        if sessoes_reconectadas > 0:
            print(f"✅ {sessoes_reconectadas} sessão(ões) reconectada(s)")
        
        print("✅ Fluxi iniciado com sucesso!")
        print("📱 Acesse: http://localhost:8000")
    finally:
        db.close()


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


@app.get("/sw-cliente.js")
def service_worker():
    return FileResponse("static/sw-cliente.js", media_type="application/javascript")


# Rota principal
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    """Página inicial - Dashboard."""
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
