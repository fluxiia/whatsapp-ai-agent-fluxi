"""
Rotas da API para clientes MCP.
"""
from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from database import get_db
from mcp_client.mcp_schema import (
    MCPClientCriar,
    MCPClientAtualizar,
    MCPClientResposta,
    MCPClientComTools,
    MCPToolResposta,
    MCPConexaoStatus,
    MCPPresetResposta,
    MCPPresetAplicarRequest,
    MCPOneClickRequest
)
from mcp_client.mcp_service import MCPService

router = APIRouter(prefix="/api/mcp", tags=["MCP Clients"])


@router.get("/presets", response_model=List[MCPPresetResposta])
def listar_presets_mcp():
    """Lista presets MCP disponíveis."""
    return MCPService.listar_presets_disponiveis()


@router.post("/presets/aplicar", response_model=MCPClientResposta)
async def aplicar_preset_mcp(
    payload: MCPPresetAplicarRequest,
    db: Session = Depends(get_db)
):
    """Aplica um preset e cria um novo cliente MCP."""
    try:
        db_mcp = MCPService.aplicar_preset(db, payload)

        if db_mcp.ativo:
            resultado_conexao = await MCPService.conectar_cliente(db, db_mcp.id)
            if not resultado_conexao.get("sucesso"):
                db_mcp.ultimo_erro = resultado_conexao.get("mensagem")
                db.commit()

        db.refresh(db_mcp)
        tools_count = len(MCPService.listar_tools_ativas(db, db_mcp.id))

        return MCPClientResposta(
            **db_mcp.__dict__,
            total_tools=tools_count
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao aplicar preset MCP: {str(e)}")


@router.post("/one-click/install")
async def instalar_mcp_one_click(
    request: Request,
    agente_id: int = Form(...),
    nome: str = Form(None),
    descricao: str = Form(None),
    json_config: str = Form(...),
    db: Session = Depends(get_db)
):
    """Instala um servidor MCP via JSON one-click."""
    try:
        # Validar dados básicos
        if not agente_id:
            raise HTTPException(status_code=400, detail="agente_id é obrigatório")
        
        if not json_config:
            raise HTTPException(status_code=400, detail="json_config é obrigatório")
        
        # Criar payload manualmente
        payload_data = {
            "agente_id": agente_id,
            "nome": nome,
            "descricao": descricao,
            "json_config": json_config
        }
        
        from mcp_client.mcp_schema import MCPOneClickRequest
        try:
            payload = MCPOneClickRequest(**payload_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro de validação: {str(e)}")
            
        db_mcp = MCPService.aplicar_one_click(db, payload)

        if db_mcp.ativo:
            resultado_conexao = await MCPService.conectar_cliente(db, db_mcp.id)
            if not resultado_conexao.get("sucesso"):
                db_mcp.ultimo_erro = resultado_conexao.get("mensagem")
                db.commit()

        db.refresh(db_mcp)
        tools_count = len(MCPService.listar_tools_ativas(db, db_mcp.id))

        # Redirecionar para a lista de MCP clients
        return RedirectResponse(url=f"/mcp/agente/{agente_id}/clients", status_code=303)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao instalar MCP one-click: {str(e)}")


@router.get("/agente/{agente_id}/clients", response_model=List[MCPClientResposta])
def listar_mcp_clients(agente_id: int, db: Session = Depends(get_db)):
    """Lista clientes MCP de um agente."""
    mcp_clients = MCPService.listar_por_agente(db, agente_id)
    
    # Adicionar contagem de tools
    resultado = []
    for mcp_client in mcp_clients:
        tools_count = len(MCPService.listar_tools_ativas(db, mcp_client.id))
        
        mcp_dict = {
            **mcp_client.__dict__,
            "total_tools": tools_count
        }
        resultado.append(MCPClientResposta(**mcp_dict))
    
    return resultado


@router.get("/clients/{mcp_client_id}", response_model=MCPClientComTools)
def obter_mcp_client(mcp_client_id: int, db: Session = Depends(get_db)):
    """Obtém detalhes de um cliente MCP com suas tools."""
    mcp_client = MCPService.obter_por_id(db, mcp_client_id)
    if not mcp_client:
        raise HTTPException(status_code=404, detail="Cliente MCP não encontrado")
    
    tools = MCPService.listar_tools_ativas(db, mcp_client_id)
    
    return MCPClientComTools(
        **mcp_client.__dict__,
        total_tools=len(tools),
        tools=[MCPToolResposta.model_validate(t) for t in tools]
    )


@router.post("/agente/{agente_id}/clients", response_model=MCPClientResposta)
async def criar_mcp_client(
    agente_id: int,
    mcp_client: MCPClientCriar,
    db: Session = Depends(get_db)
):
    """
    Cria um novo cliente MCP e tenta conectar.
    Máximo de 5 clientes MCP por agente.
    """
    try:
        # Validar que agente_id corresponde
        if mcp_client.agente_id != agente_id:
            raise HTTPException(status_code=400, detail="agente_id não corresponde")
        
        # Criar cliente
        db_mcp = MCPService.criar(db, mcp_client)
        
        # Tentar conectar
        if mcp_client.ativo:
            resultado_conexao = await MCPService.conectar_cliente(db, db_mcp.id)
            if not resultado_conexao.get("sucesso"):
                # Atualizar erro mas não falhar a criação
                db_mcp.ultimo_erro = resultado_conexao.get("mensagem")
                db.commit()
        
        # Recarregar do banco
        db.refresh(db_mcp)
        
        tools_count = len(MCPService.listar_tools_ativas(db, db_mcp.id))
        
        return MCPClientResposta(
            **db_mcp.__dict__,
            total_tools=tools_count
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao criar cliente MCP: {str(e)}")


@router.put("/clients/{mcp_client_id}", response_model=MCPClientResposta)
def atualizar_mcp_client(
    mcp_client_id: int,
    mcp_client: MCPClientAtualizar,
    db: Session = Depends(get_db)
):
    """Atualiza um cliente MCP."""
    db_mcp = MCPService.atualizar(db, mcp_client_id, mcp_client)
    if not db_mcp:
        raise HTTPException(status_code=404, detail="Cliente MCP não encontrado")
    
    tools_count = len(MCPService.listar_tools_ativas(db, mcp_client_id))
    
    return MCPClientResposta(
        **db_mcp.__dict__,
        total_tools=tools_count
    )


@router.delete("/clients/{mcp_client_id}")
def deletar_mcp_client(mcp_client_id: int, db: Session = Depends(get_db)):
    """Deleta um cliente MCP."""
    sucesso = MCPService.deletar(db, mcp_client_id)
    if not sucesso:
        raise HTTPException(status_code=404, detail="Cliente MCP não encontrado")
    
    return {"mensagem": "Cliente MCP deletado com sucesso"}


@router.post("/clients/{mcp_client_id}/conectar", response_model=MCPConexaoStatus)
async def conectar_mcp_client(mcp_client_id: int, db: Session = Depends(get_db)):
    """Conecta ou reconecta um cliente MCP."""
    try:
        resultado = await MCPService.conectar_cliente(db, mcp_client_id)
        
        # Recarregar cliente do banco
        db_mcp = MCPService.obter_por_id(db, mcp_client_id)
        if not db_mcp:
            raise HTTPException(status_code=404, detail="Cliente MCP não encontrado")
        
        tools_count = len(MCPService.listar_tools_ativas(db, mcp_client_id))
        
        return MCPConexaoStatus(
            mcp_client_id=mcp_client_id,
            conectado=db_mcp.conectado,
            server_name=db_mcp.server_name,
            server_version=db_mcp.server_version,
            total_tools=tools_count,
            mensagem=resultado.get("mensagem", "")
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao conectar: {str(e)}")


@router.post("/clients/{mcp_client_id}/desconectar")
async def desconectar_mcp_client(mcp_client_id: int, db: Session = Depends(get_db)):
    """Desconecta um cliente MCP."""
    db_mcp = MCPService.obter_por_id(db, mcp_client_id)
    if not db_mcp:
        raise HTTPException(status_code=404, detail="Cliente MCP não encontrado")
    
    await MCPService.desconectar_cliente(mcp_client_id)
    
    # Atualizar banco
    db_mcp.conectado = False
    db.commit()
    
    return {"mensagem": "Cliente MCP desconectado"}


@router.post("/clients/{mcp_client_id}/sincronizar")
async def sincronizar_tools_mcp(mcp_client_id: int, db: Session = Depends(get_db)):
    """Sincroniza tools de um cliente MCP."""
    try:
        total_tools = await MCPService.sincronizar_tools(db, mcp_client_id)
        return {
            "mensagem": f"{total_tools} tools sincronizadas com sucesso",
            "total_tools": total_tools
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao sincronizar: {str(e)}")


@router.get("/clients/{mcp_client_id}/tools", response_model=List[MCPToolResposta])
def listar_tools_mcp(mcp_client_id: int, db: Session = Depends(get_db)):
    """Lista tools de um cliente MCP."""
    tools = MCPService.listar_tools_ativas(db, mcp_client_id)
    return [MCPToolResposta.model_validate(t) for t in tools]


@router.get("/registry")
async def buscar_registry_mcp(
    q: str = "",
    page: int = 1,
    page_size: int = 20
):
    """Busca servidores MCP no registry público Smithery (https://registry.smithery.ai)."""
    resultado = await MCPService.buscar_no_registry(q=q, page=page, page_size=page_size)
    return resultado


@router.get("/registry/apikey")
def obter_smithery_apikey(db: Session = Depends(get_db)):
    """Retorna a Smithery API Key salva (parcialmente mascarada)."""
    from config.config_service import ConfiguracaoService
    chave = ConfiguracaoService.obter_valor(db, "smithery_api_key", "")
    return {"configurada": bool(chave), "chave": chave}


@router.post("/registry/apikey")
async def salvar_smithery_apikey(
    request: Request,
    db: Session = Depends(get_db)
):
    """Salva a Smithery API Key nas configurações do sistema."""
    from config.config_service import ConfiguracaoService
    body = await request.json()
    apikey = (body.get("apikey") or "").strip()
    if not apikey:
        raise HTTPException(status_code=400, detail="apikey não pode ser vazia")
    ConfiguracaoService.definir_valor(db, "smithery_api_key", apikey)
    return {"sucesso": True}
