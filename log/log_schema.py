"""
Schemas Pydantic e Enums para o sistema de logging.
"""
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from datetime import datetime


# ── Enums ────────────────────────────────────────────────────

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogModule(str, Enum):
    AGENTE = "agente"
    MENSAGEM = "mensagem"
    CODING = "coding"
    FERRAMENTA = "ferramenta"
    SESSAO = "sessao"
    LLM = "llm"
    RAG = "rag"
    MCP = "mcp"
    SKILL = "skill"
    SANDBOX = "sandbox"
    SISTEMA = "sistema"


# ── Schemas ──────────────────────────────────────────────────

class LogEntryCreate(BaseModel):
    level: str
    module: str
    sub_module: Optional[str] = None
    message: str
    extra_json: Optional[str] = None
    traceback: Optional[str] = None
    session_id: Optional[int] = None
    request_id: Optional[str] = None


class LogEntryResponse(BaseModel):
    id: int
    timestamp: datetime
    level: str
    module: str
    sub_module: Optional[str] = None
    message: str
    extra_json: Optional[str] = None
    traceback: Optional[str] = None
    session_id: Optional[int] = None
    request_id: Optional[str] = None

    class Config:
        from_attributes = True


class LogFilterParams(BaseModel):
    module: Optional[str] = None
    sub_module: Optional[str] = None
    level: Optional[str] = None
    search: Optional[str] = None
    session_id: Optional[int] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    page: int = 1
    per_page: int = 50


class LogStatsResponse(BaseModel):
    total: int = 0
    by_level: Dict[str, int] = {}
    by_module: Dict[str, int] = {}
    errors_last_hour: int = 0
    errors_by_module: Dict[str, int] = {}
