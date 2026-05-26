"""
Schemas Pydantic para validação de agentes.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class AgenteBase(BaseModel):
    """Schema base para agente."""
    codigo: str = Field(..., description="Código do agente (ex: 01, 02)")
    nome: str = Field(..., description="Nome do agente")
    descricao: Optional[str] = Field(None, description="Descrição do agente")
    agente_papel: str = Field(..., description="Papel do agente")
    agente_objetivo: str = Field(..., description="Objetivo do agente")
    agente_politicas: str = Field(..., description="Políticas do agente")
    agente_tarefa: str = Field(..., description="Tarefa do agente")
    agente_objetivo_explicito: str = Field(..., description="Objetivo explícito do agente")
    agente_publico: str = Field(..., description="Público-alvo do agente")
    agente_restricoes: str = Field(..., description="Restrições do agente")
    provedor_llm_id: Optional[int] = Field(None, description="ID do provedor LLM (null = padrão global)")
    modelo_llm: Optional[str] = Field(None, description="Modelo LLM específico")
    temperatura: Optional[float] = Field(None, description="Temperatura do modelo (0.0 a 2.0)")
    max_tokens: Optional[int] = Field(None, description="Máximo de tokens")
    top_p: Optional[float] = Field(None, description="Top P (0.0 a 1.0)")
    frequency_penalty: Optional[float] = Field(None, description="Frequency penalty (-2.0 a 2.0)")
    presence_penalty: Optional[float] = Field(None, description="Presence penalty (-2.0 a 2.0)")
    ativo: bool = Field(default=True, description="Se o agente está ativo")


class AgenteCriar(AgenteBase):
    """Schema para criar novo agente."""
    sessao_id: int


class AgenteAtualizar(BaseModel):
    """Schema para atualizar agente."""
    codigo: Optional[str] = None
    nome: Optional[str] = None
    descricao: Optional[str] = None
    agente_papel: Optional[str] = None
    agente_objetivo: Optional[str] = None
    agente_politicas: Optional[str] = None
    agente_tarefa: Optional[str] = None
    agente_objetivo_explicito: Optional[str] = None
    agente_publico: Optional[str] = None
    agente_restricoes: Optional[str] = None
    provedor_llm_id: Optional[int] = None
    modelo_llm: Optional[str] = None
    temperatura: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    rag_id: Optional[int] = None
    ativo: Optional[bool] = None


class AgenteResposta(AgenteBase):
    """Schema de resposta com dados completos."""
    id: int
    sessao_id: int
    provedor_llm_id: Optional[int] = None
    rag_id: Optional[int] = None
    internal_sandbox_ativo: Optional[bool] = False
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    criado_em: datetime
    atualizado_em: Optional[datetime] = None

    class Config:
        from_attributes = True


class AgenteFerramentaAssociar(BaseModel):
    """Schema para associar/desassociar ferramenta de um agente."""
    ferramenta_id: int
    ativa: bool = True


class AgenteFerramentasAtualizar(BaseModel):
    """Schema para atualizar ferramentas de um agente."""
    ferramentas: List[int] = Field(..., description="Lista de IDs de ferramentas (máximo 20)")
