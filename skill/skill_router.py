"""
Rotas da API para skills.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from skill.skill_schema import SkillResposta, SkillCriar, SkillAtualizar, AgenteSkillsAtualizar
from skill.skill_service import SkillService

router = APIRouter(prefix="/api/skills", tags=["Skills"])


@router.get("/", response_model=List[SkillResposta])
def listar_skills(db: Session = Depends(get_db)):
    """Lista todas as skills."""
    return SkillService.listar_todas(db)


@router.get("/ativas", response_model=List[SkillResposta])
def listar_skills_ativas(db: Session = Depends(get_db)):
    """Lista skills ativas."""
    return SkillService.listar_ativas(db)


@router.get("/agente/{agente_id}", response_model=List[SkillResposta])
def listar_skills_agente(agente_id: int, db: Session = Depends(get_db)):
    """Lista skills ativas de um agente, ordenadas por posição."""
    return SkillService.listar_skills_agente(db, agente_id)


@router.post("/agente/{agente_id}")
def atualizar_skills_agente(
    agente_id: int,
    payload: AgenteSkillsAtualizar,
    db: Session = Depends(get_db)
):
    """Substitui completamente as skills de um agente."""
    try:
        SkillService.atualizar_skills_agente(db, agente_id, payload.skills)
        return {"mensagem": "Skills do agente atualizadas com sucesso"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{skill_id}", response_model=SkillResposta)
def obter_skill(skill_id: int, db: Session = Depends(get_db)):
    """Obtém uma skill específica."""
    skill = SkillService.obter_por_id(db, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill não encontrada")
    return skill


@router.post("/", response_model=SkillResposta)
def criar_skill(skill: SkillCriar, db: Session = Depends(get_db)):
    """Cria uma nova skill."""
    try:
        return SkillService.criar(db, skill)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{skill_id}", response_model=SkillResposta)
def atualizar_skill(skill_id: int, skill: SkillAtualizar, db: Session = Depends(get_db)):
    """Atualiza uma skill existente."""
    skill_atualizada = SkillService.atualizar(db, skill_id, skill)
    if not skill_atualizada:
        raise HTTPException(status_code=404, detail="Skill não encontrada")
    return skill_atualizada


@router.delete("/{skill_id}")
def deletar_skill(skill_id: int, db: Session = Depends(get_db)):
    """Deleta uma skill."""
    sucesso = SkillService.deletar(db, skill_id)
    if not sucesso:
        raise HTTPException(status_code=404, detail="Skill não encontrada")
    return {"mensagem": "Skill deletada com sucesso"}
