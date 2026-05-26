"""
Modelo de dados para sessões WhatsApp.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base


class Sessao(Base):
    """
    Tabela de sessões WhatsApp.
    Cada sessão representa uma conta WhatsApp conectada e pode ter múltiplos agentes.
    """
    __tablename__ = "sessoes"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False, unique=True, index=True)
    # Canal de comunicação ('whatsapp' | 'telegram'). Default mantém compat com bancos antigos.
    plataforma = Column(String(20), nullable=False, default="whatsapp", index=True)
    telefone = Column(String(20), nullable=True, index=True)  # Telefone conectado (após conexão) — uso WhatsApp
    telefone_pareamento = Column(String(20), nullable=True)  # Telefone para pair code (antes de conectar)
    # Identificador genérico do canal (telefone p/ WA, bot_id/username p/ TG).
    # Convive com 'telefone' durante o período de migração.
    identificador = Column(String(100), nullable=True, index=True)
    # Credenciais por plataforma (JSON criptografado p/ Telegram bot_token). Nullable.
    credenciais = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="desconectado")  # desconectado, conectando, conectado, erro
    ativa = Column(Boolean, default=True)
    auto_responder = Column(Boolean, default=True)
    salvar_historico = Column(Boolean, default=True)
    
    # Agente ativo (qual agente está respondendo no momento)
    agente_ativo_id = Column(Integer, ForeignKey("agentes.id"), nullable=True, index=True)
    
    # QR Code
    qr_code = Column(Text, nullable=True)
    qr_code_gerado_em = Column(DateTime, nullable=True)  # Timestamp do QR Code
    
    # Metadados
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())
    ultima_conexao = Column(DateTime(timezone=True), nullable=True)
    
    # Relacionamentos
    mensagens = relationship("Mensagem", back_populates="sessao", cascade="all, delete-orphan")
    agentes = relationship(
        "Agente", 
        back_populates="sessao", 
        cascade="all, delete-orphan", 
        foreign_keys="[Agente.sessao_id]",
        overlaps="agente_ativo"
    )
    agente_ativo = relationship(
        "Agente", 
        foreign_keys=[agente_ativo_id], 
        post_update=True,
        overlaps="agentes"
    )
    tipos_mensagem = relationship(
        "SessaoTipoMensagem",
        back_populates="sessao",
        cascade="all, delete-orphan"
    )
    comandos = relationship(
        "SessaoComando",
        back_populates="sessao",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Sessao(nome='{self.nome}', telefone='{self.telefone}', status='{self.status}')>"
