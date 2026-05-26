"""I/O de arquivo + helpers de mime/path.

Tudo aqui mexe so com bytes/path. Quem cria registro `Midia` no banco eh
o `midia_service.registrar_midia`.

Layout: `{upload_base}/midias/{sessao_id}/{ts}_{rand}.{ext}`.
"""
from __future__ import annotations

import base64
import io
import logging
import secrets
import time
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


_MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/wav": "wav",
    "audio/opus": "opus",
    "audio/aac": "aac",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/x-msvideo": "avi",
    "video/x-matroska": "mkv",
    "application/pdf": "pdf",
    "application/zip": "zip",
    "application/json": "json",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/csv": "csv",
    "text/plain": "txt",
    "text/html": "html",
    "application/octet-stream": "bin",
}


def ext_de_mime(mime: Optional[str]) -> str:
    if not mime:
        return "bin"
    base = mime.split(";")[0].strip().lower()
    return _MIME_TO_EXT.get(base, "bin")


def detectar_mime_imagem(conteudo: bytes) -> Optional[str]:
    """Tenta abrir como imagem e devolve mime; None se nao for imagem."""
    try:
        with Image.open(io.BytesIO(conteudo)) as img:
            fmt = (img.format or "").lower()
        if not fmt:
            return None
        return f"image/{'jpeg' if fmt == 'jpeg' else fmt}"
    except Exception:
        return None


def gerar_media_id(
    sessao_id: int,
    chat_id: Optional[str],
    origem: str,
) -> str:
    """Gera media_id estavel.

    Formatos:
    - `s{sessao_id}_{chat_digits}_{origem}_{rand}` (inbound do usuario)
    - `gen_{uuid}` (origem ia/gerada)
    - `tratada_{uuid}` (origem tratada)
    - `baixada_{uuid}` (origem baixada de url)
    """
    o = (origem or "upload").lower()
    if o in ("ia", "gen_arte", "gerada"):
        return f"gen_{uuid.uuid4().hex}"
    if o == "tratada":
        return f"tratada_{uuid.uuid4().hex}"
    if o == "baixada":
        return f"baixada_{uuid.uuid4().hex}"
    digits = "".join(c for c in (chat_id or "") if c.isdigit())[:20] or "x"
    rand = secrets.token_hex(5)
    return f"s{sessao_id}_{digits}_{o}_{rand}"


def _base_midias(upload_base: str, sessao_id: int) -> Path:
    base = Path(upload_base) / "midias" / str(sessao_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def salvar_bytes(
    upload_base: str,
    sessao_id: int,
    conteudo: bytes,
    mime: Optional[str],
) -> dict:
    """Persiste bytes em disco. Devolve dict com path/mime/tamanho.

    Quem chama eh responsavel por criar o registro `Midia` (chamando
    `midia_service.registrar_midia`).
    """
    if not conteudo:
        raise ValueError("conteudo vazio nao pode ser salvo")

    mime_final = mime or detectar_mime_imagem(conteudo) or "application/octet-stream"
    ext = ext_de_mime(mime_final)
    base = _base_midias(upload_base, sessao_id)
    ts = int(time.time())
    rand = secrets.token_hex(4)
    destino = base / f"{ts}_{rand}.{ext}"
    destino.write_bytes(conteudo)
    return {
        "path": str(destino),
        "mime": mime_final,
        "tamanho": len(conteudo),
    }


def ler_bytes(path: str) -> bytes:
    """Le bytes do arquivo. Levanta FileNotFoundError se nao existir."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"arquivo nao encontrado: {path}")
    return p.read_bytes()


def to_base64_data_url(path: str, mime: Optional[str] = None) -> str:
    """Retorna `data:<mime>;base64,...` — util pra LLM/clients que querem inline."""
    conteudo = ler_bytes(path)
    mime_final = mime or detectar_mime_imagem(conteudo) or "application/octet-stream"
    encoded = base64.b64encode(conteudo).decode("ascii")
    return f"data:{mime_final};base64,{encoded}"


def deletar_arquivo(path: str) -> bool:
    """Remove arquivo se existir. True = removeu, False = ja nao existia."""
    p = Path(path)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError as exc:
        logger.warning("midia.storage.deletar.erro path=%s erro=%s", path, exc)
        return False


def path_dentro_uploads(path: str, upload_base: str) -> bool:
    """Validacao anti path-traversal: confirma que `path` resolve dentro de `upload_base`."""
    try:
        base = Path(upload_base).resolve()
        alvo = Path(path).resolve()
        return str(alvo).startswith(str(base))
    except Exception:
        return False
