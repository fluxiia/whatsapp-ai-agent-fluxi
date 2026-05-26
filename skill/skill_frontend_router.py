"""
Router frontend para skills.
Rotas para páginas HTML de gerenciamento de skills.
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from skill.skill_service import SkillService
from skill.skill_schema import SkillCriar, SkillAtualizar
from agente.agente_service import AgenteService

router = APIRouter(tags=["Skills Frontend"])
templates = Jinja2Templates(directory="templates")


@router.get("/skills", response_class=HTMLResponse)
def listar_skills_page(request: Request, db: Session = Depends(get_db)):
    """Página de listagem de skills."""
    skills = SkillService.listar_todas(db)
    return templates.TemplateResponse("skill/lista.html", {
        "request": request,
        "skills": skills,
        "titulo": "Skills"
    })


@router.get("/skills/novo", response_class=HTMLResponse)
def nova_skill_page(request: Request, db: Session = Depends(get_db)):
    """Página de criação de skill."""
    from ferramenta.ferramenta_service import FerramentaService
    todas_ferramentas = FerramentaService.listar_ferramentas_ativas(db)
    skills_pai = [s for s in SkillService.listar_ativas(db) if '-' not in s.nome]
    return templates.TemplateResponse("skill/form.html", {
        "request": request,
        "skill": None,
        "acao": "criar",
        "titulo": "Nova Skill",
        "todas_ferramentas": todas_ferramentas,
        "skills_pai": skills_pai,
        "ferramentas_selecionadas": []
    })


@router.get("/skills/{skill_id}", response_class=HTMLResponse)
def detalhes_skill_page(request: Request, skill_id: int, db: Session = Depends(get_db)):
    """Página de detalhes de uma skill."""
    import json
    from ferramenta.ferramenta_service import FerramentaService
    skill = SkillService.obter_por_id(db, skill_id)
    if not skill:
        return RedirectResponse(url="/skills?erro=Skill não encontrada", status_code=303)
    ferramentas_injetadas = []
    if skill.ferramentas_ids:
        try:
            ids = json.loads(skill.ferramentas_ids)
            for fid in ids:
                f = FerramentaService.obter_por_id(db, fid)
                if f:
                    ferramentas_injetadas.append(f)
        except Exception:
            pass
    return templates.TemplateResponse("skill/detalhes.html", {
        "request": request,
        "skill": skill,
        "ferramentas_injetadas": ferramentas_injetadas,
        "titulo": f"Skill: {skill.nome}"
    })


@router.get("/skills/{skill_id}/editar", response_class=HTMLResponse)
def editar_skill_page(request: Request, skill_id: int, db: Session = Depends(get_db)):
    """Página de edição de skill."""
    skill = SkillService.obter_por_id(db, skill_id)
    if not skill:
        return RedirectResponse(url="/skills?erro=Skill não encontrada", status_code=303)
    from ferramenta.ferramenta_service import FerramentaService
    import json
    todas_ferramentas = FerramentaService.listar_ferramentas_ativas(db)
    ferramentas_selecionadas = []
    if skill.ferramentas_ids:
        try:
            ferramentas_selecionadas = json.loads(skill.ferramentas_ids)
        except Exception:
            ferramentas_selecionadas = []
    skills_pai = [s for s in SkillService.listar_ativas(db) if '-' not in s.nome and s.id != skill.id]
    return templates.TemplateResponse("skill/form.html", {
        "request": request,
        "skill": skill,
        "acao": "editar",
        "titulo": f"Editar Skill: {skill.nome}",
        "todas_ferramentas": todas_ferramentas,
        "ferramentas_selecionadas": ferramentas_selecionadas,
        "skills_pai": skills_pai
    })


@router.post("/skills/criar")
def criar_skill_form(
    request: Request,
    nome: str = Form(...),
    descricao: str = Form(...),
    instrucao_completa: str = Form(...),
    script_codigo: Optional[str] = Form(None),
    script_parametros: Optional[str] = Form(None),
    ferramentas_ids: Optional[str] = Form(None),
    categoria: str = Form("utilitário"),
    icone: Optional[str] = Form("🔧"),
    versao: str = Form("1.0"),
    ativa: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Processa criação de skill."""
    try:
        skill_data = SkillCriar(
            nome=nome.strip(),
            descricao=descricao.strip(),
            instrucao_completa=instrucao_completa.strip(),
            script_codigo=script_codigo.strip() if script_codigo and script_codigo.strip() else None,
            script_parametros=script_parametros.strip() if script_parametros and script_parametros.strip() else None,
            ferramentas_ids=ferramentas_ids.strip() if ferramentas_ids and ferramentas_ids.strip() else None,
            categoria=categoria,
            icone=icone or "🔧",
            versao=versao or "1.0",
            ativa=ativa == "on" or ativa == "true" or ativa == "1"
        )
        skill = SkillService.criar(db, skill_data)
        return RedirectResponse(url=f"/skills/{skill.id}?sucesso=Skill criada com sucesso", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/skills/novo?erro={str(e)}", status_code=303)


@router.post("/skills/{skill_id}/atualizar")
def atualizar_skill_form(
    request: Request,
    skill_id: int,
    nome: str = Form(...),
    descricao: str = Form(...),
    instrucao_completa: str = Form(...),
    script_codigo: Optional[str] = Form(None),
    script_parametros: Optional[str] = Form(None),
    ferramentas_ids: Optional[str] = Form(None),
    categoria: str = Form("utilitário"),
    icone: Optional[str] = Form("🔧"),
    versao: str = Form("1.0"),
    ativa: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Processa atualização de skill."""
    try:
        skill_data = SkillAtualizar(
            nome=nome.strip(),
            descricao=descricao.strip(),
            instrucao_completa=instrucao_completa.strip(),
            script_codigo=script_codigo.strip() if script_codigo and script_codigo.strip() else None,
            script_parametros=script_parametros.strip() if script_parametros and script_parametros.strip() else None,
            ferramentas_ids=ferramentas_ids.strip() if ferramentas_ids and ferramentas_ids.strip() else None,
            categoria=categoria,
            icone=icone or "🔧",
            versao=versao or "1.0",
            ativa=ativa == "on" or ativa == "true" or ativa == "1"
        )
        SkillService.atualizar(db, skill_id, skill_data)
        return RedirectResponse(url=f"/skills/{skill_id}?sucesso=Skill atualizada com sucesso", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/skills/{skill_id}/editar?erro={str(e)}", status_code=303)


@router.post("/skills/{skill_id}/deletar")
def deletar_skill_form(skill_id: int, db: Session = Depends(get_db)):
    """Processa deleção de skill."""
    SkillService.deletar(db, skill_id)
    return RedirectResponse(url="/skills?sucesso=Skill removida", status_code=303)




@router.post("/agentes/{agente_id}/skills/atualizar")
def atualizar_skills_agente_form(
    agente_id: int,
    request: Request,
    skill_ids: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Processa atualização de skills do agente."""
    try:
        ids = []
        if skill_ids:
            ids = [int(i.strip()) for i in skill_ids.split(",") if i.strip().isdigit()]
        SkillService.atualizar_skills_agente(db, agente_id, ids)
        return RedirectResponse(url=f"/agentes/{agente_id}?tab=skills", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/agentes/{agente_id}?tab=skills", status_code=303)
