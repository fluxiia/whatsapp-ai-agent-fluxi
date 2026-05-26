"""
Rotas do frontend para agentes.
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
from agente.agente_service import AgenteService
from agente.agente_schema import AgenteCriar, AgenteAtualizar
from sessao.sessao_service import SessaoService
from ferramenta.ferramenta_service import FerramentaService
from config.config_service import ConfiguracaoService

router = APIRouter(prefix="/agentes", tags=["Frontend - Agentes"])
templates = Jinja2Templates(directory="templates")


@router.get("/sessao/{sessao_id}", response_class=HTMLResponse)
def pagina_agentes_sessao(sessao_id: int, request: Request, db: Session = Depends(get_db)):
    """Página de listagem de agentes de uma sessão."""
    sessao = SessaoService.obter_por_id(db, sessao_id)
    if not sessao:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": "Sessão não encontrada",
            "titulo": "Erro"
        })
    
    agentes = AgenteService.listar_por_sessao(db, sessao_id)

    from skill.skill_service import SkillService
    skills_por_agente = {a.id: len(SkillService.listar_skills_agente(db, a.id)) for a in agentes}

    return templates.TemplateResponse("agente/lista.html", {
        "request": request,
        "sessao": sessao,
        "agentes": agentes,
        "skills_por_agente": skills_por_agente,
        "titulo": f"Agentes - {sessao.nome}"
    })


@router.get("/sessao/{sessao_id}/novo", response_class=HTMLResponse)
def pagina_novo_agente(sessao_id: int, request: Request, db: Session = Depends(get_db)):
    """Página para criar novo agente."""
    sessao = SessaoService.obter_por_id(db, sessao_id)
    if not sessao:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": "Sessão não encontrada",
            "titulo": "Erro"
        })
    
    # Buscar configurações padrão
    config_agente = {
        "papel": ConfiguracaoService.obter_valor(db, "agente_papel_padrao", "assistente pessoal"),
        "objetivo": ConfiguracaoService.obter_valor(db, "agente_objetivo_padrao", "ajudar o usuário"),
        "politicas": ConfiguracaoService.obter_valor(db, "agente_politicas_padrao", "ser educado e prestativo"),
        "tarefa": ConfiguracaoService.obter_valor(db, "agente_tarefa_padrao", "responder perguntas"),
        "objetivo_explicito": ConfiguracaoService.obter_valor(db, "agente_objetivo_explicito_padrao", "fornecer informações úteis"),
        "publico": ConfiguracaoService.obter_valor(db, "agente_publico_padrao", "usuários em geral"),
        "restricoes": ConfiguracaoService.obter_valor(db, "agente_restricoes_padrao", "responder em português")
    }
    
    # Sugerir próximo código
    agentes_existentes = AgenteService.listar_por_sessao(db, sessao_id)
    proximo_codigo = str(len(agentes_existentes) + 1).zfill(2)
    
    return templates.TemplateResponse("agente/form.html", {
        "request": request,
        "sessao": sessao,
        "config_agente": config_agente,
        "proximo_codigo": proximo_codigo,
        "titulo": "Novo Agente",
        "acao": "criar"
    })


@router.get("/{agente_id}", response_class=HTMLResponse)
async def pagina_detalhes_agente(agente_id: int, request: Request, db: Session = Depends(get_db)):
    """Página unificada de edição do agente."""
    agente = AgenteService.obter_por_id(db, agente_id)
    if not agente:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": "Agente não encontrado",
            "titulo": "Erro"
        })

    sessao = SessaoService.obter_por_id(db, agente.sessao_id)
    todas_ferramentas = FerramentaService.listar_ferramentas_ativas(db)
    ferramentas_agente = AgenteService.listar_ferramentas(db, agente_id)
    ferramentas_agente_ids = [f.id for f in ferramentas_agente]

    from skill.skill_service import SkillService
    todas_skills = SkillService.listar_ativas(db)
    skills_agente = SkillService.listar_skills_agente(db, agente_id)
    ids_agente = {s.id for s in skills_agente}

    from rag.rag_service import RAGService
    rags_disponiveis = RAGService.listar_ativos(db)

    from config.config_service import ConfiguracaoService
    config_agente = {
        "papel": ConfiguracaoService.obter_valor(db, "agente_papel_padrao", "assistente pessoal"),
        "objetivo": ConfiguracaoService.obter_valor(db, "agente_objetivo_padrao", "ajudar o usuário"),
        "politicas": ConfiguracaoService.obter_valor(db, "agente_politicas_padrao", "ser educado e prestativo"),
        "tarefa": ConfiguracaoService.obter_valor(db, "agente_tarefa_padrao", "responder perguntas"),
        "objetivo_explicito": ConfiguracaoService.obter_valor(db, "agente_objetivo_explicito_padrao", "fornecer informações úteis"),
        "publico": ConfiguracaoService.obter_valor(db, "agente_publico_padrao", "usuários em geral"),
        "restricoes": ConfiguracaoService.obter_valor(db, "agente_restricoes_padrao", "responder em português")
    }

    # Dados LLM para a tab Configurações
    from llm_providers.llm_providers_service import ProvedorLLMService
    from llm_providers.llm_integration_service import LLMIntegrationService

    provedores_llm = ProvedorLLMService.listar_ativos(db)
    modelos_por_provedor = {}
    for p in provedores_llm:
        modelos = ProvedorLLMService.obter_modelos(db, p.id)
        modelos_por_provedor[p.id] = [
            {"id": m.modelo_id, "nome": m.nome, "contexto": m.contexto,
             "suporta_imagens": m.suporta_imagens, "suporta_ferramentas": m.suporta_ferramentas}
            for m in modelos
        ]

    openrouter_disponivel = bool(ConfiguracaoService.obter_valor(db, "openrouter_api_key"))
    openrouter_modelos = (await LLMIntegrationService.obter_modelos_disponiveis(db)).get("openrouter", []) if openrouter_disponivel else []

    config_llm_padrao = {
        "temperatura": ConfiguracaoService.obter_valor(db, "openrouter_temperatura", 0.7),
        "max_tokens": ConfiguracaoService.obter_valor(db, "openrouter_max_tokens", 2000),
        "top_p": ConfiguracaoService.obter_valor(db, "openrouter_top_p", 1.0),
        "frequency_penalty": ConfiguracaoService.obter_valor(db, "openrouter_frequency_penalty", 0.0),
        "presence_penalty": ConfiguracaoService.obter_valor(db, "openrouter_presence_penalty", 0.0),
        "modelo_padrao": ConfiguracaoService.obter_valor(db, "openrouter_modelo_padrao", "google/gemini-3.1-flash-lite-preview"),
    }

    return templates.TemplateResponse("agente/detalhes.html", {
        "request": request,
        "agente": agente,
        "sessao": sessao,
        "todas_ferramentas": todas_ferramentas,
        "ferramentas_agente_ids": ferramentas_agente_ids,
        "total_selecionadas": len(ferramentas_agente_ids),
        "todas_skills": todas_skills,
        "skills_agente": skills_agente,
        "ids_agente": ids_agente,
        "rags_disponiveis": rags_disponiveis,
        "config_agente": config_agente,
        "provedores_llm": provedores_llm,
        "modelos_por_provedor": modelos_por_provedor,
        "openrouter_disponivel": openrouter_disponivel,
        "openrouter_modelos": openrouter_modelos,
        "config_llm_padrao": config_llm_padrao,
        "titulo": f"{agente.nome}",
    })




@router.post("/sessao/{sessao_id}/criar")
def criar_agente(
    sessao_id: int,
    request: Request,
    codigo: str = Form(...),
    nome: str = Form(...),
    descricao: str = Form(""),
    agente_papel: str = Form(...),
    agente_objetivo: str = Form(...),
    agente_politicas: str = Form(...),
    agente_tarefa: str = Form(...),
    agente_objetivo_explicito: str = Form(...),
    agente_publico: str = Form(...),
    agente_restricoes: str = Form(...),
    modelo_llm: Optional[str] = Form(None),
    temperatura: Optional[str] = Form(None),
    max_tokens: Optional[str] = Form(None),
    top_p: Optional[str] = Form(None),
    # Checkbox HTML só é enviado quando marcado
    ativo: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Cria um novo agente."""
    ativo_bool = ativo is None or ativo.lower() in ("true", "on", "1", "yes")  # padrão True na criação
    try:
        agente_data = AgenteCriar(
            sessao_id=sessao_id,
            codigo=codigo,
            nome=nome,
            descricao=descricao,
            agente_papel=agente_papel,
            agente_objetivo=agente_objetivo,
            agente_politicas=agente_politicas,
            agente_tarefa=agente_tarefa,
            agente_objetivo_explicito=agente_objetivo_explicito,
            agente_publico=agente_publico,
            agente_restricoes=agente_restricoes,
            modelo_llm=modelo_llm if modelo_llm else None,
            temperatura=float(temperatura) if temperatura else None,
            max_tokens=int(max_tokens) if max_tokens else None,
            top_p=float(top_p) if top_p else None,
            ativo=ativo_bool
        )
        
        AgenteService.criar(db, agente_data)
        return RedirectResponse(url=f"/agentes/sessao/{sessao_id}", status_code=303)
    except ValueError as e:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": str(e),
            "titulo": "Erro ao criar agente"
        })


@router.post("/{agente_id}/atualizar")
def atualizar_agente(
    agente_id: int,
    request: Request,
    codigo: str = Form(...),
    nome: str = Form(...),
    descricao: str = Form(""),
    agente_papel: str = Form(...),
    agente_objetivo: str = Form(...),
    agente_politicas: str = Form(...),
    agente_tarefa: str = Form(...),
    agente_objetivo_explicito: str = Form(...),
    agente_publico: str = Form(...),
    agente_restricoes: str = Form(...),
    provedor_llm_id: Optional[str] = Form(None),
    modelo_llm: Optional[str] = Form(None),
    temperatura: Optional[str] = Form(None),
    max_tokens: Optional[str] = Form(None),
    top_p: Optional[str] = Form(None),
    frequency_penalty: Optional[str] = Form(None),
    presence_penalty: Optional[str] = Form(None),
    # Checkbox HTML só é enviado quando marcado — usamos Optional[str] para detectar ausência
    ativo: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Atualiza um agente."""
    agente = AgenteService.obter_por_id(db, agente_id)
    if not agente:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": "Agente não encontrado",
            "titulo": "Erro"
        })

    # Converte checkbox: presente → True, ausente → False
    ativo_bool = ativo is not None and ativo.lower() in ("true", "on", "1", "yes")

    try:
        agente_data = AgenteAtualizar(
            codigo=codigo,
            nome=nome,
            descricao=descricao,
            agente_papel=agente_papel,
            agente_objetivo=agente_objetivo,
            agente_politicas=agente_politicas,
            agente_tarefa=agente_tarefa,
            agente_objetivo_explicito=agente_objetivo_explicito,
            agente_publico=agente_publico,
            agente_restricoes=agente_restricoes,
            provedor_llm_id=int(provedor_llm_id) if provedor_llm_id else None,
            modelo_llm=modelo_llm if modelo_llm else None,
            temperatura=float(temperatura) if temperatura else None,
            max_tokens=int(max_tokens) if max_tokens else None,
            top_p=float(top_p) if top_p else None,
            frequency_penalty=float(frequency_penalty) if frequency_penalty else None,
            presence_penalty=float(presence_penalty) if presence_penalty else None,
            ativo=ativo_bool
        )

        AgenteService.atualizar(db, agente_id, agente_data)
        return RedirectResponse(url=f"/agentes/{agente_id}", status_code=303)
    except ValueError as e:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": str(e),
            "titulo": "Erro ao atualizar agente"
        })




@router.post("/{agente_id}/ferramentas/atualizar")
async def atualizar_ferramentas_agente(
    agente_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Atualiza as ferramentas do agente."""
    agente = AgenteService.obter_por_id(db, agente_id)
    if not agente:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": "Agente não encontrado",
            "titulo": "Erro"
        })
    
    # Obter ferramentas selecionadas do form
    form_data = await request.form()
    ferramentas_ids = []
    
    for key in form_data.keys():
        if key.startswith("ferramenta_"):
            ferramenta_id = int(key.replace("ferramenta_", ""))
            ferramentas_ids.append(ferramenta_id)
    
    try:
        AgenteService.atualizar_ferramentas(db, agente_id, ferramentas_ids)
        return RedirectResponse(url=f"/agentes/{agente_id}?tab=ferramentas", status_code=303)
    except ValueError as e:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": str(e),
            "titulo": "Erro ao atualizar ferramentas"
        })


@router.post("/{agente_id}/deletar")
def deletar_agente(agente_id: int, db: Session = Depends(get_db)):
    """Deleta um agente."""
    agente = AgenteService.obter_por_id(db, agente_id)
    if agente:
        sessao_id = agente.sessao_id
        AgenteService.deletar(db, agente_id)
        return RedirectResponse(url=f"/agentes/sessao/{sessao_id}", status_code=303)
    return RedirectResponse(url="/sessoes", status_code=303)


@router.post("/{agente_id}/ativar")
def ativar_agente(agente_id: int, db: Session = Depends(get_db)):
    """Define este agente como ativo na sessão."""
    agente = AgenteService.obter_por_id(db, agente_id)
    if agente:
        sessao = SessaoService.obter_por_id(db, agente.sessao_id)
        if sessao:
            from sessao.sessao_schema import SessaoAtualizar
            SessaoService.atualizar(db, sessao.id, SessaoAtualizar(agente_ativo_id=agente_id))
        return RedirectResponse(url=f"/agentes/sessao/{agente.sessao_id}", status_code=303)
    return RedirectResponse(url="/sessoes", status_code=303)
