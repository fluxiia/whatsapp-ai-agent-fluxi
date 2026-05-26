"""
Rotas da API para RAG.
"""
from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import os
import tempfile
import shutil
from pathlib import Path
from database import get_db
from rag.rag_schema import (
    RAGResposta,
    RAGCriar,
    RAGAtualizar,
    RAGBuscaRequest,
    RAGTextoRequest
)
from rag.rag_service import RAGService

# Configurar logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rags", tags=["RAG"])


@router.get("/", response_model=List[RAGResposta])
def listar_rags(
    apenas_ativos: bool = False,
    db: Session = Depends(get_db)
):
    """Lista todos os RAGs."""
    if apenas_ativos:
        return RAGService.listar_ativos(db)
    return RAGService.listar_todos(db)


@router.get("/{rag_id}", response_model=RAGResposta)
def obter_rag(rag_id: int, db: Session = Depends(get_db)):
    """Obtém um RAG específico."""
    rag = RAGService.obter_por_id(db, rag_id)
    if not rag:
        raise HTTPException(status_code=404, detail="RAG não encontrado")
    return rag


@router.post("/", response_model=RAGResposta)
def criar_rag(rag: RAGCriar, db: Session = Depends(get_db)):
    """Cria um novo RAG."""
    try:
        return RAGService.criar(db, rag)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{rag_id}", response_model=RAGResposta)
def atualizar_rag(
    rag_id: int,
    rag: RAGAtualizar,
    db: Session = Depends(get_db)
):
    """Atualiza um RAG existente."""
    try:
        rag_atualizado = RAGService.atualizar(db, rag_id, rag)
        if not rag_atualizado:
            raise HTTPException(status_code=404, detail="RAG não encontrado")
        return rag_atualizado
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{rag_id}")
def deletar_rag(rag_id: int, db: Session = Depends(get_db)):
    """Deleta um RAG."""
    sucesso = RAGService.deletar(db, rag_id)
    if not sucesso:
        raise HTTPException(status_code=404, detail="RAG não encontrado")
    return {"mensagem": "RAG deletado com sucesso"}


@router.post("/{rag_id}/adicionar-texto")
def adicionar_texto(
    rag_id: int,
    titulo: str = Form(...),
    texto: str = Form(...),
    chunk_size: int = Form(None),
    chunk_overlap: int = Form(None),
    db: Session = Depends(get_db)
):
    """Adiciona texto direto ao RAG."""
    logger.info(f"API: Adicionando texto '{titulo}' ao RAG {rag_id}")
    
    try:
        resultado = RAGService.adicionar_texto(
            db, rag_id, titulo, texto, chunk_size, chunk_overlap
        )
        
        if resultado["sucesso"]:
            return {
                "mensagem": "Texto adicionado com sucesso",
                "chunks_criados": resultado["chunks_criados"],
                "total_chunks": resultado["total_chunks"]
            }
        else:
            raise HTTPException(status_code=500, detail=resultado["erro"])
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"API: Erro ao adicionar texto: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao adicionar texto: {str(e)}")


@router.post("/{rag_id}/buscar")
def buscar(
    rag_id: int,
    busca: RAGBuscaRequest,
    db: Session = Depends(get_db)
):
    """Realiza busca semântica no RAG."""
    try:
        resultados = RAGService.buscar(
            db,
            rag_id,
            busca.query,
            busca.top_k,
            busca.session_id
        )
        return {
            "query": busca.query,
            "total_resultados": len(resultados),
            "resultados": resultados
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{rag_id}/chunks")
def listar_chunks(rag_id: int, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    """Lista chunks do RAG."""
    try:
        chunks = RAGService.obter_chunks(db, rag_id, limit, offset)
        return {"chunks": chunks}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"API: Erro ao listar chunks: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao listar chunks: {str(e)}")


@router.get("/{rag_id}/chunks/{chunk_id}")
def obter_chunk(rag_id: int, chunk_id: str, db: Session = Depends(get_db)):
    """Obtém um chunk específico."""
    try:
        chunk = RAGService.obter_chunk_por_id(db, rag_id, chunk_id)
        if not chunk:
            raise HTTPException(status_code=404, detail="Chunk não encontrado")
        return chunk
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"API: Erro ao obter chunk: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao obter chunk: {str(e)}")


@router.delete("/{rag_id}/chunks/{chunk_id}")
def deletar_chunk(rag_id: int, chunk_id: str, db: Session = Depends(get_db)):
    """Deleta um chunk específico."""
    try:
        sucesso = RAGService.deletar_chunk(db, rag_id, chunk_id)
        
        if sucesso:
            return {"success": True, "mensagem": "Chunk deletado com sucesso"}
        else:
            raise HTTPException(status_code=500, detail="Erro ao deletar chunk")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"API: Erro ao deletar chunk: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao deletar chunk: {str(e)}")


@router.post("/{rag_id}/adicionar-arquivo")
async def adicionar_arquivo(
    rag_id: int,
    titulo: str = Form(...),
    arquivo: UploadFile = File(...),
    chunk_size: int = Form(None),
    chunk_overlap: int = Form(None),
    db: Session = Depends(get_db)
):
    """Converte um arquivo (PDF, DOCX, PPTX, XLSX...) via MarkItDown e adiciona ao RAG."""
    logger.info(f"API: Upload de arquivo '{arquivo.filename}' para RAG {rag_id}")
    
    suffix = Path(arquivo.filename).suffix if arquivo.filename else ".tmp"
    tmp_path = None
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(arquivo.file, tmp)
            tmp_path = tmp.name
        
        resultado = RAGService.adicionar_arquivo(
            db, rag_id, titulo, tmp_path, chunk_size, chunk_overlap
        )
        
        if resultado["sucesso"]:
            return {
                "mensagem": "Arquivo processado e adicionado com sucesso",
                "chunks_criados": resultado["chunks_criados"],
                "total_chunks": resultado["total_chunks"]
            }
        else:
            raise HTTPException(status_code=500, detail=resultado["erro"])
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"API: Erro ao processar arquivo: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao processar arquivo: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.post("/{rag_id}/resetar")
def resetar_rag(rag_id: int, db: Session = Depends(get_db)):
    """Reseta o RAG, removendo todos os embeddings."""
    sucesso = RAGService.resetar_rag(db, rag_id)
    if not sucesso:
        raise HTTPException(status_code=500, detail="Erro ao resetar RAG")
    return {"mensagem": "RAG resetado com sucesso"}


@router.get("/{rag_id}/estatisticas")
def obter_estatisticas(rag_id: int, db: Session = Depends(get_db)):
    """Obtém estatísticas do RAG."""
    try:
        stats = RAGService.obter_estatisticas(db, rag_id)
        return stats
    except Exception as e:
        logger.error(f"API: Erro ao obter estatísticas: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao obter estatísticas: {str(e)}")