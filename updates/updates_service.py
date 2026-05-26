"""
Verifica se há versão mais nova do Fluxi no GitHub público.

Sem autenticação (API pública do GitHub aceita 60 req/h por IP). Cacheamos
em memória por 1h pra reduzir latência e ficar bem longe do rate limit.

Endpoint usado: /repos/{repo}/releases/latest — pula pre-releases e drafts.

Configurável via env:
- FLUXI_UPDATES_REPO    (default: fluxiia/whatsapp-ai-agent-fluxi)
- FLUXI_UPDATES_ENABLED ("false" desativa o check; default ativo)
- FLUXI_UPDATES_TTL     (segundos de cache; default 3600)
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

REPO = os.getenv("FLUXI_UPDATES_REPO", "fluxiia/whatsapp-ai-agent-fluxi")
TTL_SEGUNDOS = int(os.getenv("FLUXI_UPDATES_TTL", "3600"))
HABILITADO = os.getenv("FLUXI_UPDATES_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "sim",
)

_GITHUB_RELEASES = f"https://api.github.com/repos/{REPO}/releases/latest"
_GITHUB_TAGS = f"https://api.github.com/repos/{REPO}/tags"
_USER_AGENT = "Fluxi-UpdateChecker"

# Cache em memória. Chaves: ts (timestamp), data (dict|None), err (str|None).
_cache: dict[str, Any] = {"ts": 0.0, "data": None, "err": None}


def versao_atual() -> str:
    """Lê VERSION da raiz do projeto. Fallback: 'dev'.

    Mantemos um arquivo de texto puro em vez de uma constante Python pra
    deixar fácil bumpar a versão via script/CI sem mexer em código.
    """
    arq = Path(__file__).resolve().parent.parent / "VERSION"
    if not arq.exists():
        return "dev"
    return arq.read_text(encoding="utf-8").strip() or "dev"


def _normalizar_tag(tag: str) -> str:
    """Tira o 'v' inicial e espaços. 'v1.2.3' → '1.2.3'."""
    return (tag or "").strip().lstrip("vV")


def _parsear_versao(v: str) -> tuple[int, int, int]:
    """Converte string SemVer em tupla pra comparação. Falha gracefully com (0,0,0)."""
    partes = _normalizar_tag(v).split(".")
    out: list[int] = []
    for p in partes[:3]:
        # Pode vir '3', '3-rc1', '3+build.5' — pega só o número
        num = ""
        for c in p:
            if c.isdigit():
                num += c
            else:
                break
        out.append(int(num) if num else 0)
    while len(out) < 3:
        out.append(0)
    return out[0], out[1], out[2]


def comparar(atual: str, remota: str) -> int:
    """Retorna -1 se atual < remota, 0 se iguais, 1 se atual > remota."""
    a = _parsear_versao(atual)
    b = _parsear_versao(remota)
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def _headers_github() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
    }


def _consultar_releases_latest() -> Optional[dict[str, Any]]:
    """Endpoint principal — pula pre-releases e drafts.

    Retorna None se 404 (repo sem releases publicadas). Para outros erros
    HTTP, propaga exceção pro caller decidir.
    """
    r = httpx.get(_GITHUB_RELEASES, timeout=5.0, headers=_headers_github())
    if r.status_code == 404:
        return None
    r.raise_for_status()
    payload = r.json()
    return {
        "tag_name": _normalizar_tag(payload.get("tag_name", "")),
        "nome_release": payload.get("name") or payload.get("tag_name", ""),
        "notas": payload.get("body") or "",
        "url": payload.get("html_url") or f"https://github.com/{REPO}/releases",
        "publicada_em": payload.get("published_at"),
        "fonte": "release",
    }


def _consultar_tag_mais_nova() -> Optional[dict[str, Any]]:
    """Fallback: pega a primeira tag listada (GitHub ordena por commit desc).

    Útil quando o repo ainda não tem release formal publicada, mas já tem
    tags semver. Sem release notes — só a versão.
    """
    r = httpx.get(_GITHUB_TAGS, timeout=5.0, headers=_headers_github())
    r.raise_for_status()
    tags = r.json()
    if not isinstance(tags, list) or not tags:
        return None
    primeira = tags[0]
    nome = primeira.get("name", "")
    return {
        "tag_name": _normalizar_tag(nome),
        "nome_release": nome,
        "notas": "",
        "url": f"https://github.com/{REPO}/releases",
        "publicada_em": None,
        "fonte": "tag",
    }


def _consultar_github() -> Optional[dict[str, Any]]:
    """Tenta release oficial primeiro; cai pra tags se não houver release."""
    try:
        release = _consultar_releases_latest()
        if release is not None:
            return release
    except httpx.HTTPStatusError:
        # Erro de HTTP no /releases/latest: tenta tags como último recurso
        pass
    return _consultar_tag_mais_nova()


def obter_release_remota(forcar: bool = False) -> Optional[dict[str, Any]]:
    """Retorna dados da última release publicada (cacheado).

    Se a consulta falhar, retorna o último resultado válido (mesmo expirado)
    e guarda o erro no cache pra UI exibir.
    """
    if not HABILITADO:
        return None

    agora = time.time()
    # Cacheamos tanto sucesso quanto "sem release ainda" pra não pingar o
    # GitHub a cada page load enquanto o repo não tiver release publicada.
    ja_consultou = _cache["ts"] > 0
    fresco = ja_consultou and (agora - _cache["ts"]) < TTL_SEGUNDOS
    if fresco and not forcar:
        return _cache["data"]

    try:
        data = _consultar_github()
        _cache["data"] = data
        _cache["ts"] = agora
        _cache["err"] = None
        if data is None:
            logger.info("Update check: repo %s não tem releases nem tags ainda", REPO)
        else:
            logger.info("Update check: última versão remota = %s (%s)", data.get("tag_name"), data.get("fonte"))
    except httpx.HTTPStatusError as e:
        _cache["err"] = f"GitHub respondeu {e.response.status_code}"
        logger.warning("Update check falhou: %s", _cache["err"])
    except (httpx.HTTPError, ValueError) as e:
        _cache["err"] = f"erro de rede: {type(e).__name__}"
        logger.warning("Update check falhou: %s (%s)", _cache["err"], e)
    return _cache["data"]


def status() -> dict[str, Any]:
    """Snapshot pronto pra UI ou JSON.

    Exemplo de retorno quando há atualização disponível:

        {
          "atual": "0.3.0",
          "remota": "0.4.0",
          "tem_update": True,
          "nome_release": "v0.4.0 — Coding agent v2",
          "url": "https://github.com/.../releases/tag/v0.4.0",
          "notas": "...",
          "publicada_em": "2026-06-10T12:34:56Z",
          "repo": "fluxiia/whatsapp-ai-agent-fluxi",
          "habilitado": True,
          "erro": None
        }
    """
    atual = versao_atual()
    base = {
        "atual": atual,
        "remota": None,
        "tem_update": False,
        "nome_release": None,
        "url": f"https://github.com/{REPO}/releases",
        "notas": None,
        "publicada_em": None,
        "repo": REPO,
        "habilitado": HABILITADO,
        "erro": None,
    }
    if not HABILITADO:
        base["erro"] = "verificação desativada (FLUXI_UPDATES_ENABLED=false)"
        return base

    remota = obter_release_remota()
    if remota is None:
        # Distinguir "ainda não tem release" de "falha de rede"
        if _cache.get("err"):
            base["erro"] = _cache["err"]
        else:
            base["erro"] = "este repositório ainda não publicou releases nem tags"
        return base

    base.update({
        "remota": remota["tag_name"],
        "nome_release": remota["nome_release"],
        "url": remota["url"],
        "notas": remota["notas"],
        "publicada_em": remota["publicada_em"],
        "fonte": remota.get("fonte", "release"),
        "tem_update": comparar(atual, remota["tag_name"]) < 0,
        "erro": _cache.get("err"),
    })
    return base
