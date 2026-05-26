"""Schemas Pydantic do auth — validação de entradas (login/signup)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserSignup(BaseModel):
    """Cadastro de novo usuário."""

    nome: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    senha: str = Field(..., min_length=8, max_length=128)


class UserLogin(BaseModel):
    """Login por e-mail e senha."""

    email: EmailStr
    senha: str = Field(..., min_length=1, max_length=128)


class UserPublico(BaseModel):
    """Representação segura (sem senha_hash) — usada em templates/logs."""

    id: int
    email: EmailStr
    nome: str
    role: str
    ativo: bool
    criado_em: datetime
    ultimo_login: datetime | None = None

    class Config:
        from_attributes = True
