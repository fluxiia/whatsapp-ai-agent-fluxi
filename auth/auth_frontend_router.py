"""Rotas web de autenticação: /login, /signup, /logout."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from auth.auth_schema import UserLogin, UserSignup
from auth.auth_service import (
    autenticar,
    criar_usuario,
    existe_algum_usuario,
    signup_permitido,
)
from database import get_db

router = APIRouter(tags=["Auth"])
templates = Jinja2Templates(directory="templates")


def _destino_seguro(next_path: Optional[str]) -> str:
    """Evita open redirect: só aceita paths que começam com '/' e não '//'."""
    if not next_path:
        return "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    return next_path


@router.get("/login", response_class=HTMLResponse)
def pagina_login(
    request: Request,
    next: Optional[str] = None,
    erro: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Tela de login. Se nenhum usuário existe ainda, redireciona pra signup."""
    if not existe_algum_usuario(db):
        return RedirectResponse(url="/signup?bootstrap=1", status_code=303)

    if request.session.get("user_id"):
        return RedirectResponse(url=_destino_seguro(next), status_code=303)

    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "erro": erro,
            "next": _destino_seguro(next),
            "titulo": "Entrar — Fluxi",
            "signup_aberto": signup_permitido(db),
        },
    )


@router.post("/login")
def fazer_login(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    """Processa o formulário de login."""
    try:
        UserLogin(email=email, senha=senha)
    except ValidationError:
        return RedirectResponse(
            url=f"/login?erro={_quote('E-mail ou senha em formato inválido.')}&next={_quote(next)}",
            status_code=303,
        )

    user = autenticar(db, email, senha)
    if user is None:
        return RedirectResponse(
            url=f"/login?erro={_quote('E-mail ou senha incorretos.')}&next={_quote(next)}",
            status_code=303,
        )

    request.session["user_id"] = user.id
    request.session["user_email"] = user.email
    request.session["user_nome"] = user.nome
    request.session["user_role"] = user.role
    return RedirectResponse(url=_destino_seguro(next), status_code=303)


@router.get("/signup", response_class=HTMLResponse)
def pagina_signup(
    request: Request,
    erro: Optional[str] = None,
    bootstrap: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Tela de cadastro. Disponível apenas se permitido pela config."""
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    if not signup_permitido(db):
        return templates.TemplateResponse(
            "auth/signup_fechado.html",
            {"request": request, "titulo": "Cadastro fechado — Fluxi"},
        )

    return templates.TemplateResponse(
        "auth/signup.html",
        {
            "request": request,
            "erro": erro,
            "is_bootstrap": bool(bootstrap),
            "titulo": "Criar conta — Fluxi",
        },
    )


@router.post("/signup")
def fazer_signup(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(...),
    senha_confirmar: str = Form(...),
    db: Session = Depends(get_db),
):
    """Processa o formulário de cadastro."""
    if senha != senha_confirmar:
        return RedirectResponse(
            url=f"/signup?erro={_quote('As senhas não conferem.')}",
            status_code=303,
        )

    try:
        dados = UserSignup(nome=nome, email=email, senha=senha)
    except ValidationError as ve:
        primeira = ve.errors()[0] if ve.errors() else {"msg": "dados inválidos"}
        return RedirectResponse(
            url=f"/signup?erro={_quote(str(primeira.get('msg', 'dados inválidos')))}",
            status_code=303,
        )

    try:
        user = criar_usuario(db, dados)
    except ValueError as e:
        return RedirectResponse(
            url=f"/signup?erro={_quote(str(e))}",
            status_code=303,
        )

    # auto-login após signup
    request.session["user_id"] = user.id
    request.session["user_email"] = user.email
    request.session["user_nome"] = user.nome
    request.session["user_role"] = user.role
    return RedirectResponse(url="/", status_code=303)


@router.get("/logout")
@router.post("/logout")
def fazer_logout(request: Request):
    """Limpa a sessão e volta pra tela de login."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


def _quote(s: str) -> str:
    """Helper local — encurta urllib.parse.quote."""
    from urllib.parse import quote
    return quote(s)
