"""Dependency e middleware de autenticação.

- `obter_usuario_atual(request, db)`: pega user_id do cookie de sessão e
  carrega o User; None se não autenticado.
- `AuthMiddleware`: redireciona qualquer GET não autenticado pra /login,
  exceto rotas listadas como públicas. Sem custo extra em rotas protegidas
  porque o user_id é apenas lido do cookie (sem hit no DB no middleware).
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response

from auth.auth_model import User
from auth.auth_service import obter_por_id
from database import get_db

logger = logging.getLogger(__name__)


# Prefixos de rota acessíveis sem autenticação. Web chat público fica aqui
# porque o cliente final do bot não tem (nem precisa de) conta no Fluxi.
ROTAS_PUBLICAS: tuple[str, ...] = (
    "/login",
    "/signup",
    "/logout",
    "/health",
    "/static/",
    "/favicon",
    "/chat/",  # web chat público
    "/docs",
    "/openapi.json",
    "/redoc",
)


def _e_rota_publica(path: str, publicas: Iterable[str] = ROTAS_PUBLICAS) -> bool:
    return any(path == prefixo.rstrip("/") or path.startswith(prefixo) for prefixo in publicas)


def obter_usuario_atual(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    """Retorna o User logado ou None. Use como Depends em handlers que querem
    saber quem está logado mas não exigem login (raro)."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = obter_por_id(db, int(user_id))
    if user is None or not user.ativo:
        # cookie inválido/usuário desativado — limpa sessão
        request.session.pop("user_id", None)
        return None
    return user


def exigir_usuario(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """Versão estrita: lança 401 se não houver usuário válido.

    Não use em rotas web (use o middleware). Útil em endpoints de API JSON.
    """
    from fastapi import HTTPException, status

    user = obter_usuario_atual(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="autenticação necessária",
        )
    return user


class AuthMiddleware(BaseHTTPMiddleware):
    """Redireciona GETs anônimos pra /login; POSTs anônimos retornam 401 JSON.

    Não toca o DB — só checa cookie. A validação real do user (ativo, etc.)
    fica no `obter_usuario_atual` em handlers que precisarem.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if _e_rota_publica(path):
            return await call_next(request)

        user_id = request.session.get("user_id")
        if user_id:
            return await call_next(request)

        if request.method == "GET":
            return RedirectResponse(
                url=f"/login?next={path}",
                status_code=303,
            )
        # Para POST/PUT/DELETE anônimos retornar 401 — não redirecionar
        # (browser perderia o payload).
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"erro": "autenticação necessária", "redirect": "/login"},
            status_code=401,
        )
