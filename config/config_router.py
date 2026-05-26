"""
Rotas da API para configurações.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from config.config_schema import (
    ConfiguracaoResposta,
    ConfiguracaoCriar,
    ConfiguracaoAtualizar,
    TestarConexaoResposta
)
from config.config_service import ConfiguracaoService

router = APIRouter(prefix="/api/configuracoes", tags=["Configurações"])


@router.get("/", response_model=List[ConfiguracaoResposta])
def listar_configuracoes(db: Session = Depends(get_db)):
    """Lista todas as configurações."""
    return ConfiguracaoService.listar_todas(db)


@router.get("/categoria/{categoria}", response_model=List[ConfiguracaoResposta])
def listar_por_categoria(categoria: str, db: Session = Depends(get_db)):
    """Lista configurações por categoria."""
    return ConfiguracaoService.listar_por_categoria(db, categoria)


@router.get("/{chave}", response_model=ConfiguracaoResposta)
def obter_configuracao(chave: str, db: Session = Depends(get_db)):
    """Obtém uma configuração específica."""
    config = ConfiguracaoService.obter_por_chave(db, chave)
    if not config:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")
    return config


@router.post("/", response_model=ConfiguracaoResposta)
def criar_configuracao(config: ConfiguracaoCriar, db: Session = Depends(get_db)):
    """Cria uma nova configuração."""
    # Verificar se já existe
    existe = ConfiguracaoService.obter_por_chave(db, config.chave)
    if existe:
        raise HTTPException(status_code=400, detail="Configuração já existe")
    
    return ConfiguracaoService.criar(db, config)


@router.put("/{chave}", response_model=ConfiguracaoResposta)
def atualizar_configuracao(
    chave: str,
    config: ConfiguracaoAtualizar,
    db: Session = Depends(get_db)
):
    """Atualiza uma configuração existente."""
    try:
        config_atualizada = ConfiguracaoService.atualizar(db, chave, config)
        if not config_atualizada:
            raise HTTPException(status_code=404, detail="Configuração não encontrada")
        return config_atualizada
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{chave}")
def deletar_configuracao(chave: str, db: Session = Depends(get_db)):
    """Deleta uma configuração."""
    try:
        sucesso = ConfiguracaoService.deletar(db, chave)
        if not sucesso:
            raise HTTPException(status_code=404, detail="Configuração não encontrada")
        return {"mensagem": "Configuração deletada com sucesso"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/openrouter/testar", response_model=TestarConexaoResposta)
async def testar_conexao_openrouter(api_key: str = None, db: Session = Depends(get_db)):
    """Testa conexão com OpenRouter e busca modelos disponíveis."""
    return await ConfiguracaoService.testar_conexao_openrouter(db, api_key)


@router.get("/openrouter/modelos-audio")
async def listar_modelos_audio_openrouter():
    """Lista modelos do OpenRouter que suportam áudio."""
    from audio.transcription_service import TranscriptionService
    modelos = await TranscriptionService.listar_modelos_openrouter_audio()
    return modelos
