"""
Router API REST do Coding Agent.
Prefixo: /api/coding
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session

from database import get_db
from coding_agent.coding_memory import CodingMemoryService
from coding_agent.coding_model import CodingSession, CodingTask
from coding_agent.coding_schema import (
    CodingMensagemEnviar,
    CodingMensagemResposta,
    CodingSessionAtualizar,
    CodingSessionCriar,
    CodingSessionResposta,
    CodingTaskResposta,
    CodingTaskResumo,
    MemoriaAtualizar,
    MemoriaResposta,
    TaskStatusResposta,
)
from coding_agent.coding_service import CodingService
import asyncio

router = APIRouter(prefix="/api/coding", tags=["coding"])


# ══════════════════════════════════════════════════════════
# SESSIONS
# ══════════════════════════════════════════════════════════

@router.get("/sessions", response_model=List[CodingSessionResposta])
def listar_sessions(db: Session = Depends(get_db)):
    return CodingService.listar_sessoes(db)


@router.get("/sessions/by-agente/{agente_id}", response_model=Optional[CodingSessionResposta])
def obter_session_por_agente(agente_id: int, db: Session = Depends(get_db)):
    cs = CodingService.obter_sessao_por_agente(db, agente_id)
    if not cs:
        raise HTTPException(status_code=404, detail="CodingSession não encontrada")
    return cs


@router.get("/sessions/{session_id}", response_model=CodingSessionResposta)
def obter_session(session_id: int, db: Session = Depends(get_db)):
    cs = CodingService.obter_sessao(db, session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="CodingSession não encontrada")
    return cs


@router.post("/sessions", response_model=CodingSessionResposta, status_code=201)
def criar_session(dados: CodingSessionCriar, db: Session = Depends(get_db)):
    try:
        return CodingService.criar_sessao(db, dados)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/sessions/{session_id}", response_model=CodingSessionResposta)
def atualizar_session(
    session_id: int,
    dados: CodingSessionAtualizar,
    db: Session = Depends(get_db),
):
    cs = CodingService.obter_sessao(db, session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="CodingSession não encontrada")
    for field, value in dados.model_dump(exclude_none=True).items():
        setattr(cs, field, value)
    db.commit()
    db.refresh(cs)
    return cs


# ══════════════════════════════════════════════════════════
# MEMÓRIA
# ══════════════════════════════════════════════════════════

@router.get("/sessions/{session_id}/memory", response_model=MemoriaResposta)
def ler_memoria(session_id: int, db: Session = Depends(get_db)):
    cs = CodingService.obter_sessao(db, session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="CodingSession não encontrada")
    content = CodingMemoryService.ler(db, session_id)
    return MemoriaResposta(
        coding_session_id=session_id,
        content=content,
        tamanho_chars=len(content),
    )


@router.put("/sessions/{session_id}/memory", response_model=MemoriaResposta)
def atualizar_memoria(
    session_id: int,
    dados: MemoriaAtualizar,
    db: Session = Depends(get_db),
):
    cs = CodingService.obter_sessao(db, session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="CodingSession não encontrada")
    CodingMemoryService.escrever(db, session_id, dados.content)
    return MemoriaResposta(
        coding_session_id=session_id,
        content=dados.content,
        tamanho_chars=len(dados.content),
    )


@router.delete("/sessions/{session_id}/memory")
def limpar_memoria(session_id: int, db: Session = Depends(get_db)):
    cs = CodingService.obter_sessao(db, session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="CodingSession não encontrada")
    CodingMemoryService.escrever(db, session_id, "")
    return {"success": True, "message": "Memória limpa"}


# ══════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════

@router.get("/sessions/{session_id}/tasks", response_model=List[CodingTaskResumo])
def listar_tasks(
    session_id: int,
    status_filter: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    tarefas = CodingService.listar_tarefas(db, session_id, status_filter, limit)
    return [
        CodingTaskResumo(
            id=t.id,
            coding_session_id=t.coding_session_id,
            titulo=t.titulo,
            status=t.status,
            iteracoes=t.iteracoes,
            artifacts_count=len(t.artifacts or []),
            criado_em=t.criado_em,
            completado_em=t.completado_em,
        )
        for t in tarefas
    ]


@router.get("/tasks/{task_id}", response_model=CodingTaskResposta)
def obter_task(task_id: int, db: Session = Depends(get_db)):
    task = CodingService.obter_tarefa(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task


@router.get("/tasks/{task_id}/status", response_model=TaskStatusResposta)
def status_task(task_id: int, db: Session = Depends(get_db)):
    task = CodingService.obter_tarefa(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    # Última mensagem do assistente
    ultima_assistente = None
    for msg in reversed(task.get_messages()):
        if msg.get("role") == "assistant" and msg.get("content"):
            ultima_assistente = msg["content"]
            if isinstance(ultima_assistente, list):
                ultima_assistente = " ".join(
                    p.get("text", "") for p in ultima_assistente if isinstance(p, dict)
                )
            break
    shells_ativas = [
        sid for sid, info in (task.shell_sessions or {}).items()
        if info.get("status") == "running"
    ]
    return TaskStatusResposta(
        task_id=task.id,
        status=task.status,
        titulo=task.titulo,
        iteracoes=task.iteracoes,
        shell_sessions_ativas=shells_ativas,
        artifacts=task.artifacts or [],
        ultima_mensagem_assistente=ultima_assistente,
        error=task.error,
        completado_em=task.completado_em,
    )

@router.get("/tasks/active/{sessao_id}/{telefone_cliente}", response_model=Optional[TaskStatusResposta])
def obter_task_ativa(sessao_id: int, telefone_cliente: str, db: Session = Depends(get_db)):
    from agente.agente_model import Agente as AgenteModel
    agente_coding = db.query(AgenteModel).filter(
        AgenteModel.sessao_id == sessao_id,
        AgenteModel.is_coding_agent == True
    ).first()
    if not agente_coding:
        return None
        
    coding_session = CodingService.obter_sessao_por_agente(db, agente_coding.id)
    if not coding_session:
        return None
        
    task = CodingService.obter_tarefa_ativa(db, coding_session.id, telefone_cliente)
    if not task:
        return None
        
    return status_task(task.id, db)


@router.delete("/tasks/{task_id}")
async def cancelar_task(task_id: int, db: Session = Depends(get_db)):
    task = CodingService.obter_tarefa(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    if task.status in ("running", "waiting_input", "pending"):
        # Matar todos os processos shell ativos da tarefa
        from internal_sandbox.shell_service import ShellService
        for sid, info in (task.shell_sessions or {}).items():
            if info.get("status") == "running":
                try:
                    await ShellService.kill_session(sid)
                except Exception:
                    pass
        task.status = "cancelled"
        from datetime import datetime
        task.completado_em = datetime.utcnow()
        db.commit()
    return {"success": True, "status": task.status}


@router.delete("/sessions/{session_id}/reset")
async def resetar_sessao(session_id: int, db: Session = Depends(get_db)):
    """
    Limpa TODOS os dados de uma coding session sem deletá-la:
    - Todas as tarefas (coding_tasks) e seus históricos
    - Memória persistente
    - Arquivos do workspace (limpa o diretório)
    - Shells ativos
    Preserva a sessão, o agente e as configurações.
    """
    cs = CodingService.obter_sessao(db, session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="CodingSession não encontrada")

    import os, shutil, logging
    logger = logging.getLogger(__name__)

    # 1) Matar shells ativos de todas as tarefas
    tarefas = CodingService.listar_tarefas(db, session_id, limit=9999)
    shells_killed = 0
    for task in tarefas:
        for sid, info in (task.shell_sessions or {}).items():
            if info.get("status") == "running":
                try:
                    from internal_sandbox.shell_service import ShellService
                    await ShellService.kill_session(sid)
                    shells_killed += 1
                except Exception:
                    pass

    # 2) Deletar todas as tarefas
    tasks_deleted = db.query(CodingTask).filter(
        CodingTask.coding_session_id == session_id
    ).delete(synchronize_session="fetch")

    # 3) Limpar memória
    cs.memory_content = ""

    db.commit()

    # 4) Calcular workspace RAIZ (pode ter sido alterado por project_init/change_workspace)
    # O workspace raiz é sempre: {SANDBOX_ROOT}/coding_{agente_id}/
    workspace_atual = cs.workspace_path or ""
    sandbox_root = os.environ.get(
        "INTERNAL_SANDBOX_ROOT",
        os.path.join(os.path.expanduser("~"), "fluxi_sandbox"),
    )
    workspace_raiz = os.path.join(sandbox_root, f"coding_{cs.agente_id}")

    # Limpa AMBOS: workspace raiz e workspace atual (se diferente)
    dirs_para_limpar = {workspace_raiz}
    if workspace_atual and os.path.isdir(workspace_atual):
        dirs_para_limpar.add(workspace_atual)

    files_removed = 0
    for ws_dir in dirs_para_limpar:
        if ws_dir and os.path.isdir(ws_dir):
            for item in os.listdir(ws_dir):
                item_path = os.path.join(ws_dir, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                    files_removed += 1
                except Exception as e:
                    logger.warning(f"Erro ao remover {item_path}: {e}")

    # 5) Resetar workspace_path para o raiz (desfaz change_workspace/project_init)
    cs.workspace_path = workspace_raiz
    db.commit()

    # Recria o diretório raiz vazio
    os.makedirs(workspace_raiz, exist_ok=True)

    logger.info(
        f"[CODING-RESET] session={session_id}: "
        f"{tasks_deleted} tarefas deletadas, "
        f"{shells_killed} shells encerrados, "
        f"{files_removed} itens removidos do workspace, "
        f"workspace resetado para {workspace_raiz}, "
        f"memória limpa"
    )

    return {
        "success": True,
        "session_id": session_id,
        "tasks_deleted": tasks_deleted,
        "shells_killed": shells_killed,
        "workspace_files_removed": files_removed,
        "workspace_reset_to": workspace_raiz,
        "memory_cleared": True,
    }


@router.delete("/shell/{session_id}")
async def matar_shell(session_id: str):
    """Encerra um processo shell em background específico."""
    from internal_sandbox.shell_service import ShellService
    try:
        await ShellService.kill_session(session_id)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
# MENSAGEM (API direta — sem WhatsApp)
# ══════════════════════════════════════════════════════════

@router.post("/chat", response_model=CodingMensagemResposta)
async def enviar_mensagem(
    payload: CodingMensagemEnviar,
    db: Session = Depends(get_db),
):
    """
    Envia uma mensagem diretamente ao coding agent via API REST.
    Retorna quando a tarefa for concluída (processamento síncrono).
    """
    resultado = await CodingService.processar_mensagem(
        db=db,
        coding_session_id=payload.coding_session_id,
        mensagem=payload.mensagem,
        telefone_cliente=payload.telefone_cliente,
        task_id=payload.task_id,
    )

    if "erro" in resultado:
        raise HTTPException(status_code=400, detail=resultado["erro"])

    return CodingMensagemResposta(**resultado)


# ══════════════════════════════════════════════════════════
# CHAT ASSÍNCRONO (browser) — retorna task_id imediatamente
# ══════════════════════════════════════════════════════════

@router.post("/chat-async", status_code=202)
async def enviar_mensagem_async(
    payload: CodingMensagemEnviar,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Envia mensagem ao coding agent e retorna task_id imediatamente.
    O processamento ocorre em background via BackgroundTasks.
    """
    cs = CodingService.obter_sessao(db, payload.coding_session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="CodingSession não encontrada")

    from agente.agente_model import Agente as AgenteModel
    agente = db.query(AgenteModel).filter(AgenteModel.id == cs.agente_id).first()
    if not agente:
        raise HTTPException(status_code=400, detail="Agente de coding não encontrado")

    # Cria (ou recupera) a tarefa imediatamente para ter o task_id
    if payload.task_id:
        task = CodingService.obter_tarefa(db, payload.task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    else:
        titulo = payload.mensagem[:80].strip() if payload.mensagem else "Nova tarefa"
        task = CodingService.criar_tarefa(
            db,
            coding_session_id=cs.id,
            titulo=titulo,
            objetivo=payload.mensagem,
            telefone_cliente=payload.telefone_cliente,
        )

    task.status = "running"
    db.commit()
    task_id = task.id

    from coding_agent.coding_stream import cleanup_queue, emit_llm_delta, ensure_queue
    ensure_queue(task_id)

    async def _processar_em_background():
        import traceback
        import logging
        from database import SessionLocal
        from coding_agent.coding_stream import emit_llm_delta, emit_status

        bg_log = logging.getLogger(__name__)
        bg_db = SessionLocal()
        bg_task = None
        try:
            # Carrega TODOS os objetos na sessão fresca — nunca reutiliza session da request
            bg_task = CodingService.obter_tarefa(bg_db, task_id)
            if not bg_task:
                bg_log.error("[CODING-BG task=%d] Tarefa não encontrada na nova sessão", task_id)
                return

            bg_cs = CodingService.obter_sessao(bg_db, bg_task.coding_session_id)
            if not bg_cs:
                bg_log.error("[CODING-BG task=%d] CodingSession não encontrada", task_id)
                bg_task.status = "failed"
                bg_task.error = "CodingSession não encontrada"
                bg_db.commit()
                return

            bg_agente = bg_db.query(AgenteModel).filter(AgenteModel.id == bg_cs.agente_id).first()
            if not bg_agente:
                bg_log.error("[CODING-BG task=%d] Agente não encontrado", task_id)
                bg_task.status = "failed"
                bg_task.error = "Agente não encontrado"
                bg_db.commit()
                return

            bg_log.info("[CODING-BG task=%d] Iniciando execução — mensagem=%d chars", task_id, len(payload.mensagem))

            # Sem streaming token-a-token: a resposta é emitida completa
            # quando o loop finaliza. Eventos de tool_start/tool_result/status
            # continuam em tempo real via emit_* dentro do _executar_loop.

            # Watchdog externo: se o loop inteiro demorar mais que max_timeout, cancela
            max_iter = bg_cs.max_iteracoes or 30
            # 5 min por iteração estimada + 60s de folga
            total_timeout = max_iter * 300 + 60

            try:
                await asyncio.wait_for(
                    CodingService._executar_loop(
                        db=bg_db,
                        coding_session=bg_cs,
                        task=bg_task,
                        agente=bg_agente,
                        mensagem_usuario=payload.mensagem,
                        # on_llm_text_delta removido — sem streaming token-a-token
                    ),
                    timeout=float(total_timeout),
                )
            except asyncio.TimeoutError:
                msg_to = f"⏱️ Tarefa interrompida por timeout global ({total_timeout}s)."
                bg_log.warning("[CODING-BG task=%d] %s", task_id, msg_to)
                await emit_status(task_id, msg_to)
                bg_task.status = "failed"
                bg_task.error = msg_to
                bg_db.commit()
                return

            from datetime import datetime
            # Recarrega para pegar status mais recente (pode ter sido cancelada)
            bg_db.refresh(bg_task)
            if bg_task.status == "running":
                bg_task.status = "completed"
                bg_task.completado_em = datetime.utcnow()
                bg_db.commit()
                bg_log.info("[CODING-BG task=%d] Concluída com sucesso", task_id)

        except Exception as e:
            traceback.print_exc()
            bg_log.exception("[CODING-BG task=%d] Erro não tratado: %s", task_id, e)
            if bg_task is not None:
                try:
                    bg_task.status = "failed"
                    bg_task.error = f"{type(e).__name__}: {str(e)[:500]}"
                    bg_db.commit()
                except Exception:
                    pass
        finally:
            cleanup_queue(task_id)
            try:
                bg_db.close()
            except Exception:
                pass

    # Adiciona à fila de background tasks do FastAPI
    background_tasks.add_task(_processar_em_background)

    return {
        "task_id": task_id,
        "coding_session_id": cs.id,
        "titulo": task.titulo,
        "status": "running",
        "ws_url": f"/ws/coding/task/{task_id}",
    }


# ══════════════════════════════════════════════════════════
# MODELOS DISPONÍVEIS PARA O CODING AGENT
# ══════════════════════════════════════════════════════════

@router.get("/sessions/{session_id}/files")
def listar_arquivos_sessao(session_id: int, db: Session = Depends(get_db)):
    """Retorna os arquivos e diretórios do workspace atual da sessão."""
    cs = CodingService.obter_sessao(db, session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    
    workspace = cs.workspace_path or ""
    if cs.workspace_mode == "sandbox" or not workspace:
        import os
        base = os.environ.get(
            "INTERNAL_SANDBOX_ROOT",
            os.path.join(os.path.expanduser("~"), "fluxi_sandbox"),
        )
        workspace = os.path.join(base, f"coding_{cs.agente_id}")
    
    import os
    try:
        os.makedirs(workspace, exist_ok=True)
    except Exception:
        pass

    from internal_sandbox.file_service import FileService
    res = FileService.list_path(workspace, show_hidden=True)
    if "error" in res:
        # Se ainda der erro, tenta listar pelo menos o conteúdo do root padrão
        return {"files": [], "error": res["error"], "workspace": workspace}
    return {"files": res.get("files", []), "workspace": workspace}


@router.get("/sessions/{session_id}/file")
def ler_arquivo_sessao(session_id: int, path: str, db: Session = Depends(get_db)):
    """Retorna o conteúdo de um arquivo do workspace."""
    cs = CodingService.obter_sessao(db, session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    
    workspace = cs.workspace_path or ""
    if cs.workspace_mode == "sandbox" or not workspace:
        import os
        base = os.environ.get(
            "INTERNAL_SANDBOX_ROOT",
            os.path.join(os.path.expanduser("~"), "fluxi_sandbox"),
        )
        workspace = os.path.join(base, f"coding_{cs.agente_id}")
    
    import os
    full_path = os.path.normpath(os.path.join(workspace, path))
    # Segurança básica para não sair do workspace
    if not full_path.startswith(os.path.normpath(workspace)):
        raise HTTPException(status_code=403, detail="Acesso negado")
        
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
        
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "path": path}
    except UnicodeDecodeError:
        return {"error": "Arquivo binário ou codificação não suportada", "path": path}
    except Exception as e:
        return {"error": str(e), "path": path}


@router.get("/modelos")
async def listar_modelos_disponiveis(db: Session = Depends(get_db)):
    """
    Lista todos os modelos disponíveis em provedores ativos.
    Usado pelo frontend para popular o seletor de modelos.
    """
    import httpx
    from llm_providers.llm_providers_service import ProvedorLLMService
    from config.config_service import ConfiguracaoService

    provedores = ProvedorLLMService.listar_ativos(db)
    modelos = []

    for p in provedores:
        modelos_db = ProvedorLLMService.obter_modelos(db, p.id)
        for m in modelos_db:
            modelos.append({
                "id": m.nome if hasattr(m, "nome") else str(m),
                "nome": m.nome if hasattr(m, "nome") else str(m),
                "provedor": p.nome,
                "provedor_id": p.id,
                "tipo": "local",
            })

    # Buscar modelos do OpenRouter dinamicamente via API
    api_key = ConfiguracaoService.obter_valor(db, "openrouter_api_key")
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    for modelo_data in data.get("data", []):
                        modelo_id = modelo_data.get("id", "")
                        modelo_nome = modelo_data.get("name", modelo_id)
                        modelos.append({
                            "id": modelo_id,
                            "nome": modelo_nome,
                            "provedor": "OpenRouter",
                            "tipo": "openrouter",
                        })
        except Exception as e:
            logger.warning("Erro ao buscar modelos do OpenRouter: %s", e)

    return {"modelos": modelos, "total": len(modelos)}


# ══════════════════════════════════════════════════════════
# CRIAÇÃO DE AGENTE DE CODING PADRÃO
# ══════════════════════════════════════════════════════════

@router.post("/setup/{sessao_id}", status_code=201)
def criar_agente_coding_padrao(sessao_id: int, db: Session = Depends(get_db)):
    """
    Cria o Agente de Coding padrão para uma sessão WhatsApp e retorna
    o agente + coding_session criados.
    """
    try:
        agente, cs = CodingService.criar_agente_coding_padrao(db, sessao_id)
        return {
            "agente_id": agente.id,
            "agente_nome": agente.nome,
            "coding_session_id": cs.id,
            "workspace_path": cs.workspace_path,
            "routing_prefix": cs.routing_prefix,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
