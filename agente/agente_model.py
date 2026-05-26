"""
Modelo de dados para agentes.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Table, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base


# Tabela de associação Agente-Ferramenta (many-to-many)
agente_ferramenta = Table(
    'agente_ferramenta',
    Base.metadata,
    Column('agente_id', Integer, ForeignKey('agentes.id', ondelete='CASCADE'), primary_key=True),
    Column('ferramenta_id', Integer, ForeignKey('ferramentas.id', ondelete='CASCADE'), primary_key=True),
    Column('ativa', Boolean, default=True),  # Se a ferramenta está ativa para este agente
    Column('criado_em', DateTime(timezone=True), server_default=func.now())
)


class Agente(Base):
    """
    Tabela de agentes.
    Cada agente tem seu próprio system prompt e pode ter até 20 ferramentas ativas.
    """
    __tablename__ = "agentes"

    id = Column(Integer, primary_key=True, index=True)
    sessao_id = Column(Integer, ForeignKey("sessoes.id", ondelete='CASCADE'), nullable=False, index=True)
    
    # Identificação
    codigo = Column(String(10), nullable=False, index=True)  # Ex: "01", "02", etc.
    nome = Column(String(100), nullable=False)
    descricao = Column(Text, nullable=True)
    
    # System Prompt (campos do agente)
    agente_papel = Column(Text, nullable=False)
    agente_objetivo = Column(Text, nullable=False)
    agente_politicas = Column(Text, nullable=False)
    agente_tarefa = Column(Text, nullable=False)
    agente_objetivo_explicito = Column(Text, nullable=False)
    agente_publico = Column(Text, nullable=False)
    agente_restricoes = Column(Text, nullable=False)
    
    # Configurações LLM específicas do agente
    provedor_llm_id = Column(Integer, ForeignKey("provedores_llm.id", ondelete='SET NULL'), nullable=True)
    modelo_llm = Column(String(100), nullable=True)
    temperatura = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    top_p = Column(Float, nullable=True)
    frequency_penalty = Column(Float, nullable=True)  # -2.0 a 2.0 (evita repetição)
    presence_penalty = Column(Float, nullable=True)   # -2.0 a 2.0 (novos tópicos)
    
    # RAG (Base de Conhecimento)
    rag_id = Column(Integer, ForeignKey("rags.id", ondelete='SET NULL'), nullable=True, index=True)
    
    # Modo Autônomo (Sandbox Interno)
    internal_sandbox_ativo = Column(Boolean, default=False)

    # Coding Agent — quando True, este agente é um agente de coding independente
    is_coding_agent = Column(Boolean, default=False)

    # Status
    ativo = Column(Boolean, default=True)

    # Timestamps
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())

    # Relacionamentos
    sessao = relationship("Sessao", back_populates="agentes", foreign_keys=[sessao_id])
    ferramentas = relationship(
        "Ferramenta",
        secondary=agente_ferramenta,
        back_populates="agentes",
        lazy="dynamic"
    )
    rag = relationship("RAG", back_populates="agentes", foreign_keys=[rag_id])
    mcp_clients = relationship("MCPClient", back_populates="agente", cascade="all, delete-orphan")
    skills = relationship(
        "Skill",
        secondary="agente_skill",
        back_populates="agentes",
        lazy="dynamic"
    )
    coding_session = relationship(
        "CodingSession",
        back_populates="agente",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Agente(codigo='{self.codigo}', nome='{self.nome}', sessao_id={self.sessao_id})>"
