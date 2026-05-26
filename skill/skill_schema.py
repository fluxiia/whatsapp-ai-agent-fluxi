"""
Schemas Pydantic para skills.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class SkillBase(BaseModel):
    nome: str
    descricao: str = Field(..., max_length=250)
    instrucao_completa: str
    script_codigo: Optional[str] = None
    script_parametros: Optional[str] = None
    ferramentas_ids: Optional[str] = None
    categoria: str = "utilitário"
    icone: Optional[str] = "🔧"
    versao: str = "1.0"
    ativa: bool = True


class SkillCriar(SkillBase):
    pass


class SkillAtualizar(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    instrucao_completa: Optional[str] = None
    script_codigo: Optional[str] = None
    script_parametros: Optional[str] = None
    ferramentas_ids: Optional[str] = None
    categoria: Optional[str] = None
    icone: Optional[str] = None
    versao: Optional[str] = None
    ativa: Optional[bool] = None


class SkillResposta(SkillBase):
    id: int
    criado_em: datetime
    atualizado_em: Optional[datetime] = None

    class Config:
        from_attributes = True


class AgenteSkillsAtualizar(BaseModel):
    skills: List[int] = Field(..., description="Lista ordenada de IDs de skills")
