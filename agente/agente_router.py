"""
Rotas da API para agentes.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from database import get_db
from agente.agente_schema import (
    AgenteResposta,
    AgenteCriar,
    AgenteAtualizar,
    AgenteFerramentasAtualizar
)
from agente.agente_service import AgenteService
from log.log_service import fluxi_log

router = APIRouter(prefix="/api/agentes", tags=["Agentes"])


@router.get("/llm-opcoes")
async def obter_opcoes_llm(db: Session = Depends(get_db)):
    """Retorna provedores LLM disponíveis, modelos e valores padrão para o formulário do agente."""
    from llm_providers.llm_providers_service import ProvedorLLMService
    from config.config_service import ConfiguracaoService

    # Provedores locais ativos
    provedores = ProvedorLLMService.listar_ativos(db)
    provedores_list = []
    modelos_por_provedor = {}

    for p in provedores:
        provedores_list.append({
            "id": p.id,
            "nome": p.nome,
            "tipo": "local",
            "base_url": str(p.base_url),
        })
        modelos = ProvedorLLMService.obter_modelos(db, p.id)
        modelos_por_provedor[str(p.id)] = [
            {
                "id": m.modelo_id,
                "nome": m.nome,
                "contexto": m.contexto,
                "suporta_imagens": m.suporta_imagens,
                "suporta_ferramentas": m.suporta_ferramentas,
            }
            for m in modelos
        ]

    # OpenRouter
    openrouter_disponivel = bool(ConfiguracaoService.obter_valor(db, "openrouter_api_key"))
    from llm_providers.llm_integration_service import LLMIntegrationService
    openrouter_modelos = (await LLMIntegrationService.obter_modelos_disponiveis(db)).get("openrouter", []) if openrouter_disponivel else []

    # Valores globais padrão
    config_padrao = {
        "temperatura": ConfiguracaoService.obter_valor(db, "openrouter_temperatura", 0.7),
        "max_tokens": ConfiguracaoService.obter_valor(db, "openrouter_max_tokens", 2000),
        "top_p": ConfiguracaoService.obter_valor(db, "openrouter_top_p", 1.0),
        "frequency_penalty": ConfiguracaoService.obter_valor(db, "openrouter_frequency_penalty", 0.0),
        "presence_penalty": ConfiguracaoService.obter_valor(db, "openrouter_presence_penalty", 0.0),
        "modelo_padrao": ConfiguracaoService.obter_valor(db, "openrouter_modelo_padrao", "google/gemini-3.1-flash-lite-preview"),
    }

    return {
        "provedores": provedores_list,
        "modelos_por_provedor": modelos_por_provedor,
        "openrouter_disponivel": openrouter_disponivel,
        "openrouter_modelos": openrouter_modelos,
        "config_padrao": config_padrao,
    }


@router.get("/", response_model=List[AgenteResposta])
def listar_agentes(
    sessao_id: Optional[int] = Query(None),
    apenas_ativos: bool = Query(False),
    db: Session = Depends(get_db)
):
    """Lista todos os agentes."""
    if sessao_id is not None:
        if apenas_ativos:
            return AgenteService.listar_por_sessao_ativos(db, sessao_id)
        return AgenteService.listar_por_sessao(db, sessao_id)
    return AgenteService.listar_todos(db)


@router.get("/{agente_id}", response_model=AgenteResposta)
def obter_agente(agente_id: int, db: Session = Depends(get_db)):
    """Obtém um agente específico."""
    agente = AgenteService.obter_por_id(db, agente_id)
    if not agente:
        raise HTTPException(status_code=404, detail="Agente não encontrado")
    return agente


@router.post("/", response_model=AgenteResposta)
def criar_agente(agente: AgenteCriar, db: Session = Depends(get_db)):
    """Cria um novo agente."""
    try:
        return AgenteService.criar(db, agente)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{agente_id}", response_model=AgenteResposta)
def atualizar_agente(
    agente_id: int,
    agente: AgenteAtualizar,
    db: Session = Depends(get_db)
):
    """Atualiza um agente existente."""
    try:
        agente_atualizado = AgenteService.atualizar(db, agente_id, agente)
        if not agente_atualizado:
            raise HTTPException(status_code=404, detail="Agente não encontrado")
        return agente_atualizado
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{agente_id}")
def deletar_agente(agente_id: int, db: Session = Depends(get_db)):
    """Deleta um agente."""
    sucesso = AgenteService.deletar(db, agente_id)
    if not sucesso:
        raise HTTPException(status_code=404, detail="Agente não encontrado")
    return {"mensagem": "Agente deletado com sucesso"}


@router.post("/{agente_id}/ferramentas")
def atualizar_ferramentas_agente(
    agente_id: int,
    ferramentas: AgenteFerramentasAtualizar,
    db: Session = Depends(get_db)
):
    """Atualiza as ferramentas de um agente (máximo 20)."""
    try:
        AgenteService.atualizar_ferramentas(db, agente_id, ferramentas.ferramentas)
        return {"mensagem": "Ferramentas atualizadas com sucesso"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{agente_id}/ferramentas")
def listar_ferramentas_agente(agente_id: int, db: Session = Depends(get_db)):
    """Lista as ferramentas ativas de um agente."""
    ferramentas = AgenteService.listar_ferramentas(db, agente_id)
    return ferramentas


@router.post("/{agente_id}/internal-sandbox")
def toggle_internal_sandbox_agente(
    agente_id: int,
    request: dict,
    db: Session = Depends(get_db)
):
    """Ativa ou desativa o sandbox interno de um agente."""
    agente = AgenteService.obter_por_id(db, agente_id)
    if not agente:
        raise HTTPException(status_code=404, detail="Agente não encontrado")

    ativo = request.get("internal_sandbox_ativo", False)
    agente.internal_sandbox_ativo = ativo

    if not ativo:
        try:
            from internal_sandbox.internal_service import InternalService
            InternalService.desconectar(agente_id)
        except Exception as e:
            fluxi_log.warning("agente", "sandbox", f"Falha ao desconectar sandbox do agente {agente_id}: {e}", extra={
                "agente_id": agente_id, "erro": str(e),
            })

    db.commit()
    db.refresh(agente)
    status = "ativado" if ativo else "desativado"
    return {
        "mensagem": f"Sandbox interno {status} com sucesso",
        "internal_sandbox_ativo": agente.internal_sandbox_ativo,
    }


@router.post("/{agente_id}/vincular-treinamento")
def vincular_treinamento_agente(
    agente_id: int,
    request: dict,
    db: Session = Depends(get_db)
):
    """Vincula ou desvincula um treinamento (RAG) de um agente."""
    try:
        rag_id = request.get("rag_id")
        
        # Validar que o agente existe
        agente = AgenteService.obter_por_id(db, agente_id)
        if not agente:
            raise HTTPException(status_code=404, detail="Agente não encontrado")
        
        # Se rag_id foi fornecido, validar que o RAG existe
        if rag_id is not None and rag_id != "":
            from rag.rag_service import RAGService
            rag = RAGService.obter_por_id(db, int(rag_id))
            if not rag:
                raise HTTPException(status_code=404, detail="RAG não encontrado")
        else:
            rag_id = None
        
        # Atualizar o agente com o novo rag_id
        AgenteService.atualizar(db, agente_id, AgenteAtualizar(rag_id=rag_id))
        
        if rag_id:
            return {"mensagem": "Treinamento vinculado com sucesso"}
        else:
            return {"mensagem": "Treinamento desvinculado com sucesso"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
