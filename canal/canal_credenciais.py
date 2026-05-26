"""
Criptografia simétrica para credenciais de canais (ex.: Telegram bot_token).

A chave é lida da env var FLUXI_SECRET_KEY. Se ausente, derivamos uma chave
estável a partir do hostname + um marker fixo, para que o sistema rode em
dev sem configuração — em produção isso DEVE ser definido explicitamente.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _derivar_chave_fallback() -> bytes:
    semente = (os.uname().nodename if hasattr(os, "uname") else os.getenv("COMPUTERNAME", "fluxi"))
    digest = hashlib.sha256(f"fluxi-canal-fallback::{semente}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _obter_fernet() -> Fernet:
    chave_env = os.getenv("FLUXI_SECRET_KEY")
    if chave_env:
        try:
            return Fernet(chave_env.encode() if isinstance(chave_env, str) else chave_env)
        except Exception as e:
            # Chave inválida — não cair em fallback silencioso. Logar e propagar pra
            # operador notar.
            logger.error("FLUXI_SECRET_KEY inválida (%s). Gere uma com Fernet.generate_key().", e)
            raise
    logger.warning(
        "FLUXI_SECRET_KEY não definida. Usando chave de fallback derivada do host — "
        "definir em produção."
    )
    return Fernet(_derivar_chave_fallback())


def criptografar(payload: dict[str, Any]) -> str:
    f = _obter_fernet()
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f.encrypt(raw).decode("ascii")


def descriptografar(token: Optional[str]) -> dict[str, Any]:
    if not token:
        return {}
    f = _obter_fernet()
    try:
        raw = f.decrypt(token.encode("ascii"))
    except InvalidToken:
        logger.error("Falha ao descriptografar credenciais — chave incorreta ou dados corrompidos.")
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        logger.error("Credenciais descriptografadas não são JSON válido.")
        return {}
