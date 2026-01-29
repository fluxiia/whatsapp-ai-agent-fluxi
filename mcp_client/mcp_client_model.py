"""
Modelo de dados para clientes MCP.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base
from enum import Enum


class TransportType(str, Enum):
    """Tipos de transporte MCP."""
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


class MCPClient(Base):
    """
    Tabela de clientes MCP vinculados a agentes.
    Cada cliente representa uma conexão com um servidor MCP externo.
    """
    __tablename__ = "mcp_clients"

    id = Column(Integer, primary_key=True, index=True)
    agente_id = Column(Integer, ForeignKey("agentes.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Identificação
    nome = Column(String(100), nullable=False)  # Ex: "GitHub Tools"
    descricao = Column(Text, nullable=True)
    
    # Configuração de Conexão
    transport_type = Column(SQLEnum(TransportType), nullable=False, default=TransportType.STDIO)

    # Preset aplicado
    preset_key = Column(String(100), nullable=True, index=True)
    preset_inputs = Column(JSON, nullable=True)

    # Para STDIO (comando local)
    command = Column(String(500), nullable=True)  # Ex: "python", "npx", "uv"
    args = Column(JSON, nullable=True)  # Ex: ["run", "server.py"]
    env_vars = Column(JSON, nullable=True)  # Variáveis de ambiente

    # Para SSE/HTTP (servidor remoto)
    url = Column(String(500), nullable=True)  # Ex: "http://localhost:8000/mcp"
    headers = Column(JSON, nullable=True)
    
    # Estado
    ativo = Column(Boolean, default=True)
    conectado = Column(Boolean, default=False)
    ultimo_erro = Column(Text, nullable=True)
    
    # Metadados do servidor MCP
    server_name = Column(String(100), nullable=True)  # Nome do servidor MCP
    server_version = Column(String(50), nullable=True)
    capabilities = Column(JSON, nullable=True)  # Capabilities do servidor
    
    # Timestamps
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())
    ultima_conexao = Column(DateTime(timezone=True), nullable=True)
    ultima_sincronizacao = Column(DateTime(timezone=True), nullable=True)
    
    # Relacionamentos
    agente = relationship("Agente", back_populates="mcp_clients")
    tools = relationship("MCPTool", back_populates="mcp_client", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<MCPClient(nome='{self.nome}', agente_id={self.agente_id}, conectado={self.conectado})>"
