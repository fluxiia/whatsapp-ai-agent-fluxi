"""
Rotas do frontend para sessões.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from sessao.sessao_service import SessaoService
from sessao.sessao_schema import SessaoCriar, SessaoAtualizar
from sessao.sessao_tipo_mensagem_service import SessaoTipoMensagemService
from config.config_service import ConfiguracaoService
from log.log_service import fluxi_log

router = APIRouter(prefix="/sessoes", tags=["Frontend - Sessões"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def pagina_sessoes(request: Request, db: Session = Depends(get_db)):
    """Página de listagem de sessões."""
    sessoes = SessaoService.listar_todas(db)
    
    return templates.TemplateResponse("sessao/lista.html", {
        "request": request,
        "sessoes": sessoes,
        "titulo": "Sessões WhatsApp"
    })


@router.get("/nova", response_class=HTMLResponse)
def pagina_nova_sessao(request: Request, db: Session = Depends(get_db)):
    """Página para criar nova sessão."""
    # Buscar configurações padrão do agente
    config_agente = {
        "papel": ConfiguracaoService.obter_valor(db, "agente_papel_padrao", "assistente pessoal"),
        "objetivo": ConfiguracaoService.obter_valor(db, "agente_objetivo_padrao", "ajudar o usuário"),
        "politicas": ConfiguracaoService.obter_valor(db, "agente_politicas_padrao", "ser educado e respeitoso"),
        "tarefa": ConfiguracaoService.obter_valor(db, "agente_tarefa_padrao", "responder perguntas"),
        "objetivo_explicito": ConfiguracaoService.obter_valor(db, "agente_objetivo_explicito_padrao", "fornecer informações úteis"),
        "publico": ConfiguracaoService.obter_valor(db, "agente_publico_padrao", "usuários em geral"),
        "restricoes": ConfiguracaoService.obter_valor(db, "agente_restricoes_padrao", "responder em português")
    }
    
    # Buscar configurações LLM
    modelo_padrao = ConfiguracaoService.obter_valor(db, "openrouter_modelo_padrao", "google/gemini-3.1-flash-lite-preview")
    temperatura_padrao = ConfiguracaoService.obter_valor(db, "openrouter_temperatura", "0.7")
    max_tokens_padrao = ConfiguracaoService.obter_valor(db, "openrouter_max_tokens", "2000")
    top_p_padrao = ConfiguracaoService.obter_valor(db, "openrouter_top_p", "1.0")
    
    return templates.TemplateResponse("sessao/form.html", {
        "request": request,
        "config_agente": config_agente,
        "modelo_padrao": modelo_padrao,
        "temperatura_padrao": temperatura_padrao,
        "max_tokens_padrao": max_tokens_padrao,
        "top_p_padrao": top_p_padrao,
        "titulo": "Nova Sessão",
        "acao": "criar"
    })


@router.get("/{sessao_id}/editar", response_class=HTMLResponse)
def pagina_editar_sessao(sessao_id: int, request: Request, db: Session = Depends(get_db)):
    """Redireciona para o painel de detalhes (aba de propriedades)."""
    return RedirectResponse(url=f"/sessoes/{sessao_id}/detalhes?tab=propriedades", status_code=303)


@router.get("/{sessao_id}/detalhes", response_class=HTMLResponse)
def pagina_detalhes_sessao(
    sessao_id: int,
    request: Request,
    erro: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Página de detalhes da sessão."""
    sessao = SessaoService.obter_por_id(db, sessao_id)
    if not sessao:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": "Sessão não encontrada",
            "titulo": "Erro"
        })

    # Buscar comandos ativos
    from sessao.sessao_comando_service import SessaoComandoService
    comandos = SessaoComandoService.obter_comandos_dict(db, sessao_id)

    # Buscar tipos de mensagem configurados
    configs = SessaoTipoMensagemService.listar_por_sessao(db, sessao_id)
    tipos = {}
    for config in configs:
        tipos[config.tipo] = {"acao": config.acao, "resposta_fixa": config.resposta_fixa}

    for tipo in ["audio", "imagem", "video", "sticker", "localizacao", "documento"]:
        if tipo not in tipos:
            tipos[tipo] = {"acao": "ignorar", "resposta_fixa": None}

    return templates.TemplateResponse("sessao/detalhes.html", {
        "request": request,
        "sessao": sessao,
        "comandos": comandos,
        "tipos": tipos,
        "erro": erro,
        "titulo": f"Painel do Agente - {sessao.nome}"
    })


@router.get("/{sessao_id}/conectar", response_class=HTMLResponse)
def pagina_conectar_sessao(sessao_id: int, request: Request, db: Session = Depends(get_db)):
    """Página para conectar sessão (WhatsApp: QR; Telegram: dispara polling)."""
    from datetime import datetime, timedelta

    sessao = SessaoService.obter_por_id(db, sessao_id)
    if not sessao:
        return templates.TemplateResponse("shared/erro.html", {
            "request": request,
            "mensagem": "Sessão não encontrada",
            "titulo": "Erro"
        })

    # Telegram: não há QR — dispara conexão e volta pra detalhes.
    if sessao.plataforma == "telegram":
        erro_msg = None
        try:
            if sessao.status != "conectado":
                SessaoService.conectar(db, sessao_id)
        except ValueError as ve:
            erro_msg = str(ve)
            fluxi_log.error("sessao", "conexao", "Erro ao conectar Telegram", exc_info=True, extra={"sessao_id": sessao_id, "erro": erro_msg})
        except Exception:
            erro_msg = "Falha inesperada ao conectar o bot. Veja os logs do servidor."
            fluxi_log.error("sessao", "conexao", "Erro ao conectar Telegram", exc_info=True, extra={"sessao_id": sessao_id})
        destino = f"/sessoes/{sessao_id}/detalhes"
        if erro_msg:
            from urllib.parse import quote
            destino += f"?erro={quote(erro_msg)}"
        return RedirectResponse(url=destino, status_code=303)

    # WhatsApp: fluxo de QR.
    qr_code_expirado = False
    if sessao.qr_code and sessao.qr_code_gerado_em:
        tempo_decorrido = datetime.now() - sessao.qr_code_gerado_em
        if tempo_decorrido > timedelta(seconds=60):
            qr_code_expirado = True
            fluxi_log.info("sessao", "qrcode", "QR Code expirado", extra={"sessao_id": sessao_id, "tempo_decorrido_s": tempo_decorrido.seconds})
            sessao.qr_code = None
            sessao.status = "desconectado"

    # QR mais fresco vem do adapter ativo (se já está conectando).
    from sessao.sessao_service import gerenciador_sessoes
    canal_ativo = gerenciador_sessoes.obter_cliente(sessao_id)
    qr_canal = getattr(canal_ativo, "qr_code", None) if canal_ativo else None
    if qr_canal and not qr_code_expirado:
        sessao.qr_code = qr_canal

    return templates.TemplateResponse("sessao/paircode.html", {
        "request": request,
        "sessao": sessao,
        "qr_code_expirado": qr_code_expirado,
        "titulo": f"Conectar - {sessao.nome}"
    })


@router.post("/{sessao_id}/conectar")
def conectar_sessao_post(
    sessao_id: int,
    db: Session = Depends(get_db)
):
    """Inicia conexão (WA: QR; TG: polling)."""
    erro_msg: Optional[str] = None
    sessao = SessaoService.obter_por_id(db, sessao_id)
    try:
        if sessao and sessao.plataforma == "whatsapp":
            sessao.qr_code = None
            sessao.qr_code_gerado_em = None
            db.commit()
            fluxi_log.info("sessao", "qrcode", "QR Code antigo limpo", extra={"sessao_id": sessao_id})

        SessaoService.conectar(db, sessao_id, usar_paircode=False)
    except ValueError as ve:
        erro_msg = str(ve)
        fluxi_log.error("sessao", "conexao", "Erro ao conectar", exc_info=True, extra={"sessao_id": sessao_id, "erro": erro_msg})
    except Exception:
        erro_msg = "Erro inesperado ao iniciar conexão."
        fluxi_log.error("sessao", "conexao", "Erro ao conectar", exc_info=True, extra={"sessao_id": sessao_id})

    destino = f"/sessoes/{sessao_id}/detalhes" if (sessao and sessao.plataforma in ("telegram", "webchat")) else f"/sessoes/{sessao_id}/conectar"
    if erro_msg:
        from urllib.parse import quote
        destino += ("&" if "?" in destino else "?") + f"erro={quote(erro_msg)}"
    return RedirectResponse(url=destino, status_code=303)


@router.post("/{sessao_id}/desconectar")
def desconectar_sessao_post(sessao_id: int, db: Session = Depends(get_db)):
    """Desconecta uma sessão WhatsApp."""
    try:
        SessaoService.desconectar(db, sessao_id)
    except Exception as e:
        fluxi_log.error("sessao", "conexao", "Erro ao desconectar", exc_info=True, extra={"sessao_id": sessao_id})
    return RedirectResponse(url="/sessoes", status_code=303)


@router.post("/{sessao_id}/deletar")
def deletar_sessao_post(sessao_id: int, db: Session = Depends(get_db)):
    """Deleta uma sessão WhatsApp."""
    try:
        SessaoService.deletar(db, sessao_id)
        fluxi_log.info("sessao", "conexao", "Sessao deletada com sucesso", extra={"sessao_id": sessao_id})
    except Exception as e:
        fluxi_log.error("sessao", "conexao", "Erro ao deletar", exc_info=True, extra={"sessao_id": sessao_id})
    return RedirectResponse(url="/sessoes", status_code=303)


@router.post("/criar")
def criar_sessao_post(
    nome: str = Form(...),
    plataforma: str = Form("whatsapp"),
    telegram_bot_token: str = Form(None),
    modelo_llm: str = Form(None),
    temperatura: str = Form(None),
    max_tokens: str = Form(None),
    top_p: str = Form(None),
    auto_responder: str = Form(None),
    salvar_historico: str = Form(None),
    # Tipos de mensagem
    tipo_audio: str = Form("enviar_ia"),
    tipo_audio_resposta: str = Form(""),
    tipo_imagem: str = Form("enviar_ia"),
    tipo_imagem_resposta: str = Form(""),
    tipo_video: str = Form("ignorar"),
    tipo_video_resposta: str = Form(""),
    tipo_sticker: str = Form("ignorar"),
    tipo_sticker_resposta: str = Form(""),
    tipo_localizacao: str = Form("ignorar"),
    tipo_localizacao_resposta: str = Form(""),
    tipo_documento: str = Form("ignorar"),
    tipo_documento_resposta: str = Form(""),
    db: Session = Depends(get_db)
):
    """Cria uma nova sessão via formulário."""
    try:
        # Converter checkboxes
        auto_responder_bool = auto_responder == "true"
        salvar_historico_bool = salvar_historico == "true"

        # Criar sessão
        sessao_data = SessaoCriar(
            nome=nome,
            plataforma=plataforma,
            telegram_bot_token=(telegram_bot_token.strip() if telegram_bot_token else None),
            auto_responder=auto_responder_bool,
            salvar_historico=salvar_historico_bool,
        )
        
        sessao = SessaoService.criar(db, sessao_data)
        
        # Criar configurações de tipos de mensagem
        tipos_config = {
            "audio": {"acao": tipo_audio, "resposta_fixa": tipo_audio_resposta if tipo_audio == "resposta_fixa" else None},
            "imagem": {"acao": tipo_imagem, "resposta_fixa": tipo_imagem_resposta if tipo_imagem == "resposta_fixa" else None},
            "video": {"acao": tipo_video, "resposta_fixa": tipo_video_resposta if tipo_video == "resposta_fixa" else None},
            "sticker": {"acao": tipo_sticker, "resposta_fixa": tipo_sticker_resposta if tipo_sticker == "resposta_fixa" else None},
            "localizacao": {"acao": tipo_localizacao, "resposta_fixa": tipo_localizacao_resposta if tipo_localizacao == "resposta_fixa" else None},
            "documento": {"acao": tipo_documento, "resposta_fixa": tipo_documento_resposta if tipo_documento == "resposta_fixa" else None},
        }
        SessaoTipoMensagemService.atualizar_todos(db, sessao.id, tipos_config)
        
        return RedirectResponse(url="/sessoes", status_code=303)
    except ValueError as e:
        return RedirectResponse(url=f"/sessoes/nova?erro={str(e)}", status_code=303)


@router.get("/{sessao_id}/tipos-mensagem", response_class=HTMLResponse)
def pagina_tipos_mensagem(sessao_id: int, request: Request, db: Session = Depends(get_db)):
    """Redireciona para o painel de detalhes."""
    return RedirectResponse(url=f"/sessoes/{sessao_id}/detalhes?tab=midia", status_code=303)


@router.post("/{sessao_id}/tipos-mensagem/salvar")
def salvar_tipos_mensagem(
    sessao_id: int,
    tipo_audio: str = Form("ignorar"),
    tipo_audio_resposta: str = Form(""),
    tipo_imagem: str = Form("ignorar"),
    tipo_imagem_resposta: str = Form(""),
    tipo_video: str = Form("ignorar"),
    tipo_video_resposta: str = Form(""),
    tipo_sticker: str = Form("ignorar"),
    tipo_sticker_resposta: str = Form(""),
    tipo_localizacao: str = Form("ignorar"),
    tipo_localizacao_resposta: str = Form(""),
    tipo_documento: str = Form("ignorar"),
    tipo_documento_resposta: str = Form(""),
    db: Session = Depends(get_db)
):
    """Salva configurações de tipos de mensagem."""
    tipos_config = {
        "audio": {"acao": tipo_audio, "resposta_fixa": tipo_audio_resposta if tipo_audio == "resposta_fixa" else None},
        "imagem": {"acao": tipo_imagem, "resposta_fixa": tipo_imagem_resposta if tipo_imagem == "resposta_fixa" else None},
        "video": {"acao": tipo_video, "resposta_fixa": tipo_video_resposta if tipo_video == "resposta_fixa" else None},
        "sticker": {"acao": tipo_sticker, "resposta_fixa": tipo_sticker_resposta if tipo_sticker == "resposta_fixa" else None},
        "localizacao": {"acao": tipo_localizacao, "resposta_fixa": tipo_localizacao_resposta if tipo_localizacao == "resposta_fixa" else None},
        "documento": {"acao": tipo_documento, "resposta_fixa": tipo_documento_resposta if tipo_documento == "resposta_fixa" else None},
    }
    SessaoTipoMensagemService.atualizar_todos(db, sessao_id, tipos_config)
    return RedirectResponse(url=f"/sessoes/{sessao_id}/detalhes", status_code=303)


# ===================== COMANDOS PERSONALIZÁVEIS =====================

@router.get("/{sessao_id}/comandos", response_class=HTMLResponse)
def pagina_comandos(sessao_id: int, request: Request, db: Session = Depends(get_db)):
    """Redireciona para o painel de detalhes."""
    return RedirectResponse(url=f"/sessoes/{sessao_id}/detalhes?tab=comandos", status_code=303)


@router.post("/{sessao_id}/comandos/salvar")
def salvar_comandos(
    sessao_id: int,
    request: Request,
    # Ativar/Desativar IA
    cmd_ativar_ativo: str = Form(None),
    cmd_ativar_gatilho: str = Form("#ativar"),
    cmd_ativar_descricao: str = Form("Ativa o auto-responder da IA"),
    cmd_ativar_resposta: str = Form(None),
    cmd_desativar_ativo: str = Form(None),
    cmd_desativar_gatilho: str = Form("#desativar"),
    cmd_desativar_descricao: str = Form("Desativa o auto-responder da IA"),
    cmd_desativar_resposta: str = Form(None),
    # Limpar
    cmd_limpar_ativo: str = Form(None),
    cmd_limpar_gatilho: str = Form("#limpar"),
    cmd_limpar_descricao: str = Form("Apaga o histórico de conversas"),
    cmd_limpar_resposta: str = Form(None),
    # Ajuda
    cmd_ajuda_ativo: str = Form(None),
    cmd_ajuda_gatilho: str = Form("#ajuda"),
    cmd_ajuda_descricao: str = Form("Mostra comandos disponíveis"),
    # Status
    cmd_status_ativo: str = Form(None),
    cmd_status_gatilho: str = Form("#status"),
    cmd_status_descricao: str = Form("Mostra informações da sessão"),
    # Listar
    cmd_listar_ativo: str = Form(None),
    cmd_listar_gatilho: str = Form("#listar"),
    cmd_listar_descricao: str = Form("Lista agentes disponíveis"),
    # Trocar Agente
    cmd_trocar_agente_ativo: str = Form(None),
    cmd_trocar_agente_gatilho: str = Form("#"),
    cmd_trocar_agente_descricao: str = Form("Ativa um agente específico"),
    cmd_trocar_agente_resposta: str = Form(None),
    db: Session = Depends(get_db)
):
    """Salva configurações de comandos."""
    from sessao.sessao_comando_service import SessaoComandoService
    
    comandos_config = {
        "ativar": {
            "gatilho": cmd_ativar_gatilho,
            "ativo": cmd_ativar_ativo == "true",
            "descricao": cmd_ativar_descricao,
            "resposta": cmd_ativar_resposta
        },
        "desativar": {
            "gatilho": cmd_desativar_gatilho,
            "ativo": cmd_desativar_ativo == "true",
            "descricao": cmd_desativar_descricao,
            "resposta": cmd_desativar_resposta
        },
        "limpar": {
            "gatilho": cmd_limpar_gatilho,
            "ativo": cmd_limpar_ativo == "true",
            "descricao": cmd_limpar_descricao,
            "resposta": cmd_limpar_resposta
        },
        "ajuda": {
            "gatilho": cmd_ajuda_gatilho,
            "ativo": cmd_ajuda_ativo == "true",
            "descricao": cmd_ajuda_descricao
        },
        "status": {
            "gatilho": cmd_status_gatilho,
            "ativo": cmd_status_ativo == "true",
            "descricao": cmd_status_descricao
        },
        "listar": {
            "gatilho": cmd_listar_gatilho,
            "ativo": cmd_listar_ativo == "true",
            "descricao": cmd_listar_descricao
        },
        "trocar_agente": {
            "gatilho": cmd_trocar_agente_gatilho,
            "ativo": cmd_trocar_agente_ativo == "true",
            "descricao": cmd_trocar_agente_descricao,
            "resposta": cmd_trocar_agente_resposta
        }
    }
    
    SessaoComandoService.atualizar_todos(db, sessao_id, comandos_config)
    return RedirectResponse(url=f"/sessoes/{sessao_id}/detalhes", status_code=303)


@router.post("/{sessao_id}/atualizar")
def atualizar_sessao_post(
    sessao_id: int,
    nome: str = Form(None),
    agente_papel: str = Form(None),
    agente_objetivo: str = Form(None),
    agente_politicas: str = Form(None),
    agente_tarefa: str = Form(None),
    agente_objetivo_explicito: str = Form(None),
    agente_publico: str = Form(None),
    agente_restricoes: str = Form(None),
    modelo_llm: str = Form(None),
    temperatura: str = Form(None),
    max_tokens: str = Form(None),
    top_p: str = Form(None),
    auto_responder: str = Form(None),
    salvar_historico: str = Form(None),
    ativa: str = Form(None),
    db: Session = Depends(get_db)
):
    """Atualiza uma sessão via formulário."""
    try:
        # Preparar dados de atualização
        update_data = {}
        
        if nome:
            update_data["nome"] = nome
        if agente_papel:
            update_data["agente_papel"] = agente_papel
        if agente_objetivo:
            update_data["agente_objetivo"] = agente_objetivo
        if agente_politicas:
            update_data["agente_politicas"] = agente_politicas
        if agente_tarefa:
            update_data["agente_tarefa"] = agente_tarefa
        if agente_objetivo_explicito:
            update_data["agente_objetivo_explicito"] = agente_objetivo_explicito
        if agente_publico:
            update_data["agente_publico"] = agente_publico
        if agente_restricoes:
            update_data["agente_restricoes"] = agente_restricoes
        if modelo_llm:
            update_data["modelo_llm"] = modelo_llm
        if temperatura:
            update_data["temperatura"] = temperatura
        if max_tokens:
            update_data["max_tokens"] = max_tokens
        if top_p:
            update_data["top_p"] = top_p
        if auto_responder is not None:
            update_data["auto_responder"] = auto_responder == "true"
        if salvar_historico is not None:
            update_data["salvar_historico"] = salvar_historico == "true"
        if ativa is not None:
            update_data["ativa"] = ativa == "true"
        
        sessao_atualizar = SessaoAtualizar(**update_data)
        SessaoService.atualizar(db, sessao_id, sessao_atualizar)
        
        return RedirectResponse(url=f"/sessoes/{sessao_id}/detalhes", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/sessoes/{sessao_id}/editar?erro={str(e)}", status_code=303)
