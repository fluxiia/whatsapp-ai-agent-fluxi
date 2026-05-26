"""Modelo de usuário do Fluxi (single-tenant — todos veem os mesmos dados)."""
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from database import Base


class User(Base):
    """Usuário com acesso à interface administrativa do Fluxi.

    O primeiro usuário criado é promovido a 'admin' automaticamente. Outros
    cadastros podem ser bloqueados pela env var FLUXI_ALLOW_SIGNUP=false.
    O campo `role` já existe pra evoluir pra multi-tenant sem migration nova.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    nome = Column(String(100), nullable=False)
    senha_hash = Column(String(255), nullable=False)
    ativo = Column(Boolean, nullable=False, default=True)
    role = Column(String(20), nullable=False, default="user")
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    ultimo_login = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"
