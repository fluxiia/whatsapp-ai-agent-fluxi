"""
Modelo de dados para skills.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Table, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base


agente_skill = Table(
    'agente_skill',
    Base.metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('agente_id', Integer, ForeignKey('agentes.id', ondelete='CASCADE'), nullable=False),
    Column('skill_id', Integer, ForeignKey('skills.id', ondelete='CASCADE'), nullable=False),
    Column('posicao', Integer, default=0),
    Column('ativa', Boolean, default=True),
    UniqueConstraint('agente_id', 'skill_id', name='uq_agente_skill')
)


class Skill(Base):
    """
    Tabela de skills disponíveis no sistema.
    Skills são pacotes de instruções especializadas que o LLM carrega sob demanda.
    """
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False, unique=True, index=True)
    descricao = Column(String(250), nullable=False)
    instrucao_completa = Column(Text, nullable=False)
    script_codigo = Column(Text, nullable=True)
    script_parametros = Column(Text, nullable=True)
    ferramentas_ids = Column(Text, nullable=True)
    categoria = Column(String(50), nullable=False, default='utilitário')
    icone = Column(String(20), nullable=True, default='🔧')
    versao = Column(String(10), nullable=False, default='1.0')
    ativa = Column(Boolean, default=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())

    agentes = relationship(
        "Agente",
        secondary="agente_skill",
        back_populates="skills",
        lazy="dynamic"
    )

    def __repr__(self):
        return f"<Skill(nome='{self.nome}', categoria='{self.categoria}', ativa={self.ativa})>"
