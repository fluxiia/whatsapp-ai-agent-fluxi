"""
Rotas do Web Chat embutido.

- GET  /chat/{sessao_id}                 → página HTML do chat (UI)
- POST /chat/{sessao_id}/enviar          → recebe mensagem do visitante (texto/áudio/imagem)
- GET  /chat/{sessao_id}/stream          → SSE com respostas do agente em tempo real
- GET  /chat/{sessao_id}/historico       → últimas N mensagens (JSON) pra hidratar a UI no load

Identidade do visitante = UUID gerado no browser e enviado em todo request via
`client_id` (form-field, cookie ou query param). Não há login.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from canal.canal_base import EventoMensagem, Plataforma, TipoMidia
from canal.canal_webchat import CanalWebChatClient
from database import get_db
from log.log_service import fluxi_log
from mensagem.mensagem_model import Mensagem
from mensagem.mensagem_service import MensagemService
from sessao.sessao_service import SessaoService, gerenciador_sessoes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Web Chat"])
templates = Jinja2Templates(directory="templates")


def _obter_canal_webchat(sessao_id: int, db: Session) -> Optional[CanalWebChatClient]:
    """Garante que existe um adapter WebChat ativo pra essa sessão."""
    sessao = SessaoService.obter_por_id(db, sessao_id)
    if not sessao or sessao.plataforma != Plataforma.WEBCHAT.value or not sessao.ativa:
        return None

    canal = gerenciador_sessoes.obter_cliente(sessao_id)
    if canal is None:
        # Auto-conecta: webchat não precisa de credenciais externas.
        try:
            SessaoService.conectar(db, sessao_id)
            canal = gerenciador_sessoes.obter_cliente(sessao_id)
        except Exception:
            logger.exception("Falha ao autoconectar webchat sessão %s", sessao_id)
            return None

    if not isinstance(canal, CanalWebChatClient):
        return None
    return canal


@router.get("/{sessao_id}", response_class=HTMLResponse)
def pagina_chat(sessao_id: int, request: Request, db: Session = Depends(get_db)):
    """Renderiza a página do web chat."""
    sessao = SessaoService.obter_por_id(db, sessao_id)
    if not sessao:
        return templates.TemplateResponse(
            "shared/erro.html",
            {"request": request, "mensagem": "Sessão não encontrada", "titulo": "Erro"},
        )
    if sessao.plataforma != Plataforma.WEBCHAT.value:
        return templates.TemplateResponse(
            "shared/erro.html",
            {
                "request": request,
                "mensagem": "Esta sessão não está configurada como Web Chat.",
                "titulo": "Canal incorreto",
            },
        )
    if not sessao.ativa:
        return templates.TemplateResponse(
            "shared/erro.html",
            {
                "request": request,
                "mensagem": "Este chat está desativado pelo administrador.",
                "titulo": "Chat indisponível",
            },
        )

    # Auto-conecta na primeira visita.
    _obter_canal_webchat(sessao_id, db)

    return templates.TemplateResponse(
        "webchat/chat.html",
        {
            "request": request,
            "sessao": sessao,
            "titulo": sessao.nome,
        },
    )


@router.get("/{sessao_id}/historico")
def historico_chat(
    sessao_id: int,
    client_id: str,
    limite: int = 50,
    db: Session = Depends(get_db),
):
    """Últimas mensagens desse visitante. Usado pelo browser ao carregar a página."""
    sessao = SessaoService.obter_por_id(db, sessao_id)
    if not sessao or sessao.plataforma != Plataforma.WEBCHAT.value:
        return JSONResponse({"mensagens": []})

    msgs = (
        db.query(Mensagem)
        .filter(
            Mensagem.sessao_id == sessao_id,
            Mensagem.plataforma == Plataforma.WEBCHAT.value,
            Mensagem.chat_id == client_id,
        )
        .order_by(Mensagem.criado_em.desc())
        .limit(limite)
        .all()
    )

    payload = []
    for m in reversed(msgs):  # cronológico crescente pra UI
        payload.append(
            {
                "id": m.id,
                "direcao": m.direcao,
                "tipo": m.tipo,
                "texto": m.conteudo_texto or "",
                "resposta_texto": m.resposta_texto or "",
                "criado_em": m.criado_em.isoformat() if m.criado_em else None,
                "imagem_url": (
                    f"/chat/{sessao_id}/imagem/{m.id}"
                    if m.conteudo_imagem_path
                    else None
                ),
            }
        )
    return JSONResponse({"mensagens": payload})


@router.get("/{sessao_id}/imagem/{mensagem_id}")
def baixar_imagem(sessao_id: int, mensagem_id: int, db: Session = Depends(get_db)):
    """Serve imagem persistida da mensagem."""
    from fastapi.responses import FileResponse

    msg = db.query(Mensagem).filter(
        Mensagem.id == mensagem_id, Mensagem.sessao_id == sessao_id
    ).first()
    if not msg or not msg.conteudo_imagem_path:
        return JSONResponse({"erro": "imagem não encontrada"}, status_code=404)
    return FileResponse(msg.conteudo_imagem_path, media_type=msg.conteudo_mime_type or "image/jpeg")


@router.post("/{sessao_id}/enviar")
async def enviar_mensagem(
    sessao_id: int,
    client_id: str = Form(...),
    nome: Optional[str] = Form(None),
    texto: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
    imagem: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """Recebe mensagem do visitante e despacha pro pipeline."""
    canal = _obter_canal_webchat(sessao_id, db)
    if not canal:
        return JSONResponse({"ok": False, "erro": "Chat indisponível"}, status_code=400)

    # Construir EventoMensagem baseado no que veio.
    msg_id_externo = str(uuid.uuid4())

    if audio is not None:
        audio_bytes = await audio.read()
        if not audio_bytes:
            return JSONResponse({"ok": False, "erro": "Áudio vazio"}, status_code=400)
        evento = EventoMensagem(
            plataforma=Plataforma.WEBCHAT,
            sessao_id=sessao_id,
            mensagem_id_externo=msg_id_externo,
            chat_id=client_id,
            remetente_id=client_id,
            remetente_nome=nome,
            tipo=TipoMidia.AUDIO,
            texto=(texto or "").strip(),
            midia_bytes=audio_bytes,
            midia_mime=audio.content_type or "audio/webm",
        )
    elif imagem is not None:
        img_bytes = await imagem.read()
        if not img_bytes:
            return JSONResponse({"ok": False, "erro": "Imagem vazia"}, status_code=400)
        evento = EventoMensagem(
            plataforma=Plataforma.WEBCHAT,
            sessao_id=sessao_id,
            mensagem_id_externo=msg_id_externo,
            chat_id=client_id,
            remetente_id=client_id,
            remetente_nome=nome,
            tipo=TipoMidia.IMAGEM,
            texto=(texto or "").strip(),
            midia_bytes=img_bytes,
            midia_mime=imagem.content_type or "image/jpeg",
            midia_nome=imagem.filename,
        )
    elif texto and texto.strip():
        evento = EventoMensagem(
            plataforma=Plataforma.WEBCHAT,
            sessao_id=sessao_id,
            mensagem_id_externo=msg_id_externo,
            chat_id=client_id,
            remetente_id=client_id,
            remetente_nome=nome,
            tipo=TipoMidia.TEXTO,
            texto=texto.strip(),
        )
    else:
        return JSONResponse({"ok": False, "erro": "Mensagem vazia"}, status_code=400)

    # Mostrar indicador de "digitando" pro browser enquanto processa.
    canal.empurrar_indicador_digitando(client_id, True)

    # Processar de forma assíncrona pra não bloquear o POST.
    async def _processar():
        from database import SessionLocal

        db_bg = SessionLocal()
        try:
            await MensagemService.processar_evento_canal(db_bg, evento)
        except Exception:
            fluxi_log.error(
                "webchat", "pipeline", "Erro no processamento do evento",
                exc_info=True, session_id=sessao_id,
            )
            canal.enviar_texto(
                client_id,
                "❌ Tive um problema ao processar sua mensagem. Tenta de novo, por favor.",
            )
        finally:
            canal.empurrar_indicador_digitando(client_id, False)
            db_bg.close()

    asyncio.create_task(_processar())
    return JSONResponse({"ok": True, "mensagem_id": msg_id_externo})


@router.get("/{sessao_id}/stream")
async def stream_sse(sessao_id: int, client_id: str, db: Session = Depends(get_db)):
    """Server-Sent Events: empurra eventos da fila do client_id pro browser."""
    canal = _obter_canal_webchat(sessao_id, db)
    if not canal:
        return JSONResponse({"erro": "Chat indisponível"}, status_code=400)

    fila = canal.obter_ou_criar_fila(client_id)

    async def event_stream():
        # Hello inicial — confirma conexão pro browser.
        yield f": ping\n\n"
        yield "event: ready\ndata: {}\n\n"

        try:
            while True:
                try:
                    payload = await asyncio.wait_for(fila.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    # Keep-alive a cada 20s pra proxies não derrubarem a conexão.
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            # Browser fechou conexão — limpar fila pra não vazar memória.
            canal.limpar_fila_inativa(client_id)
            raise

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Nginx: não bufferiza SSE
            "Connection": "keep-alive",
        },
    )
