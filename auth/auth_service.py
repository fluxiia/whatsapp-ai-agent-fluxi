"""Lógica de autenticação: hash bcrypt, criação, login.

O primeiro usuário cadastrado vira automaticamente `role='admin'` — não há
fluxo separado de bootstrap. Após o primeiro, novos signups dependem de
FLUXI_ALLOW_SIGNUP=true no ambiente (default: bloqueado).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

import bcrypt
from sqlalchemy.orm import Session

from auth.auth_model import User
from auth.auth_schema import UserSignup

logger = logging.getLogger(__name__)


def hash_senha(senha_plana: str) -> str:
    """Gera hash bcrypt da senha em texto. Retorna string ASCII pronta pro DB."""
    if not senha_plana:
        raise ValueError("senha vazia não é permitida")
    return bcrypt.hashpw(senha_plana.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verificar_senha(senha_plana: str, hash_armazenado: str) -> bool:
    """Compara senha em texto com hash armazenado. False em qualquer falha."""
    if not senha_plana or not hash_armazenado:
        return False
    try:
        return bcrypt.checkpw(
            senha_plana.encode("utf-8"), hash_armazenado.encode("ascii")
        )
    except (ValueError, TypeError):
        # hash corrompido ou em formato inválido
        return False


def signup_permitido(db: Session) -> bool:
    """Decide se um novo signup pode ocorrer.

    Regras:
    - Se não existe nenhum usuário, signup é sempre permitido (bootstrap admin).
    - Se já existe usuário, depende de FLUXI_ALLOW_SIGNUP=true.
    """
    total = db.query(User).count()
    if total == 0:
        return True
    flag = os.getenv("FLUXI_ALLOW_SIGNUP", "false").strip().lower()
    return flag in ("1", "true", "yes", "sim")


def obter_por_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.lower().strip()).first()


def obter_por_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def existe_algum_usuario(db: Session) -> bool:
    return db.query(User).first() is not None


def criar_usuario(db: Session, dados: UserSignup) -> User:
    """Cria usuário. Primeiro do sistema vira admin automaticamente.

    Raises:
        ValueError: email já cadastrado ou signup bloqueado por config.
    """
    if not signup_permitido(db):
        raise ValueError(
            "cadastro fechado: este Fluxi não está aceitando novos usuários. "
            "Peça ao admin para habilitar FLUXI_ALLOW_SIGNUP=true."
        )

    email_normalizado = dados.email.lower().strip()
    if obter_por_email(db, email_normalizado):
        raise ValueError(
            f"e-mail já cadastrado: {email_normalizado!r}. "
            "Use a tela de login ou recupere a senha."
        )

    # Primeiro user = admin. Bootstrap automático.
    role = "admin" if not existe_algum_usuario(db) else "user"

    usuario = User(
        email=email_normalizado,
        nome=dados.nome.strip(),
        senha_hash=hash_senha(dados.senha),
        role=role,
        ativo=True,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    logger.info("Usuário criado: id=%s email=%s role=%s", usuario.id, usuario.email, usuario.role)
    return usuario


def resetar_senha_via_env(db: Session) -> Optional[User]:
    """Reset de senha disparado por variáveis de ambiente — usado quando o
    admin perde acesso ao painel.

    Lê FLUXI_ADMIN_RESET_EMAIL + FLUXI_ADMIN_RESET_PASSWORD. Se ambas estiverem
    setadas, procura o usuário pelo email e troca a senha. Não cria usuário
    novo (use signup pra isso). Não exige que seja admin — qualquer user que
    o operador conheça o email pode ser resetado.

    Retorna o User atualizado, ou None se nada foi feito.

    Side effects: commit no DB; log INFO em sucesso, WARNING em falha.

    Pra usar: definir as 2 env vars no .env, reiniciar o container; depois
    remover as variáveis do .env (senão a senha será sobrescrita a cada
    restart).
    """
    email = os.getenv("FLUXI_ADMIN_RESET_EMAIL", "").strip().lower()
    nova_senha = os.getenv("FLUXI_ADMIN_RESET_PASSWORD", "")
    if not email or not nova_senha:
        return None

    if len(nova_senha) < 8:
        logger.warning(
            "Reset via env IGNORADO: FLUXI_ADMIN_RESET_PASSWORD precisa ter ao "
            "menos 8 caracteres (recebido: %d).",
            len(nova_senha),
        )
        return None

    usuario = obter_por_email(db, email)
    if usuario is None:
        logger.warning(
            "Reset via env IGNORADO: nenhum usuário com email %r. "
            "Conferir FLUXI_ADMIN_RESET_EMAIL no .env.",
            email,
        )
        return None

    usuario.senha_hash = hash_senha(nova_senha)
    if not usuario.ativo:
        usuario.ativo = True
    db.commit()
    db.refresh(usuario)
    logger.warning(
        "==========================================================\n"
        "  Senha de %r foi RESETADA via FLUXI_ADMIN_RESET_*.\n"
        "  >>> REMOVA essas variáveis do .env agora <<<\n"
        "  Senão a senha será sobrescrita a cada restart.\n"
        "==========================================================",
        usuario.email,
    )
    return usuario


def autenticar(db: Session, email: str, senha: str) -> Optional[User]:
    """Retorna o User se credenciais batem e ativo=True; senão None.

    Não distingue 'email inexistente' de 'senha errada' — mesma resposta pra
    evitar enumeração de contas.
    """
    usuario = obter_por_email(db, email)
    if usuario is None or not usuario.ativo:
        return None
    if not verificar_senha(senha, usuario.senha_hash):
        return None
    usuario.ultimo_login = datetime.now()
    db.commit()
    return usuario
