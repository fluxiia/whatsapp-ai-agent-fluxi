"""
Schemas Pydantic para validação de sessões.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SessaoBase(BaseModel):
    """Schema base para sessão."""
    nome: str = Field(..., description="Nome identificador da sessão")
    plataforma: str = Field(default="whatsapp", description="Canal: 'whatsapp' ou 'telegram'")
    auto_responder: bool = Field(default=True, description="Auto responder mensagens")
    salvar_historico: bool = Field(default=True, description="Salvar histórico de mensagens")


class SessaoCriar(SessaoBase):
    """Schema para criar nova sessão.

    Para Telegram, `telegram_bot_token` é obrigatório e será criptografado
    antes de gravar em `Sessao.credenciais`.
    """
    telegram_bot_token: Optional[str] = Field(
        default=None, description="Bot token do Telegram (apenas plataforma=telegram)"
    )


class SessaoAtualizar(BaseModel):
    """Schema para atualizar sessão."""
    nome: Optional[str] = None
    auto_responder: Optional[bool] = None
    salvar_historico: Optional[bool] = None
    ativa: Optional[bool] = None
    agente_ativo_id: Optional[int] = None


class SessaoResposta(SessaoBase):
    """Schema de resposta com dados completos."""
    id: int
    telefone: Optional[str] = None
    identificador: Optional[str] = None
    status: str
    qr_code: Optional[str] = None
    ativa: bool
    agente_ativo_id: Optional[int] = None
    criado_em: datetime
    atualizado_em: Optional[datetime] = None
    ultima_conexao: Optional[datetime] = None

    class Config:
        from_attributes = True


class SessaoConectar(BaseModel):
    """Schema para conectar sessão."""
    sessao_id: int


class SessaoDesconectar(BaseModel):
    """Schema para desconectar sessão."""
    sessao_id: int


class SessaoStatusResposta(BaseModel):
    """Schema de resposta de status da sessão."""
    id: int
    nome: str
    status: str
    telefone: Optional[str] = None
    qr_code: Optional[str] = None
    mensagem: str
