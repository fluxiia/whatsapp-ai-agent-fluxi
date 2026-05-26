"""
Modelo de dados para ferramentas.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base
from enum import Enum


class ToolType(str, Enum):
    """Tipos de ferramenta."""
    WEB = "web"
    CODE = "code"
    NATIVE = "native"  # Chama service layer diretamente via NATIVE_REGISTRY


class ToolScope(str, Enum):
    """Escopo da ferramenta."""
    PRINCIPAL = "principal"
    AUXILIAR = "auxiliar"


class OutputDestination(str, Enum):
    """Destino do output."""
    LLM = "llm"
    USER = "user"
    BOTH = "both"


class ChannelType(str, Enum):
    """Tipo de canal para envio."""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


class BodyType(str, Enum):
    """Tipo de body para requisições."""
    JSON = "json"
    FORM_DATA = "form-data"
    URLENCODED = "x-www-form-urlencoded"
    RAW = "raw"


class Ferramenta(Base):
    """
    Tabela de ferramentas disponíveis no sistema.
    Ferramentas podem ser requisições web ou código Python executável.
    """
    __tablename__ = "ferramentas"

    id = Column(Integer, primary_key=True, index=True)
    
    # Campos básicos
    nome = Column(String(100), nullable=False, unique=True, index=True)
    descricao = Column(Text, nullable=False)
    
    # Tipo e escopo
    tool_type = Column(SQLEnum(ToolType), nullable=False, default=ToolType.CODE)
    tool_scope = Column(SQLEnum(ToolScope), nullable=False, default=ToolScope.PRINCIPAL)
    
    # Parâmetros da ferramenta (JSON com definição dos params)
    params = Column(Text, nullable=True)  # JSON: {"param_name": {"type": "string", "required": true, ...}}
    
    # Campos para ferramentas WEB
    curl_command = Column(Text, nullable=True)  # Comando CURL completo (única fonte da verdade)
    
    # Campos para ferramentas CODE
    codigo_python = Column(Text, nullable=True)  # Código Python para executar
    
    # Substituição dinâmica
    substituir = Column(Boolean, default=True)  # Permite uso de {variavel}
    
    # Mapeamento de resposta
    response_map = Column(Text, nullable=True)  # JSON: {"campo_api": "campo_resultado"}
    
    # Destino da saída
    output = Column(SQLEnum(OutputDestination), nullable=False, default=OutputDestination.LLM)
    channel = Column(SQLEnum(ChannelType), nullable=True, default=ChannelType.TEXT)
    
    # Instruções e encadeamento
    post_instruction = Column(Text, nullable=True)  # Instrução para o LLM sobre como usar a resposta
    next_tool = Column(String(100), nullable=True)  # Nome da próxima ferramenta a executar
    
    # Variável de saída (para código Python)
    print_output_var = Column(String(100), nullable=True)  # Nome da variável a capturar
    
    # Status
    ativa = Column(Boolean, default=True)  # Se a ferramenta está disponível no sistema
    
    # Timestamps
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relacionamentos
    agentes = relationship(
        "Agente",
        secondary="agente_ferramenta",
        back_populates="ferramentas",
        lazy="dynamic"
    )
    variaveis = relationship(
        "FerramentaVariavel",
        back_populates="ferramenta",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Ferramenta(nome='{self.nome}', tipo={self.tool_type}, escopo={self.tool_scope})>"
