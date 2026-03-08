"""Presets prontos para configurar servidores MCP populares."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from mcp_client.mcp_client_model import TransportType


@dataclass(slots=True)
class MCPPresetInput:
    """Campo de entrada que o usuário precisa fornecer ao aplicar um preset."""

    id: str
    label: str
    description: str
    secret: bool = False


@dataclass(slots=True)
class MCPPreset:
    """Estrutura de um preset MCP plug-and-play."""

    key: str
    name: str
    description: str
    transport_type: TransportType
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    documentation_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    inputs: List[MCPPresetInput] = field(default_factory=list)
    notes: Optional[str] = None


MCP_PRESETS: Dict[str, MCPPreset] = {
    "aio-sandbox": MCPPreset(
        key="aio-sandbox",
        name="AIO Sandbox (Browser + Shell + Files)",
        description=(
            "Sandbox all-in-one com navegador web, terminal, gerenciador de arquivos "
            "e conversão de documentos. Roda isolado em Docker. "
            "Permite ao agente navegar na internet, executar código Python, "
            "instalar pacotes via pip, gerenciar arquivos e muito mais."
        ),
        transport_type=TransportType.STREAMABLE_HTTP,
        url="${input:sandbox_url}",
        documentation_url="https://github.com/agent-infra/sandbox",
        tags=["featured", "sandbox", "browser", "shell", "files", "code"],
        inputs=[
            MCPPresetInput(
                id="sandbox_url",
                label="URL do Sandbox MCP",
                description=(
                    "Endpoint MCP do AIO Sandbox. "
                    "Se usando docker-compose: http://fluxi-sandbox:8080/mcp | "
                    "Se local: http://localhost:8080/mcp"
                ),
                secret=False,
            )
        ],
        notes=(
            "Requer o container AIO Sandbox rodando. "
            "Adicione o serviço 'sandbox' ao docker-compose.yml ou execute: "
            "docker run --security-opt seccomp=unconfined --rm -it -p 8080:8080 "
            "ghcr.io/agent-infra/sandbox:latest"
        ),
    ),
    "github-copilot-oauth": MCPPreset(
        key="github-copilot-oauth",
        name="GitHub Copilot (OAuth)",
        description="Conecta ao MCP oficial do GitHub Copilot usando autenticação padrão.",
        transport_type=TransportType.STREAMABLE_HTTP,
        url="https://api.githubcopilot.com/mcp/",
        documentation_url="https://docs.github.com/en/copilot/github-copilot-services/copilot-chat-in-enterprise#allow-network-access",
        tags=["featured", "coding", "github"],
        notes="Autenticação gerenciada automaticamente pelo VS Code (1.101+).",
    ),
    "deepwiki-sse": MCPPreset(
        key="deepwiki-sse",
        name="DeepWiki (SSE)",
        description="Acesso ao DeepWiki via SSE transport.",
        transport_type=TransportType.SSE,
        url="https://mcp.deepwiki.com/sse",
        documentation_url="https://mcp.deepwiki.com",
        tags=["featured", "search", "wiki"],
        notes="Servidor MCP para busca em wikis e documentação.",
    ),
    "deepwiki-http": MCPPreset(
        key="deepwiki-http",
        name="DeepWiki (HTTP)",
        description="Acesso ao DeepWiki via Streamable HTTP transport.",
        transport_type=TransportType.STREAMABLE_HTTP,
        url="https://mcp.deepwiki.com/mcp",
        documentation_url="https://mcp.deepwiki.com",
        tags=["featured", "search", "wiki"],
        notes="Servidor MCP para busca em wikis e documentação.",
    ),
    "github-copilot-pat": MCPPreset(
        key="github-copilot-pat",
        name="GitHub Copilot (PAT)",
        description="Usa um token pessoal para autenticar no servidor MCP do Copilot.",
        transport_type=TransportType.STREAMABLE_HTTP,
        url="https://api.githubcopilot.com/mcp/",
        headers={"Authorization": "Bearer ${input:github_mcp_pat}"},
        documentation_url="https://docs.github.com/en/copilot/github-copilot-services/copilot-chat-in-enterprise#allow-network-access",
        tags=["featured", "coding", "github"],
        inputs=[
            MCPPresetInput(
                id="github_mcp_pat",
                label="GitHub Personal Access Token",
                description="Token com escopo 'copilot-mcp-server'.",
                secret=True,
            )
        ],
    ),
    "jina-ai-tools": MCPPreset(
        key="jina-ai-tools",
        name="Jina AI MCP Tools",
        description="Ferramentas de pesquisa e leitura da Jina AI via npx (Node).",
        transport_type=TransportType.STDIO,
        command="npx",
        args=["jina-mcp-tools"],
        env={"JINA_API_KEY": "${input:jina_api_key}"},
        documentation_url="https://github.com/jina-ai/jina-mcp-tools",
        tags=["featured", "search", "web"],
        inputs=[
            MCPPresetInput(
                id="jina_api_key",
                label="Jina API Key",
                description="Chave da Jina AI disponível em https://jina.ai/",
                secret=True,
            )
        ],
    ),
    "firecrawl": MCPPreset(
        key="firecrawl",
        name="Firecrawl MCP",
        description="Rastreador e leitor web focado em crawling inteligente.",
        transport_type=TransportType.STDIO,
        command="npx",
        args=["-y", "firecrawl-mcp"],
        env={"FIRECRAWL_API_KEY": "${input:firecrawl_api_key}"},
        documentation_url="https://github.com/mendableai/firecrawl",
        tags=["web", "crawler"],
        inputs=[
            MCPPresetInput(
                id="firecrawl_api_key",
                label="Firecrawl API Key",
                description="Chave Firecrawl (https://www.firecrawl.dev/).",
                secret=True,
            )
        ],
    ),
    "serper": MCPPreset(
        key="serper",
        name="Serper Search",
        description="Busca Google com Serper via utilitário Python (uvx).",
        transport_type=TransportType.STDIO,
        command="uvx",
        args=["serper-mcp-server"],
        env={"SERPER_API_KEY": "${input:serper_api_key}"},
        documentation_url="https://github.com/serper-ai/serper-mcp-server",
        tags=["search", "google"],
        inputs=[
            MCPPresetInput(
                id="serper_api_key",
                label="Serper API Key",
                description="Crie em https://serper.dev/",
                secret=True,
            )
        ],
    ),
    "google-maps": MCPPreset(
        key="google-maps",
        name="Google Maps",
        description="Consulta APIs do Google Maps via contêiner Docker oficial (mcp.so).",
        transport_type=TransportType.STDIO,
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-e",
            "GOOGLE_MAPS_API_KEY=${input:google_maps_api_key}",
            "mcp/google-maps",
        ],
        documentation_url="https://mcp.so/server/google-maps",
        tags=["maps", "geolocation"],
        inputs=[
            MCPPresetInput(
                id="google_maps_api_key",
                label="Google Maps API Key",
                description="Crie no console Google Cloud (APIs & Services).",
                secret=True,
            )
        ],
    ),
    "brave-search": MCPPreset(
        key="brave-search",
        name="Brave Search",
        description="Busca web com foco em privacidade via imagem Docker do mcp.so.",
        transport_type=TransportType.STDIO,
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-e",
            "BRAVE_API_KEY=${input:brave_api_key}",
            "mcp/brave-search",
        ],
        documentation_url="https://mcp.so/server/brave-search",
        tags=["search", "privacy"],
        inputs=[
            MCPPresetInput(
                id="brave_api_key",
                label="Brave Search API Key",
                description="Crie em https://brave.com/search/api/",
                secret=True,
            )
        ],
    ),
    "time-server": MCPPreset(
        key="time-server",
        name="Time Server",
        description="Servidor de tempo com suporte a fusos horários.",
        transport_type=TransportType.STDIO,
        command="uvx",
        args=["mcp-server-time", "--local-timezone=America/Sao_Paulo"],
        documentation_url="https://github.com/modelcontextprotocol/servers",
        tags=["time", "utility"],
        notes="Servidor de tempo para consultas de data e hora.",
    ),
    "minimax": MCPPreset(
        key="minimax",
        name="MiniMax MCP",
        description="Integração com MiniMax AI via MCP.",
        transport_type=TransportType.STDIO,
        command="uvx",
        args=["minimax-mcp"],
        env={
            "MINIMAX_API_KEY": "${input:minimax_api_key}",
            "MINIMAX_MCP_BASE_PATH": "${input:minimax_base_path}",
            "MINIMAX_API_HOST": "https://api.minimaxi.chat",
            "MINIMAX_API_RESOURCE_MODE": "url"
        },
        documentation_url="https://github.com/modelcontextprotocol/servers",
        tags=["ai", "minimax"],
        inputs=[
            MCPPresetInput(
                id="minimax_api_key",
                label="MiniMax API Key",
                description="Chave da API MiniMax",
                secret=True,
            ),
            MCPPresetInput(
                id="minimax_base_path",
                label="Base Path",
                description="Caminho local para saída (ex: /tmp/minimax)",
                secret=False,
            )
        ],
    ),
}


def listar_presets() -> List[MCPPreset]:
    """Retorna presets ordenados por nome."""

    return sorted(MCP_PRESETS.values(), key=lambda preset: preset.name.lower())


def obter_preset(preset_key: str) -> Optional[MCPPreset]:
    """Busca preset pelo identificador."""

    return MCP_PRESETS.get(preset_key)
