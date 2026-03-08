"""
Serviço para gerenciar clientes MCP e executar tools.
"""
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
import asyncio
import time
import json
from datetime import datetime

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp import types

from mcp_client.mcp_client_model import MCPClient, TransportType
from mcp_client.mcp_tool_model import MCPTool
from mcp_client.mcp_schema import (
    MCPClientCriar,
    MCPClientAtualizar,
    MCPPresetAplicarRequest,
    MCPPresetResposta,
    MCPOneClickRequest
)
from mcp_client.mcp_presets import listar_presets, obter_preset
from config.config_service import ConfiguracaoService


class MCPService:
    """Serviço para gerenciar clientes MCP."""
    
    # Sessões ativas de clientes MCP (em memória)
    _active_sessions: Dict[int, ClientSession] = {}
    _session_contexts: Dict[int, Any] = {}  # Context managers
    _session_locks: Dict[int, asyncio.Lock] = {}
    
    @staticmethod
    def _get_lock(mcp_client_id: int) -> asyncio.Lock:
        """Obtém ou recria um lock compatível com o event loop atual."""
        lock = MCPService._session_locks.get(mcp_client_id)
        if lock is not None:
            try:
                # Testa se o lock é compatível com o loop atual
                asyncio.get_running_loop()
                # Tenta criar um future no lock para validar
                if hasattr(lock, '_loop') and lock._loop is not None:
                    if lock._loop is not asyncio.get_running_loop():
                        raise RuntimeError("wrong loop")
                return lock
            except RuntimeError:
                # Lock vinculado a outro event loop — recriar
                pass
        new_lock = asyncio.Lock()
        MCPService._session_locks[mcp_client_id] = new_lock
        return new_lock
    
    @staticmethod
    def listar_por_agente(db: Session, agente_id: int) -> List[MCPClient]:
        """Lista todos os clientes MCP de um agente."""
        return db.query(MCPClient).filter(MCPClient.agente_id == agente_id).all()
    
    @staticmethod
    def listar_ativos_por_agente(db: Session, agente_id: int) -> List[MCPClient]:
        """Lista clientes MCP ativos de um agente."""
        return db.query(MCPClient).filter(
            MCPClient.agente_id == agente_id,
            MCPClient.ativo == True
        ).all()
    
    @staticmethod
    def obter_por_id(db: Session, mcp_client_id: int) -> Optional[MCPClient]:
        """Obtém um cliente MCP pelo ID."""
        return db.query(MCPClient).filter(MCPClient.id == mcp_client_id).first()
    
    @staticmethod
    def contar_por_agente(db: Session, agente_id: int) -> int:
        """Conta quantos clientes MCP um agente possui."""
        return db.query(MCPClient).filter(MCPClient.agente_id == agente_id).count()
    
    @staticmethod
    def criar(db: Session, mcp_client: MCPClientCriar) -> MCPClient:
        """Cria um novo cliente MCP."""
        # Validar limite de MCP clients por agente (configurável)
        max_clients = ConfiguracaoService.obter_valor(db, "mcp_max_clients_por_agente", 5)
        total_existentes = MCPService.contar_por_agente(db, mcp_client.agente_id)
        if total_existentes >= max_clients:
            raise ValueError(f"Um agente pode ter no máximo {max_clients} clientes MCP")

        data = mcp_client.model_dump()
        db_mcp = MCPClient(**data)
        db.add(db_mcp)
        db.commit()
        db.refresh(db_mcp)
        return db_mcp
    
    @staticmethod
    def atualizar(db: Session, mcp_client_id: int, mcp_client: MCPClientAtualizar) -> Optional[MCPClient]:
        """Atualiza um cliente MCP."""
        db_mcp = MCPService.obter_por_id(db, mcp_client_id)
        if not db_mcp:
            return None

        update_data = mcp_client.model_dump(exclude_unset=True)
        for campo, valor in update_data.items():
            setattr(db_mcp, campo, valor)

        db.commit()
        db.refresh(db_mcp)
        return db_mcp

    @staticmethod
    def deletar(db: Session, mcp_client_id: int) -> bool:
        """Deleta um cliente MCP."""
        db_mcp = MCPService.obter_por_id(db, mcp_client_id)
        if not db_mcp:
            return False
        
        # Desconectar se estiver conectado (remover da memória)
        if mcp_client_id in MCPService._active_sessions:
            try:
                # Remover da memória (as sessões serão fechadas automaticamente)
                del MCPService._active_sessions[mcp_client_id]
            except KeyError:
                pass
        
        if mcp_client_id in MCPService._session_contexts:
            try:
                del MCPService._session_contexts[mcp_client_id]
            except KeyError:
                pass
        
        # Deletar do banco (cascade vai deletar as tools)
        db.delete(db_mcp)
        db.commit()
        return True

    # Presets -----------------------------------------------------------------

    @staticmethod
    def listar_presets_disponiveis() -> List[MCPPresetResposta]:
        """Retorna lista de presets convertidos para schema de resposta."""

        presets = listar_presets()
        resposta = []
        for preset in presets:
            resposta.append(
                MCPPresetResposta(
                    key=preset.key,
                    name=preset.name,
                    description=preset.description,
                    transport_type=preset.transport_type.value,
                    tags=preset.tags,
                    documentation_url=preset.documentation_url,
                    notes=preset.notes,
                    command=preset.command,
                    args=preset.args,
                    url=preset.url,
                    env=preset.env,
                    headers=preset.headers,
                    inputs=[
                        {
                            "id": input_field.id,
                            "label": input_field.label,
                            "description": input_field.description,
                            "secret": input_field.secret,
                        }
                        for input_field in preset.inputs
                    ],
                )
            )
        return resposta

    @staticmethod
    def aplicar_preset(db: Session, payload: MCPPresetAplicarRequest) -> MCPClient:
        """Cria um MCP Client a partir de um preset."""

        preset = obter_preset(payload.preset_key)
        if not preset:
            raise ValueError("Preset não encontrado")

        inputs = payload.inputs or {}
        # Validar inputs obrigatórios
        for input_field in preset.inputs:
            if inputs.get(input_field.id) in (None, ""):
                raise ValueError(f"Campo obrigatório: {input_field.label}")

        nome = payload.nome or preset.name
        descricao = payload.descricao or preset.description

        criar_schema = MCPClientCriar(
            agente_id=payload.agente_id,
            nome=nome,
            descricao=descricao,
            preset_key=preset.key,
            preset_inputs=inputs,
            transport_type=preset.transport_type.value,
            command=preset.command,
            args=preset.args,
            env_vars={key: valor for key, valor in preset.env.items()},
            url=preset.url,
            headers=preset.headers or None,
            ativo=True,
        )

        # Aplicar inputs ao env/headers/url se necessário
        if criar_schema.url:
            criar_schema.url = MCPService._substituir_inputs(criar_schema.url, inputs)

        if criar_schema.env_vars:
            for key, value in list(criar_schema.env_vars.items()):
                criar_schema.env_vars[key] = MCPService._substituir_inputs(value, inputs)

        if criar_schema.headers:
            for key, value in list(criar_schema.headers.items()):
                criar_schema.headers[key] = MCPService._substituir_inputs(value, inputs)

        return MCPService.criar(db, criar_schema)

    @staticmethod
    def aplicar_one_click(db: Session, payload: MCPOneClickRequest) -> MCPClient:
        """Cria um MCP Client a partir de um JSON one-click."""

        # Parse JSON
        try:
            config = json.loads(payload.json_config)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON inválido: {str(e)}")

        # Validar estrutura básica
        if "mcpServers" not in config:
            raise ValueError("JSON deve conter 'mcpServers' como chave raiz")

        mcp_servers = config["mcpServers"]
        if not isinstance(mcp_servers, dict) or not mcp_servers:
            raise ValueError("'mcpServers' deve ser um objeto não vazio")

        # Pegar primeiro servidor (suporta apenas um por configuração)
        server_name = next(iter(mcp_servers.keys()))
        server_config = mcp_servers[server_name]

        # Validar campos obrigatórios
        if not isinstance(server_config, dict):
            raise ValueError(f"Configuração do servidor '{server_name}' deve ser um objeto")

        # Determinar transport type
        transport_type = "stdio"  # default
        command = server_config.get("command")
        args = server_config.get("args", [])
        url = server_config.get("url")
        server_url = server_config.get("serverUrl")  # Para compatibilidade com SSE

        # Usar serverUrl se disponível (formato SSE)
        if server_url:
            url = server_url
            transport_type = "sse"
        elif url:
            # Determinar se é SSE ou HTTP baseado na URL
            if "/sse" in url:
                transport_type = "sse"
            else:
                transport_type = "streamable-http"
        elif command:
            transport_type = "stdio"
        else:
            raise ValueError("Servidor deve ter 'command', 'url' ou 'serverUrl'")

        # Extrair env e headers
        env_vars = server_config.get("env", {})
        headers = server_config.get("headers", {})

        # Nome e descrição
        nome = payload.nome or server_name
        descricao = payload.descricao or f"Instalado via one-click: {server_name}"

        # Criar schema
        criar_schema = MCPClientCriar(
            agente_id=payload.agente_id,
            nome=nome,
            descricao=descricao,
            preset_key=None,  # Não é um preset
            preset_inputs=None,
            transport_type=transport_type,
            command=command,
            args=args,
            env_vars=env_vars,
            url=url,
            headers=headers,
            ativo=True,
        )

        return MCPService.criar(db, criar_schema)

    @staticmethod
    def _substituir_inputs(valor: str, inputs: Dict[str, str]) -> str:
        """Substitui placeholders ${input:key} pelos valores fornecidos."""

        if not isinstance(valor, str):
            return valor

        resultado = valor
        for key, val in inputs.items():
            resultado = resultado.replace(f"${{input:{key}}}", val)
        return resultado
    
    @staticmethod
    async def _conectar_cliente_interno(db: Session, mcp_client_id: int, db_mcp) -> Dict[str, Any]:
        """
        Conecta a um servidor MCP sem usar lock (uso interno).
        Deve ser chamado quando o lock já está adquirido.
        """
        try:
                # Conectar baseado no tipo de transporte
                if db_mcp.transport_type == TransportType.STDIO:
                    # Conexão STDIO
                    server_params = StdioServerParameters(
                        command=db_mcp.command,
                        args=db_mcp.args or [],
                        env=db_mcp.env_vars or {}
                    )
                    
                    context = stdio_client(server_params)
                    streams = await context.__aenter__()
                    read_stream, write_stream = streams
                    
                elif db_mcp.transport_type == TransportType.STREAMABLE_HTTP:
                    # Conexão HTTP
                    context = streamablehttp_client(db_mcp.url)
                    streams = await context.__aenter__()
                    read_stream, write_stream, _ = streams
                
                elif db_mcp.transport_type == TransportType.SSE:
                    # Conexão SSE
                    from mcp.client.sse import sse_client
                    context = sse_client(db_mcp.url)
                    streams = await context.__aenter__()
                    read_stream, write_stream = streams
                
                else:
                    raise ValueError(f"Transport type {db_mcp.transport_type} não suportado ainda")
                
                # Criar sessão do cliente
                session = ClientSession(read_stream, write_stream)
                await session.__aenter__()
                
                # Inicializar conexão
                init_result = await session.initialize()
                
                # Armazenar sessão ativa
                MCPService._active_sessions[mcp_client_id] = session
                MCPService._session_contexts[mcp_client_id] = context
                
                # Atualizar banco de dados
                db_mcp.conectado = True
                db_mcp.ultimo_erro = None
                db_mcp.ultima_conexao = datetime.now()
                db_mcp.server_name = init_result.serverInfo.name if hasattr(init_result, 'serverInfo') else None
                db_mcp.server_version = init_result.serverInfo.version if hasattr(init_result, 'serverInfo') else None
                # Converter capabilities para dict se necessário
                if hasattr(init_result, 'capabilities') and init_result.capabilities:
                    if hasattr(init_result.capabilities, 'model_dump'):
                        db_mcp.capabilities = init_result.capabilities.model_dump()
                    elif hasattr(init_result.capabilities, 'dict'):
                        db_mcp.capabilities = init_result.capabilities.dict()
                    else:
                        db_mcp.capabilities = init_result.capabilities
                else:
                    db_mcp.capabilities = None
                db.commit()
                
                # Sincronizar tools
                await MCPService.sincronizar_tools(db, mcp_client_id)
                
                return {
                    "sucesso": True,
                    "mensagem": "Conectado com sucesso",
                    "server_name": db_mcp.server_name,
                    "server_version": db_mcp.server_version
                }
        
        except Exception as e:
            # Registrar erro
            db_mcp.conectado = False
            db_mcp.ultimo_erro = str(e)
            db.commit()
            
            return {
                "sucesso": False,
                "mensagem": f"Erro ao conectar: {str(e)}",
                "erro": str(e)
            }
    
    @staticmethod
    async def conectar_cliente(db: Session, mcp_client_id: int) -> Dict[str, Any]:
        """
        Conecta a um servidor MCP e inicializa a sessão.
        Versão pública que usa lock.
        
        Returns:
            Dict com status da conexão
        """
        db_mcp = MCPService.obter_por_id(db, mcp_client_id)
        if not db_mcp:
            raise ValueError(f"Cliente MCP {mcp_client_id} não encontrado")
        
        # Verificar se já está conectado
        if mcp_client_id in MCPService._active_sessions:
            return {
                "sucesso": True,
                "mensagem": "Já conectado",
                "server_name": db_mcp.server_name
            }
        
        # Usar lock compatível com o event loop atual
        lock = MCPService._get_lock(mcp_client_id)
        async with lock:
            return await MCPService._conectar_cliente_interno(db, mcp_client_id, db_mcp)
    
    @staticmethod
    async def desconectar_cliente(mcp_client_id: int):
        """Desconecta um cliente MCP."""
        if mcp_client_id in MCPService._active_sessions:
            try:
                session = MCPService._active_sessions[mcp_client_id]
                context = MCPService._session_contexts.get(mcp_client_id)
                
                # Fechar sessão
                await session.__aexit__(None, None, None)
                
                # Fechar context
                if context:
                    await context.__aexit__(None, None, None)
                
            except Exception as e:
                print(f"Erro ao desconectar cliente MCP {mcp_client_id}: {e}")
            finally:
                # Remover da memória
                del MCPService._active_sessions[mcp_client_id]
                if mcp_client_id in MCPService._session_contexts:
                    del MCPService._session_contexts[mcp_client_id]
    
    @staticmethod
    async def sincronizar_tools(db: Session, mcp_client_id: int) -> int:
        """
        Sincroniza tools do servidor MCP com o banco de dados.
        
        Returns:
            Número de tools sincronizadas
        """
        session = MCPService._active_sessions.get(mcp_client_id)
        if not session:
            raise ValueError(f"Cliente MCP {mcp_client_id} não está conectado")
        
        try:
            # Listar tools do servidor MCP
            tools_result = await session.list_tools()
            tools_mcp = tools_result.tools
            
            # Obter tools existentes no banco
            tools_existentes = db.query(MCPTool).filter(
                MCPTool.mcp_client_id == mcp_client_id
            ).all()
            tools_existentes_map = {t.name: t for t in tools_existentes}
            
            tools_names_novas = set()
            
            # Atualizar/criar tools
            for tool in tools_mcp:
                tools_names_novas.add(tool.name)
                
                # Extrair display name (title ou name)
                display_name = getattr(tool, 'title', None) or tool.name
                
                if tool.name in tools_existentes_map:
                    # Atualizar tool existente
                    db_tool = tools_existentes_map[tool.name]
                    db_tool.display_name = display_name
                    db_tool.description = tool.description or ""
                    # Converter inputSchema para dict se necessário
                    if hasattr(tool.inputSchema, 'model_dump'):
                        db_tool.input_schema = tool.inputSchema.model_dump()
                    elif hasattr(tool.inputSchema, 'dict'):
                        db_tool.input_schema = tool.inputSchema.dict()
                    else:
                        db_tool.input_schema = tool.inputSchema
                    
                    # Converter outputSchema para dict se necessário
                    if hasattr(tool, 'outputSchema') and tool.outputSchema:
                        if hasattr(tool.outputSchema, 'model_dump'):
                            db_tool.output_schema = tool.outputSchema.model_dump()
                        elif hasattr(tool.outputSchema, 'dict'):
                            db_tool.output_schema = tool.outputSchema.dict()
                        else:
                            db_tool.output_schema = tool.outputSchema
                    else:
                        db_tool.output_schema = None
                    db_tool.ultima_sincronizacao = datetime.now()
                else:
                    # Criar nova tool
                    db_tool = MCPTool(
                        mcp_client_id=mcp_client_id,
                        name=tool.name,
                        display_name=display_name,
                        description=tool.description or "",
                        input_schema=tool.inputSchema.model_dump() if hasattr(tool.inputSchema, 'model_dump') else (tool.inputSchema.dict() if hasattr(tool.inputSchema, 'dict') else tool.inputSchema),
                        output_schema=tool.outputSchema.model_dump() if hasattr(tool, 'outputSchema') and tool.outputSchema and hasattr(tool.outputSchema, 'model_dump') else (tool.outputSchema.dict() if hasattr(tool, 'outputSchema') and tool.outputSchema and hasattr(tool.outputSchema, 'dict') else (tool.outputSchema if hasattr(tool, 'outputSchema') and tool.outputSchema else None)),
                        ativa=True
                    )
                    db.add(db_tool)
            
            # Remover tools que não existem mais no servidor
            for tool_name, db_tool in tools_existentes_map.items():
                if tool_name not in tools_names_novas:
                    db.delete(db_tool)
            
            # Atualizar timestamp de sincronização do cliente
            db_mcp = MCPService.obter_por_id(db, mcp_client_id)
            if db_mcp:
                db_mcp.ultima_sincronizacao = datetime.now()
            
            db.commit()
            
            return len(tools_names_novas)
        
        except Exception as e:
            print(f"Erro ao sincronizar tools do MCP {mcp_client_id}: {e}")
            raise
    
    @staticmethod
    def listar_tools_ativas(db: Session, mcp_client_id: int) -> List[MCPTool]:
        """Lista tools ativas de um cliente MCP."""
        return db.query(MCPTool).filter(
            MCPTool.mcp_client_id == mcp_client_id,
            MCPTool.ativa == True
        ).all()
    
    @staticmethod
    def converter_mcp_tool_para_openai(mcp_client: MCPClient, mcp_tool: MCPTool) -> Dict[str, Any]:
        """
        Converte uma MCPTool para o formato OpenAI Function Calling.
        Adiciona prefixo mcp_{client_id}_ para evitar conflitos.
        """
        function_name = f"mcp_{mcp_client.id}_{mcp_tool.name}"
        
        return {
            "type": "function",
            "function": {
                "name": function_name,
                "description": f"[MCP: {mcp_client.nome}] {mcp_tool.description}",
                "parameters": mcp_tool.input_schema
            }
        }
    
    @staticmethod
    async def executar_tool_mcp(
        db: Session,
        mcp_client_id: int,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Executa uma tool MCP.
        
        Returns:
            Dict no formato padronizado do Fluxi:
            {
                "resultado": {...},
                "output": "llm",
                "enviado_usuario": False
            }
        """
        inicio = time.time()
        
        lock = MCPService._get_lock(mcp_client_id)
        print(f"🔒 [MCP] Aguardando lock para client {mcp_client_id}...")
        # Usar lock para evitar chamadas concorrentes na mesma sessão
        async with lock:
            print(f"🔓 [MCP] Lock adquirido para client {mcp_client_id}")
            # Obter sessão ativa
            session = MCPService._active_sessions.get(mcp_client_id)
            print(f"📡 [MCP] Sessão obtida: {session is not None}")
            if not session:
                # Tentar reconectar usando função interna (já estamos dentro do lock)
                print(f"⚠️  [MCP] Sessão não existe. Tentando reconectar...")
                db_mcp = MCPService.obter_por_id(db, mcp_client_id)
                if not db_mcp:
                    return {
                        "resultado": {"erro": f"Cliente MCP {mcp_client_id} não encontrado"},
                        "output": "llm",
                        "enviado_usuario": False
                    }
                
                # Reconectar (já estamos dentro do lock, então usamos função interna)
                resultado_conexao = await MCPService._conectar_cliente_interno(db, mcp_client_id, db_mcp)
                if not resultado_conexao.get("sucesso"):
                    print(f"❌ [MCP] Falha ao reconectar: {resultado_conexao.get('mensagem')}")
                    return {
                        "resultado": {"erro": f"Erro ao reconectar MCP: {resultado_conexao.get('mensagem')}"},
                        "output": "llm",
                        "enviado_usuario": False
                    }
                
                # Obter sessão recém-criada
                session = MCPService._active_sessions.get(mcp_client_id)
                if not session:
                    return {
                        "resultado": {"erro": "Erro ao obter sessão após reconexão"},
                        "output": "llm",
                        "enviado_usuario": False
                    }
                print(f"✅ [MCP] Reconectado com sucesso!")
            
            try:
                # Timeout inteligente: sandbox usa timeout maior
                db_mcp_info = MCPService.obter_por_id(db, mcp_client_id)
                is_sandbox = db_mcp_info and db_mcp_info.preset_key == "aio-sandbox"
                if is_sandbox:
                    timeout_mcp = float(ConfiguracaoService.obter_valor(db, "mcp_timeout_sandbox", 300))
                else:
                    timeout_mcp = float(ConfiguracaoService.obter_valor(db, "mcp_timeout_execucao", 120))
                
                print(f"🚀 [MCP] Chamando '{tool_name}' (timeout={timeout_mcp}s)...")
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments),
                    timeout=timeout_mcp
                )
                print(f"✅ [MCP] Tool '{tool_name}' concluída")
                
                # Parse resultado
                content_list = []
                for content_item in result.content:
                    if isinstance(content_item, types.TextContent):
                        content_list.append({
                            "type": "text",
                            "text": content_item.text
                        })
                    elif isinstance(content_item, types.ImageContent):
                        content_list.append({
                            "type": "image",
                            "data": content_item.data,
                            "mimeType": content_item.mimeType
                        })
                    elif isinstance(content_item, types.EmbeddedResource):
                        # Recurso incorporado
                        resource = content_item.resource
                        if isinstance(resource, types.TextResourceContents):
                            content_list.append({
                                "type": "resource",
                                "uri": str(resource.uri),
                                "text": resource.text
                            })
                
                # Extrair structured content se houver
                structured_content = None
                if hasattr(result, 'structuredContent') and result.structuredContent:
                    structured_content = result.structuredContent
                
                # Calcular tempo
                tempo_ms = int((time.time() - inicio) * 1000)
                print(f"⏱️  [MCP] Tempo de execução: {tempo_ms}ms")
                
                # Formatar resultado
                if structured_content:
                    resultado_final = structured_content
                elif content_list:
                    # Se só tem texto, retornar o texto direto
                    if len(content_list) == 1 and content_list[0]["type"] == "text":
                        resultado_final = {"resposta": content_list[0]["text"]}
                    else:
                        resultado_final = {"content": content_list}
                else:
                    resultado_final = {"resposta": "Tool executada com sucesso"}
                
                return {
                    "resultado": resultado_final,
                    "output": "llm",
                    "enviado_usuario": False,
                    "tempo_ms": tempo_ms
                }
            
            except asyncio.TimeoutError:
                print(f"⏱️  [MCP] TIMEOUT: Tool '{tool_name}' demorou mais de {timeout_mcp}s")
                # Sessão fica corrompida após timeout (call_tool pendente no wire)
                # Forçar desconexão para que próxima chamada reconecte com sessão limpa
                try:
                    print(f"🔄 [MCP] Forçando desconexão do client {mcp_client_id} após timeout...")
                    if mcp_client_id in MCPService._active_sessions:
                        old_session = MCPService._active_sessions.pop(mcp_client_id)
                        old_context = MCPService._session_contexts.pop(mcp_client_id, None)
                        try:
                            await old_session.__aexit__(None, None, None)
                        except Exception:
                            pass
                        try:
                            if old_context:
                                await old_context.__aexit__(None, None, None)
                        except Exception:
                            pass
                    print(f"✅ [MCP] Sessão limpa após timeout. Próxima chamada vai reconectar.")
                except Exception as cleanup_err:
                    print(f"⚠️  [MCP] Erro ao limpar sessão após timeout: {cleanup_err}")
                
                tempo_ms = int((time.time() - inicio) * 1000)
                return {
                    "resultado": {"erro": f"Timeout ao executar tool MCP '{tool_name}' ({timeout_mcp}s). Tente novamente ou divida a tarefa em partes menores."},
                    "output": "llm",
                    "enviado_usuario": False,
                    "tempo_ms": tempo_ms
                }
            except Exception as e:
                print(f"❌ [MCP] EXCEÇÃO durante execução: {type(e).__name__}: {str(e)}")
                import traceback
                traceback.print_exc()
                tempo_ms = int((time.time() - inicio) * 1000)
                return {
                    "resultado": {"erro": f"Erro ao executar tool MCP: {str(e)}"},
                    "output": "llm",
                    "enviado_usuario": False,
                    "tempo_ms": tempo_ms
                }
