"""
Rotas do frontend para clientes MCP.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from mcp_client.mcp_service import MCPService
from mcp_client.mcp_presets import listar_presets
from agente.agente_service import AgenteService

router = APIRouter(prefix="/mcp", tags=["MCP Frontend"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def mcp_index(request: Request, db: Session = Depends(get_db)):
    """Página inicial MCP - lista sessões com agentes."""
    from sessao.sessao_service import SessaoService
    
    sessoes = SessaoService.listar_todas(db, apenas_ativas=True)
    
    # Contar MCP clients por sessão
    for sessao in sessoes:
        total_mcp = 0
        for agente in sessao.agentes:
            if agente.ativo:
                total_mcp += len(MCPService.listar_por_agente(db, agente.id))
        sessao.total_mcp_clients = total_mcp
    
    return templates.TemplateResponse("mcp/index.html", {
        "request": request,
        "sessoes": sessoes,
        "titulo": "MCP Clients"
    })


@router.get("/presets", response_class=HTMLResponse)
def pagina_presets(
    request: Request,
    agente_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Página com presets plug-and-play para servidores MCP."""

    agente = AgenteService.obter_por_id(db, agente_id) if agente_id else None
    presets = MCPService.listar_presets_disponiveis()

    return templates.TemplateResponse("mcp/presets.html", {
        "request": request,
        "agente": agente,
        "presets": presets,
        "titulo": "Presets MCP",
    })


@router.get("/docs", response_class=HTMLResponse)
def pagina_docs_mcp(request: Request):
    """Documentação simplificada sobre MCP dentro da plataforma."""

    # Conteúdo estruturado para facilitar manutenção
    overview = {
        "intro": "O Model Context Protocol (MCP) permite conectar o seu agente Fluxi a servidores externos que expõem ferramentas, recursos e prompts de maneira padronizada.",
        "beneficios": [
            "Padroniza a integração de ferramentas externas",
            "Permite reuso em diferentes IDEs e agentes",
            "Oferece transports STDIO e HTTP (streamable ou SSE)",
            "Facilita publicação de novas ferramentas para a comunidade",
        ],
    }

    passos_basicos = [
        {
            "titulo": "Escolha um servidor MCP",
            "descricao": "Use os presets da Fluxi ou consulte a galeria pública em https://mcp.so/servers.",
        },
        {
            "titulo": "Adicione a conexão",
            "descricao": "Forneça comando (STDIO) ou URL (HTTP) e as variáveis de ambiente necessárias.",
        },
        {
            "titulo": "Sincronize as tools",
            "descricao": "Clique em Sync para importar ferramentas, prompts e recursos do servidor.",
        },
        {
            "titulo": "Use no agente",
            "descricao": "Após sincronizar, o LLM poderá invocar as tools MCP automaticamente nas conversas.",
        },
    ]

    recursos = [
        {
            "titulo": "Documentação oficial MCP Python",
            "descricao": "SDK Python completo com exemplos de cliente e servidor.",
            "link": "https://github.com/modelcontextprotocol/servers",
        },
        {
            "titulo": "Galeria de servidores (mcp.so)",
            "descricao": "Coleção curada de servidores MCP prontos para uso (Node, Python, Docker).",
            "link": "https://mcp.so/servers?tag=featured",
        },
        {
            "titulo": "Jina MCP Tools",
            "descricao": "Ferramentas de leitura, busca e verificação construídas pela Jina AI.",
            "link": "https://github.com/jina-ai/jina-mcp-tools",
        },
        {
            "titulo": "GitHub Copilot MCP",
            "descricao": "Acesso às ferramentas do Copilot via VS Code 1.101+ ou PAT.",
            "link": "https://docs.github.com/en/copilot/github-copilot-services/copilot-chat-in-enterprise#allow-network-access",
        },
    ]

    comandos_exemplo = [
        {
            "nome": "Firecrawl (Node)",
            "config": {
                "mcpServers": {
                    "firecrawl-mcp": {
                        "command": "npx",
                        "args": ["-y", "firecrawl-mcp"],
                        "env": {"FIRECRAWL_API_KEY": "fc-..."},
                    }
                }
            },
        },
        {
            "nome": "Serper (Python)",
            "config": {
                "mcpServers": {
                    "serper": {
                        "command": "uvx",
                        "args": ["serper-mcp-server"],
                        "env": {"SERPER_API_KEY": "<api-key>"},
                    }
                }
            },
        },
        {
            "nome": "Google Maps (Docker)",
            "config": {
                "mcpServers": {
                    "google-maps": {
                        "command": "docker",
                        "args": [
                            "run",
                            "-i",
                            "--rm",
                            "-e",
                            "GOOGLE_MAPS_API_KEY",
                            "mcp/google-maps",
                        ],
                        "env": {"GOOGLE_MAPS_API_KEY": "<api-key>"},
                    }
                }
            },
        },
    ]

    return templates.TemplateResponse("mcp/docs.html", {
        "request": request,
        "titulo": "Documentação MCP",
        "overview": overview,
        "passos_basicos": passos_basicos,
        "recursos": recursos,
        "comandos_exemplo": comandos_exemplo,
    })


@router.get("/agente/{agente_id}/clients", response_class=HTMLResponse)
def listar_mcp_clients_frontend(
    request: Request,
    agente_id: int,
    db: Session = Depends(get_db)
):
    """Página para listar e gerenciar clientes MCP de um agente."""
    agente = AgenteService.obter_por_id(db, agente_id)
    if not agente:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "mensagem": "Agente não encontrado"
        })
    
    mcp_clients = MCPService.listar_por_agente(db, agente_id)
    
    # Adicionar contagem de tools
    for mcp_client in mcp_clients:
        mcp_client.total_tools = len(MCPService.listar_tools_ativas(db, mcp_client.id))
    
    total_mcp_clients = len(mcp_clients)
    
    return templates.TemplateResponse("mcp/lista.html", {
        "request": request,
        "agente": agente,
        "mcp_clients": mcp_clients,
        "total_mcp_clients": total_mcp_clients,
        "limite_mcp_clients": 5,
        "pode_adicionar": total_mcp_clients < 5,
        "titulo": f"MCP Clients - {agente.nome}"
    })


# Rota removida - agora usamos apenas JSON Config


@router.get("/clients/{mcp_client_id}/editar", response_class=HTMLResponse)
def form_editar_mcp_client(
    request: Request,
    mcp_client_id: int,
    db: Session = Depends(get_db)
):
    """Formulário para editar cliente MCP."""
    mcp_client = MCPService.obter_por_id(db, mcp_client_id)
    if not mcp_client:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "mensagem": "Cliente MCP não encontrado"
        })
    
    agente = AgenteService.obter_por_id(db, mcp_client.agente_id)
    
    return templates.TemplateResponse("mcp/form.html", {
        "request": request,
        "agente": agente,
        "mcp_client": mcp_client,
        "titulo": f"Editar {mcp_client.nome}"
    })


@router.get("/clients/{mcp_client_id}/tools", response_class=HTMLResponse)
def listar_tools_frontend(
    request: Request,
    mcp_client_id: int,
    db: Session = Depends(get_db)
):
    """Página para visualizar tools de um cliente MCP."""
    mcp_client = MCPService.obter_por_id(db, mcp_client_id)
    if not mcp_client:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "mensagem": "Cliente MCP não encontrado"
        })
    
    agente = AgenteService.obter_por_id(db, mcp_client.agente_id)
    tools = MCPService.listar_tools_ativas(db, mcp_client_id)
    
    return templates.TemplateResponse("mcp/tools.html", {
        "request": request,
        "agente": agente,
        "mcp_client": mcp_client,
        "tools": tools,
        "titulo": f"Tools - {mcp_client.nome}"
    })


@router.get("/galeria", response_class=HTMLResponse)
def pagina_galeria_mcp(
    request: Request,
    agente_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Galeria pública de servidores MCP via Smithery registry."""
    from config.config_service import ConfiguracaoService
    agente = AgenteService.obter_por_id(db, agente_id) if agente_id else None
    smithery_api_key = ConfiguracaoService.obter_valor(db, "smithery_api_key", "")
    return templates.TemplateResponse("mcp/galeria.html", {
        "request": request,
        "agente": agente,
        "smithery_api_key": smithery_api_key,
        "titulo": "Galeria de Servidores MCP",
    })


@router.get("/agente/{agente_id}/json-config", response_class=HTMLResponse)
def form_json_config(
    request: Request,
    agente_id: int,
    db: Session = Depends(get_db)
):
    """Formulário para conectar via configuração JSON one-click."""
    agente = AgenteService.obter_por_id(db, agente_id)
    if not agente:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "mensagem": "Agente não encontrado"
        })
    
    # Verificar limite
    total_existentes = MCPService.contar_por_agente(db, agente_id)
    if total_existentes >= 5:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "mensagem": "Limite de 5 clientes MCP por agente atingido"
        })
    
    # Exemplos de configuração JSON
    exemplos_json = [
        {
            "nome": "DeepWiki",
            "config": {
                "mcpServers": {
                    "deepwiki": {
                        "url": "https://mcp.deepwiki.com/mcp"
                    }
                }
            }
        },
        {
            "nome": "Time Server",
            "config": {
                "mcpServers": {
                    "time": {
                        "command": "uvx",
                        "args": [
                            "mcp-server-time",
                            "--local-timezone=America/Sao_Paulo"
                        ]
                    }
                }
            }
        },
        {
            "nome": "Jina AI Tools",
            "config": {
                "mcpServers": {
                    "jina-mcp-tools": {
                        "command": "npx",
                        "args": ["jina-mcp-tools"],
                        "env": {
                            "JINA_API_KEY": "your_jina_api_key_here"
                        }
                    }
                }
            }
        },
        {
            "nome": "Serper Search",
            "config": {
                "mcpServers": {
                    "serper": {
                        "command": "uvx",
                        "args": ["serper-mcp-server"],
                        "env": {
                            "SERPER_API_KEY": "<Your Serper API key>"
                        }
                    }
                }
            }
        }
    ]
    
    return templates.TemplateResponse("mcp/json_config.html", {
        "request": request,
        "agente": agente,
        "exemplos": exemplos_json,
        "titulo": "Conectar via JSON Config"
    })
