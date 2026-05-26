"""
Serviço RAG customizado - Implementação própria sem dependências externas pesadas.
Permite adicionar texto direto, criar chunks, gerar embeddings e fazer busca semântica.
Suporta OpenAI e OpenRouter como provedores de embeddings.
"""
import os
import json
import logging
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
import re
import httpx

# Dependências leves
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

logger = logging.getLogger(__name__)


class RAGCustomService:
    """Serviço RAG customizado com implementação própria."""

    def __init__(self, rag_id: int, storage_path: str, api_key: str = None,
                 modelo_embed: str = "text-embedding-3-small",
                 score_threshold: float = None,
                 provider: str = "openai"):
        self.rag_id = rag_id
        self.storage_path = storage_path
        self.api_key = api_key
        self.modelo_embed = modelo_embed
        self.score_threshold = score_threshold
        self.provider = provider
        self.client = None
        self.collection = None

        # Criar diretório se não existir
        os.makedirs(storage_path, exist_ok=True)

        # Inicializar ChromaDB
        self._init_chromadb()
    
    def _init_chromadb(self):
        """Inicializa ChromaDB."""
        if not CHROMADB_AVAILABLE:
            raise ValueError("ChromaDB não está instalado. Execute: pip install chromadb")
        
        try:
            self.client = chromadb.PersistentClient(
                path=self.storage_path,
                settings=Settings(anonymized_telemetry=False)
            )
            
            # Criar ou obter coleção (hnsw:space=cosine para similaridade correta)
            collection_name = f"rag_{self.rag_id}"
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"rag_id": self.rag_id, "hnsw:space": "cosine"}
            )
            
            logger.info(f"ChromaDB inicializado para RAG {self.rag_id}")
            
        except Exception as e:
            logger.error(f"Erro ao inicializar ChromaDB: {str(e)}")
            raise ValueError(f"Erro ao inicializar ChromaDB: {str(e)}")
    
    def _generate_embedding(self, text: str) -> List[float]:
        """Gera embedding para um texto usando o provider configurado."""
        if self.provider == "openrouter":
            return self._generate_embedding_openrouter(text)
        else:
            return self._generate_embedding_openai(text)

    def _generate_embedding_openai(self, text: str) -> List[float]:
        """Gera embedding via OpenAI."""
        if not OPENAI_AVAILABLE:
            raise ValueError("OpenAI não está instalado. Execute: pip install openai")

        if not self.api_key:
            raise ValueError("API key do OpenAI não fornecida")

        try:
            client = openai.OpenAI(api_key=self.api_key)
            response = client.embeddings.create(
                model=self.modelo_embed,
                input=text
            )
            return response.data[0].embedding

        except Exception as e:
            logger.error(f"Erro ao gerar embedding (OpenAI): {str(e)}")
            raise ValueError(f"Erro ao gerar embedding: {str(e)}")

    def _generate_embedding_openrouter(self, text: str) -> List[float]:
        """Gera embedding via OpenRouter (/api/v1/embeddings)."""
        if not self.api_key:
            raise ValueError("API key do OpenRouter não fornecida")

        import requests

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://fluxi.ai",
                    "X-Title": "Fluxi WhatsApp AI Agent"
                },
                json={
                    "model": self.modelo_embed,
                    "input": text
                },
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()

            # Formato de resposta: {"data": [{"embedding": [...], "index": 0}]}
            embeddings = data.get("data", [])
            if not embeddings:
                raise ValueError("Resposta do OpenRouter não contém embeddings")

            return embeddings[0]["embedding"]

        except Exception as e:
            logger.error(f"Erro ao gerar embedding (OpenRouter): {str(e)}")
            raise ValueError(f"Erro ao gerar embedding: {str(e)}")
    
    def _create_chunks(self, text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[Dict[str, Any]]:
        """Cria chunks do texto."""
        logger.info(f"Criando chunks: tamanho={chunk_size}, overlap={chunk_overlap}")
        
        # Limpar texto
        text = re.sub(r'\s+', ' ', text.strip())
        
        chunks = []
        start = 0
        chunk_id = 0
        
        while start < len(text):
            end = start + chunk_size
            
            # Tentar quebrar em palavra completa
            if end < len(text):
                # Procurar último espaço antes do limite
                last_space = text.rfind(' ', start, end)
                if last_space > start:
                    end = last_space
            
            chunk_text = text[start:end].strip()
            
            if chunk_text:
                uid = hashlib.md5(f"{self.rag_id}_{start}_{end}_{chunk_text[:40]}".encode()).hexdigest()[:16]
                chunk = {
                    "id": uid,
                    "text": chunk_text,
                    "start": start,
                    "end": end,
                    "length": len(chunk_text),
                    "created_at": datetime.now().isoformat()
                }
                chunks.append(chunk)
                chunk_id += 1
            
            # Mover para próximo chunk com overlap
            start = end - chunk_overlap if end < len(text) else end
        
        logger.info(f"Criados {len(chunks)} chunks")
        return chunks
    
    def add_text(self, text: str, titulo: str = "", chunk_size: int = 1000, chunk_overlap: int = 200) -> Dict[str, Any]:
        """Adiciona texto à base de conhecimento."""
        logger.info(f"Adicionando texto ao RAG {self.rag_id}")
        
        try:
            # Criar chunks
            chunks = self._create_chunks(text, chunk_size, chunk_overlap)
            
            # Gerar embeddings e adicionar ao ChromaDB
            documents = []
            embeddings = []
            metadatas = []
            ids = []
            
            for chunk in chunks:
                # Gerar embedding
                embedding = self._generate_embedding(chunk["text"])
                
                # Preparar dados para ChromaDB
                documents.append(chunk["text"])
                embeddings.append(embedding)
                metadatas.append({
                    "chunk_id": chunk["id"],
                    "titulo": titulo,
                    "start": chunk["start"],
                    "end": chunk["end"],
                    "length": chunk["length"],
                    "created_at": chunk["created_at"]
                })
                ids.append(chunk["id"])
            
            # Adicionar ao ChromaDB
            self.collection.add(
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
                ids=ids
            )
            
            logger.info(f"Texto adicionado com sucesso: {len(chunks)} chunks")
            
            return {
                "success": True,
                "chunks_created": len(chunks),
                "total_chunks": self.collection.count(),
                "chunks": chunks
            }
            
        except Exception as e:
            logger.error(f"Erro ao adicionar texto: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Realiza busca semântica."""
        logger.info(f"Buscando: '{query}' (top_k={top_k})")
        
        try:
            # Gerar embedding da query
            query_embedding = self._generate_embedding(query)
            
            # Buscar no ChromaDB
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"]
            )
            
            # Formatar resultados
            formatted_results = []
            for i, (doc, metadata, distance) in enumerate(zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0]
            )):
                # Com hnsw:space=cosine: distance = 1 - cosine_similarity → similarity = 1 - distance
                score = 1.0 - float(distance)
                
                # Aplicar score_threshold se configurado
                if self.score_threshold is not None and score < self.score_threshold:
                    continue
                
                result = {
                    "context": doc,
                    "metadata": {
                        "chunk_id": metadata["chunk_id"],
                        "titulo": metadata.get("titulo", ""),
                        "start": metadata["start"],
                        "end": metadata["end"],
                        "length": metadata["length"],
                        "created_at": metadata["created_at"],
                        "score": score
                    },
                    "score": score
                }
                formatted_results.append(result)
            
            logger.info(f"Busca retornou {len(formatted_results)} resultados")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Erro na busca: {str(e)}", exc_info=True)
            return []
    
    def get_chunks(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Obtém chunks armazenados."""
        logger.info(f"Obtendo chunks: limit={limit}, offset={offset}")
        
        try:
            # Buscar todos os documentos
            results = self.collection.get(
                limit=limit,
                offset=offset,
                include=["documents", "metadatas"]
            )
            
            chunks = []
            for doc, metadata in zip(results["documents"], results["metadatas"]):
                chunk = {
                    "id": metadata["chunk_id"],
                    "titulo": metadata.get("titulo", ""),
                    "text": doc,
                    "start": metadata["start"],
                    "end": metadata["end"],
                    "length": metadata["length"],
                    "created_at": metadata["created_at"]
                }
                chunks.append(chunk)
            
            logger.info(f"Retornados {len(chunks)} chunks")
            return chunks
            
        except Exception as e:
            logger.error(f"Erro ao obter chunks: {str(e)}", exc_info=True)
            return []
    
    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Obtém um chunk específico por ID (O(1))."""
        try:
            result = self.collection.get(
                ids=[chunk_id],
                include=["documents", "metadatas"]
            )
            if not result["ids"]:
                return None
            doc = result["documents"][0]
            metadata = result["metadatas"][0]
            return {
                "id": metadata["chunk_id"],
                "titulo": metadata.get("titulo", ""),
                "text": doc,
                "start": metadata["start"],
                "end": metadata["end"],
                "length": metadata["length"],
                "created_at": metadata["created_at"]
            }
        except Exception as e:
            logger.error(f"Erro ao obter chunk {chunk_id}: {str(e)}")
            return None

    def delete_chunk(self, chunk_id: str) -> bool:
        """Deleta um chunk específico."""
        logger.info(f"Deletando chunk: {chunk_id}")
        
        try:
            self.collection.delete(ids=[chunk_id])
            logger.info(f"Chunk {chunk_id} deletado com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao deletar chunk: {str(e)}", exc_info=True)
            return False
    
    def reset(self) -> bool:
        """Reseta a base de conhecimento."""
        logger.info(f"Resetando RAG {self.rag_id}")
        
        try:
            # Deletar coleção
            self.client.delete_collection(self.collection.name)
            
            # Recriar coleção (mantendo cosine distance)
            collection_name = f"rag_{self.rag_id}"
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"rag_id": self.rag_id, "hnsw:space": "cosine"}
            )
            
            logger.info("RAG resetado com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao resetar RAG: {str(e)}", exc_info=True)
            return False
    
    def add_file(self, file_path: str, titulo: str = "", chunk_size: int = 1000, chunk_overlap: int = 200) -> Dict[str, Any]:
        """Converte um arquivo via MarkItDown e adiciona à base de conhecimento."""
        logger.info(f"Processando arquivo '{file_path}' via MarkItDown para RAG {self.rag_id}")
        
        try:
            from markitdown import MarkItDown
        except ImportError:
            return {"success": False, "error": "MarkItDown não instalado. Execute: pip install 'markitdown[pdf,docx,pptx,xlsx]'"}
        
        try:
            md = MarkItDown(enable_plugins=False)
            result = md.convert(file_path)
            text = result.text_content
            
            if not text or not text.strip():
                return {"success": False, "error": "Arquivo não contém texto extraível"}
            
            logger.info(f"MarkItDown extraiu {len(text)} caracteres de '{file_path}'")
            return self.add_text(text=text, titulo=titulo, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            
        except Exception as e:
            logger.error(f"Erro ao processar arquivo com MarkItDown: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Erro ao processar arquivo: {str(e)}"}

    def get_stats(self) -> Dict[str, Any]:
        """Obtém estatísticas da base de conhecimento."""
        try:
            total_chunks = self.collection.count()
            
            return {
                "total_chunks": total_chunks,
                "rag_id": self.rag_id,
                "storage_path": self.storage_path,
                "collection_name": self.collection.name
            }
            
        except Exception as e:
            logger.error(f"Erro ao obter estatísticas: {str(e)}", exc_info=True)
            return {
                "total_chunks": 0,
                "rag_id": self.rag_id,
                "storage_path": self.storage_path,
                "error": str(e)
            }
