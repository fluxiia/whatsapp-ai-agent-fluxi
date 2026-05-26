"""
Schemas Pydantic para o Coding Agent.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════
# CODING SESSION
# ══════════════════════════════════════════════════════════

class CodingSessionBase(BaseModel):
    workspace_mode: str = Field("sandbox", description="'sandbox' ou 'host_path'")
    workspace_path: Optional[str] = Field(None, description="Caminho do workspace (para host_path)")
    extra_read_paths: Optional[List[str]] = Field(default_factory=list)
    routing_prefix: str = Field("#code", description="Prefixo WhatsApp para rotear ao coding agent")
    modelo_coding: Optional[str] = None
    thinking_mode: bool = True
    max_iteracoes: int = 200
    timeout_shell_rapido: int = 30
    timeout_shell_background: int = 3600


class CodingSessionCriar(CodingSessionBase):
    agente_id: int


class CodingSessionAtualizar(BaseModel):
    workspace_mode: Optional[str] = None
    workspace_path: Optional[str] = None
    extra_read_paths: Optional[List[str]] = None
    routing_prefix: Optional[str] = None
    modelo_coding: Optional[str] = None
    thinking_mode: Optional[bool] = None
    max_iteracoes: Optional[int] = None
    timeout_shell_rapido: Optional[int] = None
    timeout_shell_background: Optional[int] = None
    memory_content: Optional[str] = None
    ativa: Optional[bool] = None


class CodingSessionResposta(CodingSessionBase):
    id: int
    agente_id: int
    workspace_path: str
    memory_content: Optional[str] = ""
    ativa: bool
    criado_em: datetime
    atualizado_em: Optional[datetime] = None

    class Config:
        from_attributes = True


# ══════════════════════════════════════════════════════════
# CODING TASK
# ══════════════════════════════════════════════════════════

class CodingTaskBase(BaseModel):
    titulo: str = "Tarefa sem título"
    objetivo: Optional[str] = None


class CodingTaskCriar(CodingTaskBase):
    coding_session_id: int
    telefone_cliente: Optional[str] = None
    objetivo: Optional[str] = None


class CodingTaskResposta(CodingTaskBase):
    id: int
    coding_session_id: int
    telefone_cliente: Optional[str] = None
    status: str
    messages: List[Dict[str, Any]] = []
    artifacts: List[Dict[str, Any]] = []
    active_skills: List[str] = []
    shell_sessions: Dict[str, Any] = {}
    tokens_input_total: int = 0
    tokens_output_total: int = 0
    iteracoes: int = 0
    error: Optional[str] = None
    criado_em: datetime
    atualizado_em: Optional[datetime] = None
    completado_em: Optional[datetime] = None

    class Config:
        from_attributes = True


class CodingTaskResumo(BaseModel):
    """Versão compacta para listagens."""
    id: int
    coding_session_id: int
    titulo: str
    status: str
    iteracoes: int
    artifacts_count: int = 0
    criado_em: datetime
    completado_em: Optional[datetime] = None

    class Config:
        from_attributes = True


# ══════════════════════════════════════════════════════════
# MENSAGEM CODING (para API de envio direto)
# ══════════════════════════════════════════════════════════

class CodingMensagemEnviar(BaseModel):
    """Envia uma mensagem diretamente ao coding agent via API (sem WhatsApp)."""
    coding_session_id: int
    task_id: Optional[int] = Field(None, description="Se informado, continua tarefa existente")
    mensagem: str
    telefone_cliente: Optional[str] = None


class CodingMensagemResposta(BaseModel):
    task_id: int
    titulo: str
    status: str
    resposta: Optional[str] = None
    artifacts: List[Dict[str, Any]] = []
    tokens_input: int = 0
    tokens_output: int = 0
    iteracoes: int = 0
    tempo_ms: int = 0


# ══════════════════════════════════════════════════════════
# MEMÓRIA
# ══════════════════════════════════════════════════════════

class MemoriaAtualizar(BaseModel):
    content: str = Field(..., description="Novo conteúdo da memória (substitui o atual)")


class MemoriaResposta(BaseModel):
    coding_session_id: int
    content: str
    tamanho_chars: int


# ══════════════════════════════════════════════════════════
# STATUS DE TAREFA (para polling)
# ══════════════════════════════════════════════════════════

class TaskStatusResposta(BaseModel):
    task_id: int
    status: str
    titulo: str
    iteracoes: int
    shell_sessions_ativas: List[str] = []
    artifacts: List[Dict[str, Any]] = []
    ultima_mensagem_assistente: Optional[str] = None
    error: Optional[str] = None
    completado_em: Optional[datetime] = None
