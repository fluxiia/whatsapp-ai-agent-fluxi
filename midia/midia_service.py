"""Service da tabela `midias`.

Responsabilidades:
- Persistir bytes via `midia_storage` e criar registro `Midia`
- Buscar/vincular/marcar para delete
- Purga de expirados (chamada por background task)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from config.config_service import ConfiguracaoService
from midia import midia_storage
from midia.midia_model import Midia, OrigemMidia, VinculadaTipo

logger = logging.getLogger(__name__)


def _mapear_origem(origem: Optional[str]) -> OrigemMidia:
    """Mapeia string solta pro enum. Fallback seguro = upload."""
    o = (origem or "upload").lower()
    if o.startswith("upload"):
        return OrigemMidia.upload
    if o in ("ia", "gerada", "gen", "gen_arte"):
        return OrigemMidia.gerada
    if o == "tratada":
        return OrigemMidia.tratada
    if o == "baixada":
        return OrigemMidia.baixada
    logger.warning("midia.origem.desconhecida origem=%s fallback=upload", o)
    return OrigemMidia.upload


def _mapear_vinculada(valor) -> Optional[VinculadaTipo]:
    if valor is None:
        return None
    if isinstance(valor, VinculadaTipo):
        return valor
    try:
        return VinculadaTipo(str(valor).lower())
    except ValueError:
        logger.warning("midia.vinculada.desconhecido valor=%s fallback=outros", valor)
        return VinculadaTipo.outros


def _upload_base(db: Session) -> str:
    return ConfiguracaoService.obter_valor(db, "sistema_diretorio_uploads", "./uploads")


def registrar_midia(
    db: Session,
    sessao_id: int,
    chat_id: Optional[str],
    conteudo: bytes,
    mime: Optional[str],
    origem: str = "upload",
    vinculada_tipo: Optional[str] = None,
    vinculada_id: Optional[int] = None,
    ttl_dias: Optional[int] = None,
) -> Midia:
    """Salva bytes no FS e cria registro `Midia`. Retorna a instancia ja com PK.

    `ttl_dias=None` -> usa config `sistema_midia_ttl_dias` (default 120).
    `ttl_dias=0` -> arquivo sem TTL (nao sera purgado).
    """
    upload_base = _upload_base(db)
    info = midia_storage.salvar_bytes(upload_base, sessao_id, conteudo, mime)

    if ttl_dias is None:
        ttl_dias = int(ConfiguracaoService.obter_valor(db, "sistema_midia_ttl_dias", 120))

    ttl_em = None
    if ttl_dias and ttl_dias > 0:
        ttl_em = datetime.now(tz=timezone.utc) + timedelta(days=ttl_dias)

    media_id = midia_storage.gerar_media_id(sessao_id, chat_id, origem)

    midia = Midia(
        sessao_id=sessao_id,
        chat_id=chat_id,
        media_id=media_id,
        path=info["path"],
        mime=info["mime"],
        tamanho_bytes=info["tamanho"],
        origem=_mapear_origem(origem),
        vinculada_tipo=_mapear_vinculada(vinculada_tipo),
        vinculada_id=vinculada_id,
        ttl_em=ttl_em,
    )
    db.add(midia)
    db.flush()
    logger.info(
        "midia.registrar media_id=%s sessao_id=%s origem=%s tamanho=%d mime=%s",
        media_id, sessao_id, origem, info["tamanho"], info["mime"],
    )
    return midia


def buscar_por_media_id(
    db: Session, media_id: str, sessao_id: Optional[int] = None
) -> Optional[Midia]:
    """Retorna `Midia` ou None.

    Se `sessao_id` for passado, filtra (ownership). Sem sessao_id, retorna global
    — use so em contextos administrativos.
    """
    q = db.query(Midia).filter(Midia.media_id == media_id)
    if sessao_id is not None:
        q = q.filter(Midia.sessao_id == sessao_id)
    return q.first()


def vincular(
    db: Session,
    media_id: str,
    vinculada_tipo: str,
    vinculada_id: int,
) -> bool:
    """Liga midia a um recurso (mensagem, sessao, etc). False se nao achou."""
    midia = db.query(Midia).filter(Midia.media_id == media_id).first()
    if midia is None:
        return False
    midia.vinculada_tipo = _mapear_vinculada(vinculada_tipo)
    midia.vinculada_id = vinculada_id
    db.flush()
    return True


def marcar_para_delete(db: Session, media_id: str) -> bool:
    """Deleta arquivo do disco E registro do banco. True se deletou."""
    midia = db.query(Midia).filter(Midia.media_id == media_id).first()
    if midia is None:
        return False
    midia_storage.deletar_arquivo(midia.path)
    db.delete(midia)
    db.flush()
    logger.info("midia.deletar media_id=%s", media_id)
    return True


def purgar_expiradas(db: Session, grace_dias: Optional[int] = None) -> int:
    """Remove midias com `ttl_em < now` E nao referenciadas em Mensagem recente.

    `grace_dias`: se houver Mensagem criada nesse periodo apontando pro `path` da
    midia (via `conteudo_imagem_path`), pula a purga. Default = config
    `sistema_midia_grace_dias` (7).
    """
    from mensagem.mensagem_model import Mensagem  # lazy: evita ciclo

    if grace_dias is None:
        grace_dias = int(ConfiguracaoService.obter_valor(db, "sistema_midia_grace_dias", 7))

    agora = datetime.now(tz=timezone.utc)
    corte_grace = agora - timedelta(days=grace_dias) if grace_dias > 0 else None

    expiradas = (
        db.query(Midia)
        .filter(Midia.ttl_em.isnot(None))
        .filter(Midia.ttl_em < agora)
        .all()
    )

    count = 0
    for midia in expiradas:
        # Grace check: msg recente apontando pra esse arquivo?
        if corte_grace is not None:
            ref = (
                db.query(Mensagem)
                .filter(Mensagem.conteudo_imagem_path == midia.path)
                .filter(Mensagem.criado_em >= corte_grace)
                .first()
            )
            if ref is not None:
                logger.debug(
                    "midia.purgar.skip media_id=%s motivo=referenciada_recente msg_id=%s",
                    midia.media_id, ref.id,
                )
                continue
        midia_storage.deletar_arquivo(midia.path)
        db.delete(midia)
        count += 1

    if count:
        db.flush()
        logger.info("midia.purgar.total deletadas=%d", count)
    return count
