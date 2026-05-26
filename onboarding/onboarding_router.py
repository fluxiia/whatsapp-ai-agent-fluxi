"""
Router do onboarding guiado.

Rotas do wizard de 5 passos. O estado vive em request.session['onboarding'],
mesmo padrao do wizard de ferramenta. Nao persiste em banco enquanto o
usuario nao confirmar cada passo.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from agente.agente_schema import AgenteCriar
from agente.agente_service import AgenteService
from canal.canal_base import Plataforma
from database import get_db
from llm_providers.llm_providers_model import ProvedorLLM, StatusProvedorEnum
from llm_providers.llm_providers_schema import ProvedorLLMCriar
from llm_providers.llm_providers_service import ProvedorLLMService
from log.log_service import fluxi_log
from onboarding import onboarding_service as svc
from sessao.sessao_schema import SessaoCriar
from sessao.sessao_service import SessaoService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])
templates = Jinja2Templates(directory="templates")


# ============================================================
# Passo 0 - Boas-vindas
# ============================================================


@router.get("/", response_class=HTMLResponse)
def pagina_welcome(request: Request, db: Session = Depends(get_db)):
    """Tela inicial de boas-vindas. Reinicia o estado a cada visita."""
    svc.limpar_estado(request)
    svc.salvar_estado(request, step=1)
    return templates.TemplateResponse(
        "onboarding/welcome.html",
        {
            "request": request,
            "titulo": "Bem-vindo ao Fluxi",
            "ja_configurado": svc.sistema_ja_configurado(db),
        },
    )


@router.post("/pular")
def pular_onboarding(request: Request):
    """Abandona o wizard e vai pro dashboard."""
    svc.limpar_estado(request)
    return RedirectResponse(url="/", status_code=303)


# ============================================================
# Passo 1 - Provedor LLM (cerebro)
# ============================================================


@router.get("/llm", response_class=HTMLResponse)
def pagina_llm(request: Request):
    estado = svc.obter_estado(request)
    svc.salvar_estado(request, step=1)
    return templates.TemplateResponse(
        "onboarding/llm.html",
        {
            "request": request,
            "estado": estado,
            "step_atual": 1,
            "titulo": "Configurar o cerebro (LLM)",
        },
    )


@router.get("/llm/detectar")
def api_detectar_llm():
    """Detecta LM Studio / Ollama rodando localmente. Usado no carregamento da pagina."""
    return JSONResponse({"provedores": svc.detectar_provedores_locais()})


@router.post("/llm/testar")
def api_testar_llm(
    base_url: str = Form(...),
    api_key: Optional[str] = Form(None),
):
    """Testa conexao com um provedor (GET /models). Retorna ok/mensagem/modelos."""
    resultado = svc.testar_conexao(base_url=base_url.strip(), api_key=(api_key or "").strip() or None)
    return JSONResponse(resultado)


@router.post("/llm/salvar")
def salvar_llm(
    request: Request,
    nome: str = Form(...),
    base_url: str = Form(...),
    api_key: Optional[str] = Form(None),
    descricao: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Cria o ProvedorLLM e avanca para o passo 2."""
    try:
        # Garante https/http
        url = base_url.strip()
        if not url.startswith(("http://", "https://")):
            url = "http://" + url

        provedor_data = ProvedorLLMCriar(
            nome=nome.strip() or "Provedor padrao",
            base_url=url,
            api_key=(api_key or "").strip() or None,
            descricao=(descricao or "").strip() or None,
            ativo=True,
        )
        provedor = ProvedorLLMService.criar(db, provedor_data)
        # Marca como ATIVO por padrao apos onboarding (status do enum).
        provedor.status = StatusProvedorEnum.ATIVO
        db.commit()

        svc.salvar_estado(request, provedor_id=provedor.id, step=2)
        fluxi_log.info("onboarding", "llm", "Provedor LLM criado", extra={"provedor_id": provedor.id})
        return RedirectResponse(url="/onboarding/canal", status_code=303)
    except Exception as e:
        fluxi_log.error("onboarding", "llm", f"Erro ao criar provedor: {e}", exc_info=True)
        return templates.TemplateResponse(
            "onboarding/llm.html",
            {
                "request": request,
                "estado": svc.obter_estado(request),
                "step_atual": 1,
                "erro": f"Nao consegui salvar o provedor: {e}",
                "form_nome": nome,
                "form_base_url": base_url,
                "form_api_key": api_key or "",
                "titulo": "Configurar o cerebro (LLM)",
            },
            status_code=400,
        )


# ============================================================
# Passo 2 - Canal (WhatsApp / Telegram / Webchat)
# ============================================================


@router.get("/canal", response_class=HTMLResponse)
def pagina_canal_escolher(request: Request):
    estado = svc.obter_estado(request)
    if not estado.get("provedor_id"):
        return RedirectResponse(url="/onboarding/llm", status_code=303)
    svc.salvar_estado(request, step=2)
    return templates.TemplateResponse(
        "onboarding/canal.html",
        {
            "request": request,
            "estado": estado,
            "step_atual": 2,
            "titulo": "Escolher canal",
        },
    )


@router.get("/canal/{canal}", response_class=HTMLResponse)
def pagina_canal_form(canal: str, request: Request):
    estado = svc.obter_estado(request)
    if not estado.get("provedor_id"):
        return RedirectResponse(url="/onboarding/llm", status_code=303)
    if canal not in ("whatsapp", "telegram", "webchat"):
        return RedirectResponse(url="/onboarding/canal", status_code=303)
    svc.salvar_estado(request, step=2, canal=canal)
    template_name = f"onboarding/canal_{canal}.html"
    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "estado": svc.obter_estado(request),
            "step_atual": 2,
            "canal": canal,
            "titulo": f"Conectar {canal.capitalize()}",
        },
    )


@router.post("/canal/criar")
def criar_canal(
    request: Request,
    canal: str = Form(...),
    nome: str = Form(...),
    telegram_bot_token: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Cria a Sessao no banco. Roteia pra subfluxo correto em seguida."""
    canal = canal.strip().lower()
    if canal not in ("whatsapp", "telegram", "webchat"):
        return RedirectResponse(url="/onboarding/canal", status_code=303)

    try:
        sessao_data = SessaoCriar(
            nome=nome.strip(),
            plataforma=canal,
            telegram_bot_token=(telegram_bot_token or "").strip() or None,
            auto_responder=False,  # so liga ao final do wizard
            salvar_historico=True,
        )
        sessao = SessaoService.criar(db, sessao_data)
        svc.salvar_estado(request, sessao_id=sessao.id, canal=canal)
        fluxi_log.info("onboarding", "canal", f"Sessao {canal} criada", extra={"sessao_id": sessao.id})

        if canal == "whatsapp":
            # Dispara conexao em background, pagina mostra QR + polling
            try:
                SessaoService.conectar(db, sessao.id)
            except Exception as e:
                fluxi_log.warning("onboarding", "canal", f"Erro ao iniciar conexao WA: {e}")
            return RedirectResponse(url=f"/onboarding/canal/aguardar/{sessao.id}", status_code=303)

        if canal == "telegram":
            # Conecta direto (long polling do bot)
            try:
                SessaoService.conectar(db, sessao.id)
            except Exception as e:
                fluxi_log.warning("onboarding", "canal", f"Erro ao conectar Telegram: {e}")
            return RedirectResponse(url=f"/onboarding/canal/aguardar/{sessao.id}", status_code=303)

        # Webchat: ja fica "conectado" assim que e criado
        try:
            SessaoService.conectar(db, sessao.id)
        except Exception as e:
            fluxi_log.warning("onboarding", "canal", f"Erro ao iniciar webchat: {e}")
        return RedirectResponse(url=f"/onboarding/canal/aguardar/{sessao.id}", status_code=303)

    except ValueError as e:
        # Erro de validacao (ex: token telegram invalido, nome duplicado)
        return templates.TemplateResponse(
            f"onboarding/canal_{canal}.html",
            {
                "request": request,
                "estado": svc.obter_estado(request),
                "step_atual": 2,
                "canal": canal,
                "erro": str(e),
                "form_nome": nome,
                "titulo": f"Conectar {canal.capitalize()}",
            },
            status_code=400,
        )


@router.get("/canal/aguardar/{sessao_id}", response_class=HTMLResponse)
def pagina_canal_aguardar(sessao_id: int, request: Request, db: Session = Depends(get_db)):
    """Pagina que aguarda o canal ficar pronto. WA: mostra QR + poll; outros: avanca."""
    sessao = SessaoService.obter_por_id(db, sessao_id)
    if not sessao:
        return RedirectResponse(url="/onboarding/canal", status_code=303)
    svc.salvar_estado(request, sessao_id=sessao_id, canal=sessao.plataforma, step=2)
    return templates.TemplateResponse(
        "onboarding/canal_aguardar.html",
        {
            "request": request,
            "sessao": sessao,
            "estado": svc.obter_estado(request),
            "step_atual": 2,
            "titulo": f"Conectar - {sessao.nome}",
        },
    )


@router.get("/canal/status/{sessao_id}")
def api_canal_status(sessao_id: int, db: Session = Depends(get_db)):
    """Polling. Retorna status atual + qr_code se WA."""
    sessao = SessaoService.obter_por_id(db, sessao_id)
    if not sessao:
        return JSONResponse({"erro": "sessao nao encontrada"}, status_code=404)

    # QR mais fresco vem do adapter ativo (igual sessao_frontend_router faz)
    from sessao.sessao_service import gerenciador_sessoes
    qr = sessao.qr_code
    canal_ativo = gerenciador_sessoes.obter_cliente(sessao_id)
    if canal_ativo is not None:
        qr_canal = getattr(canal_ativo, "qr_code", None)
        if qr_canal:
            qr = qr_canal

    return JSONResponse({
        "status": sessao.status,
        "plataforma": sessao.plataforma,
        "qr_code": qr,
        "telefone": sessao.telefone,
        "identificador": sessao.identificador,
        "pronto": sessao.status == "conectado",
    })


@router.post("/canal/confirmar")
def confirmar_canal(request: Request):
    """Apos canal conectado, avanca para passo 3 (agente)."""
    estado = svc.obter_estado(request)
    if not estado.get("sessao_id"):
        return RedirectResponse(url="/onboarding/canal", status_code=303)
    svc.salvar_estado(request, step=3)
    return RedirectResponse(url="/onboarding/agente", status_code=303)


# ============================================================
# Passo 3 - Agente
# ============================================================


@router.get("/agente", response_class=HTMLResponse)
def pagina_agente(request: Request, template_id: Optional[str] = None):
    estado = svc.obter_estado(request)
    if not estado.get("sessao_id"):
        return RedirectResponse(url="/onboarding/canal", status_code=303)
    svc.salvar_estado(request, step=3)

    selecionado = svc.obter_template_agente(template_id) if template_id else None
    return templates.TemplateResponse(
        "onboarding/agente.html",
        {
            "request": request,
            "estado": estado,
            "step_atual": 3,
            "templates_agente": svc.TEMPLATES_AGENTE,
            "selecionado": selecionado,
            "titulo": "Criar o primeiro agente",
        },
    )


@router.post("/agente/salvar")
def salvar_agente(
    request: Request,
    nome: str = Form(...),
    descricao: Optional[str] = Form(None),
    agente_papel: str = Form(...),
    agente_objetivo: str = Form(...),
    agente_politicas: str = Form(...),
    agente_tarefa: str = Form(...),
    agente_objetivo_explicito: str = Form(...),
    agente_publico: str = Form(...),
    agente_restricoes: str = Form(...),
    db: Session = Depends(get_db),
):
    """Cria o Agente e vincula como ativo da sessao."""
    estado = svc.obter_estado(request)
    sessao_id = estado.get("sessao_id")
    provedor_id = estado.get("provedor_id")
    if not sessao_id:
        return RedirectResponse(url="/onboarding/canal", status_code=303)

    try:
        codigo = svc.proximo_codigo_agente(db, sessao_id)
        agente_data = AgenteCriar(
            sessao_id=sessao_id,
            codigo=codigo,
            nome=nome.strip(),
            descricao=(descricao or "").strip() or None,
            agente_papel=agente_papel,
            agente_objetivo=agente_objetivo,
            agente_politicas=agente_politicas,
            agente_tarefa=agente_tarefa,
            agente_objetivo_explicito=agente_objetivo_explicito,
            agente_publico=agente_publico,
            agente_restricoes=agente_restricoes,
            provedor_llm_id=provedor_id,
            ativo=True,
        )
        agente = AgenteService.criar(db, agente_data)

        # Marca como agente ativo da sessao
        from sessao.sessao_schema import SessaoAtualizar
        SessaoService.atualizar(db, sessao_id, SessaoAtualizar(agente_ativo_id=agente.id))

        svc.salvar_estado(request, agente_id=agente.id, step=4)
        fluxi_log.info("onboarding", "agente", "Agente criado", extra={"agente_id": agente.id, "sessao_id": sessao_id})
        return RedirectResponse(url="/onboarding/teste", status_code=303)
    except Exception as e:
        fluxi_log.error("onboarding", "agente", f"Erro ao criar agente: {e}", exc_info=True)
        return templates.TemplateResponse(
            "onboarding/agente.html",
            {
                "request": request,
                "estado": svc.obter_estado(request),
                "step_atual": 3,
                "templates_agente": svc.TEMPLATES_AGENTE,
                "erro": f"Nao consegui salvar o agente: {e}",
                "form": {
                    "nome": nome,
                    "descricao": descricao,
                    "agente_papel": agente_papel,
                    "agente_objetivo": agente_objetivo,
                    "agente_politicas": agente_politicas,
                    "agente_tarefa": agente_tarefa,
                    "agente_objetivo_explicito": agente_objetivo_explicito,
                    "agente_publico": agente_publico,
                    "agente_restricoes": agente_restricoes,
                },
                "titulo": "Criar o primeiro agente",
            },
            status_code=400,
        )


# ============================================================
# Passo 4 - Testar
# ============================================================


@router.get("/teste", response_class=HTMLResponse)
def pagina_teste(request: Request, db: Session = Depends(get_db)):
    estado = svc.obter_estado(request)
    if not estado.get("agente_id"):
        return RedirectResponse(url="/onboarding/agente", status_code=303)
    svc.salvar_estado(request, step=4)

    sessao = SessaoService.obter_por_id(db, estado["sessao_id"]) if estado.get("sessao_id") else None
    agente = AgenteService.obter_por_id(db, estado["agente_id"])
    return templates.TemplateResponse(
        "onboarding/teste.html",
        {
            "request": request,
            "estado": estado,
            "step_atual": 4,
            "sessao": sessao,
            "agente": agente,
            "titulo": "Testar o agente",
        },
    )


@router.post("/teste/enviar")
async def api_teste_enviar(
    request: Request,
    texto: str = Form(...),
    db: Session = Depends(get_db),
):
    """Envia mensagem pro agente e devolve resposta. Nao persiste no banco."""
    estado = svc.obter_estado(request)
    agente_id = estado.get("agente_id")
    sessao_id = estado.get("sessao_id")
    if not agente_id or not sessao_id:
        return JSONResponse({"ok": False, "erro": "Estado de onboarding invalido"}, status_code=400)

    sessao = SessaoService.obter_por_id(db, sessao_id)
    agente = AgenteService.obter_por_id(db, agente_id)
    if not sessao or not agente:
        return JSONResponse({"ok": False, "erro": "Sessao ou agente nao encontrado"}, status_code=404)

    # Constroi uma Mensagem em memoria (nao persiste)
    from mensagem.mensagem_model import Mensagem as MensagemModel
    msg = MensagemModel(
        sessao_id=sessao_id,
        plataforma=sessao.plataforma,
        telefone_cliente="onboarding",
        chat_id="onboarding",
        tipo="texto",
        direcao="recebida",
        conteudo_texto=texto.strip(),
    )

    try:
        resultado = await AgenteService.processar_mensagem(
            db=db,
            sessao=sessao,
            mensagem=msg,
            historico_mensagens=[],
            agente=agente,
        )
        return JSONResponse({
            "ok": True,
            "texto": resultado.get("texto") or "(resposta vazia)",
            "modelo": resultado.get("modelo"),
            "tempo_ms": resultado.get("tempo_ms"),
        })
    except Exception as e:
        fluxi_log.error("onboarding", "teste", f"Erro no teste do agente: {e}", exc_info=True)
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=500)


# ============================================================
# Passo 5 - Finalizar
# ============================================================


@router.post("/finalizar")
def finalizar(request: Request, db: Session = Depends(get_db)):
    """Liga auto_responder na sessao e marca onboarding como concluido."""
    estado = svc.obter_estado(request)
    sessao_id = estado.get("sessao_id")
    if sessao_id:
        try:
            from sessao.sessao_schema import SessaoAtualizar
            SessaoService.atualizar(db, sessao_id, SessaoAtualizar(auto_responder=True))
        except Exception as e:
            fluxi_log.warning("onboarding", "finalizar", f"Erro ao ligar auto_responder: {e}")
    svc.salvar_estado(request, step=5, finalizado=True)
    return RedirectResponse(url="/onboarding/pronto", status_code=303)


@router.get("/pronto", response_class=HTMLResponse)
def pagina_pronto(request: Request, db: Session = Depends(get_db)):
    estado = svc.obter_estado(request)
    sessao = SessaoService.obter_por_id(db, estado["sessao_id"]) if estado.get("sessao_id") else None
    agente = AgenteService.obter_por_id(db, estado["agente_id"]) if estado.get("agente_id") else None
    return templates.TemplateResponse(
        "onboarding/done.html",
        {
            "request": request,
            "estado": estado,
            "step_atual": 5,
            "sessao": sessao,
            "agente": agente,
            "titulo": "Tudo pronto!",
        },
    )


@router.post("/concluir")
def concluir(request: Request):
    """Limpa estado e manda pro dashboard."""
    svc.limpar_estado(request)
    return RedirectResponse(url="/", status_code=303)
