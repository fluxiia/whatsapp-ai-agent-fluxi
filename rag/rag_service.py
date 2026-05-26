"""
Serviço de lógica de negócio para RAG customizado.
"""
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
import os
import logging
from datetime import datetime

from rag.rag_model import RAG
from rag.rag_schema import RAGCriar, RAGAtualizar
from config.rag_config import RAGConfig

# Configurar logger
logger = logging.getLogger(__name__)


class RAGService:
    """Serviço para gerenciar RAG customizado."""

    @staticmethod
    def listar_todos(db: Session) -> List[RAG]:
        """Lista todos os RAGs."""
        return db.query(RAG).all()

    @staticmethod
    def listar_ativos(db: Session) -> List[RAG]:
        """Lista RAGs ativos."""
        return db.query(RAG).filter(RAG.ativo == True).all()

    @staticmethod
    def obter_por_id(db: Session, rag_id: int) -> Optional[RAG]:
        """Obtém um RAG pelo ID."""
        return db.query(RAG).filter(RAG.id == rag_id).first()

    @staticmethod
    def obter_por_nome(db: Session, nome: str) -> Optional[RAG]:
        """Obtém um RAG pelo nome."""
        return db.query(RAG).filter(RAG.nome == nome).first()

    @staticmethod
    def criar(db: Session, rag: RAGCriar) -> RAG:
        """Cria um novo RAG."""
        # Verificar se já existe RAG com mesmo nome
        existe = RAGService.obter_por_nome(db, rag.nome)
        if existe:
            raise ValueError(f"Já existe um RAG com o nome '{rag.nome}'")
        
        # Criar diretório de storage
        storage_path = f"rags/{rag.nome.replace(' ', '_').lower()}"
        os.makedirs(storage_path, exist_ok=True)
        
        # Criar RAG
        db_rag = RAG(
            nome=rag.nome,
            descricao=rag.descricao,
            provider=rag.provider,
            modelo_embed=rag.modelo_embed,
            chunk_size=rag.chunk_size,
            chunk_overlap=rag.chunk_overlap,
            top_k=rag.top_k,
            score_threshold=rag.score_threshold,
            api_key_embed=rag.api_key_embed,
            ativo=rag.ativo,
            storage_path=storage_path
        )
        
        db.add(db_rag)
        db.commit()
        db.refresh(db_rag)
        return db_rag

    @staticmethod
    def atualizar(db: Session, rag_id: int, rag: RAGAtualizar) -> Optional[RAG]:
        """Atualiza um RAG existente."""
        db_rag = RAGService.obter_por_id(db, rag_id)
        if not db_rag:
            return None

        update_data = rag.model_dump(exclude_unset=True, exclude={'api_key_embed'})
        
        # Verificar se está mudando o nome e se já existe outro com esse nome
        if "nome" in update_data and update_data["nome"] != db_rag.nome:
            existe = RAGService.obter_por_nome(db, update_data["nome"])
            if existe:
                raise ValueError(f"Já existe um RAG com o nome '{update_data['nome']}'")
        
        for campo, valor in update_data.items():
            setattr(db_rag, campo, valor)
        
        # Atualizar API key se fornecida
        if rag.api_key_embed:
            db_rag.api_key_embed = rag.api_key_embed

        db.commit()
        db.refresh(db_rag)
        return db_rag

    @staticmethod
    def deletar(db: Session, rag_id: int) -> bool:
        """Deleta um RAG."""
        db_rag = RAGService.obter_por_id(db, rag_id)
        if not db_rag:
            return False

        db.delete(db_rag)
        db.commit()
        return True

    @staticmethod
    def inicializar_rag_service(rag: RAG, db: Session = None) -> Any:
        """
        Inicializa instância do RAG customizado.
        """
        logger.info(f"Inicializando RAG customizado para '{rag.nome}' (Provider: {rag.provider})")

        try:
            from rag.rag_custom_service import RAGCustomService
            logger.info("RAG customizado importado com sucesso")

            # Resolver API key
            api_key = rag.api_key_embed
            if not api_key and rag.provider == "openrouter" and db:
                # Fallback para a API key global do OpenRouter
                from config.config_service import ConfiguracaoService
                api_key = ConfiguracaoService.obter_valor(db, "openrouter_api_key")
                logger.info("Usando API key global do OpenRouter para RAG '%s'", rag.nome)

            if not api_key:
                raise ValueError("API key é obrigatória para o RAG customizado")

            # Criar instância do RAG customizado
            logger.info("Criando instância do RAG customizado...")
            rag_service = RAGCustomService(
                rag_id=rag.id,
                storage_path=rag.storage_path,
                api_key=api_key,
                modelo_embed=rag.modelo_embed,
                score_threshold=rag.score_threshold,
                provider=rag.provider
            )
            logger.info("RAG customizado criado com sucesso")
            return rag_service
            
        except ImportError as e:
            logger.error("Dependências do RAG customizado não estão instaladas")
            raise ValueError("Dependências não instaladas. Execute: pip install openai chromadb numpy")
        except Exception as e:
            logger.error(f"Erro ao inicializar RAG customizado: {str(e)}", exc_info=True)
            raise ValueError(f"Erro ao inicializar RAG customizado: {str(e)}")

    @staticmethod
    def adicionar_texto(
        db: Session,
        rag_id: int,
        titulo: str,
        texto: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None
    ) -> Dict[str, Any]:
        """Adiciona texto à base de conhecimento."""
        logger.info(f"Adicionando texto '{titulo}' ao RAG {rag_id}")
        
        rag = RAGService.obter_por_id(db, rag_id)
        if not rag:
            raise ValueError(f"RAG com ID {rag_id} não encontrado")
        
        try:
            # Inicializar RAG customizado
            rag_service = RAGService.inicializar_rag_service(rag, db)
            
            # Usar configurações do RAG se não especificadas
            chunk_size = chunk_size or rag.chunk_size
            chunk_overlap = chunk_overlap or rag.chunk_overlap
            
            # Adicionar texto
            result = rag_service.add_text(
                text=texto,
                titulo=titulo,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            
            if result["success"]:
                # Atualizar RAG
                rag.treinado = True
                rag.treinado_em = datetime.now()
                rag.total_chunks = result["total_chunks"]
                db.commit()
                
                logger.info(f"Texto adicionado com sucesso: {result['chunks_created']} chunks")
                return {
                    "sucesso": True,
                    "chunks_criados": result["chunks_created"],
                    "total_chunks": result["total_chunks"]
                }
            else:
                raise ValueError(f"Erro ao adicionar texto: {result.get('error', 'Erro desconhecido')}")
            
        except Exception as e:
            logger.error(f"Erro ao adicionar texto: {str(e)}", exc_info=True)
            return {
                "sucesso": False,
                "erro": str(e)
            }

    @staticmethod
    def adicionar_arquivo(
        db: Session,
        rag_id: int,
        titulo: str,
        file_path: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None
    ) -> Dict[str, Any]:
        """Converte um arquivo via MarkItDown e adiciona à base de conhecimento."""
        logger.info(f"Adicionando arquivo '{file_path}' ao RAG {rag_id}")
        
        rag = RAGService.obter_por_id(db, rag_id)
        if not rag:
            raise ValueError(f"RAG com ID {rag_id} não encontrado")
        
        try:
            rag_service = RAGService.inicializar_rag_service(rag, db)

            chunk_size = chunk_size or rag.chunk_size
            chunk_overlap = chunk_overlap or rag.chunk_overlap

            result = rag_service.add_file(
                file_path=file_path,
                titulo=titulo,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            
            if result["success"]:
                rag.treinado = True
                rag.treinado_em = datetime.now()
                rag.total_chunks = result["total_chunks"]
                db.commit()
                
                logger.info(f"Arquivo adicionado com sucesso: {result['chunks_created']} chunks")
                return {
                    "sucesso": True,
                    "chunks_criados": result["chunks_created"],
                    "total_chunks": result["total_chunks"]
                }
            else:
                raise ValueError(result.get("error", "Erro desconhecido"))
            
        except Exception as e:
            logger.error(f"Erro ao adicionar arquivo: {str(e)}", exc_info=True)
            return {"sucesso": False, "erro": str(e)}

    @staticmethod
    def buscar(
        db: Session,
        rag_id: int,
        query: str,
        top_k: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Realiza busca semântica no RAG customizado.
        """
        rag = RAGService.obter_por_id(db, rag_id)
        if not rag:
            raise ValueError(f"RAG {rag_id} não encontrado")
        
        if not rag.treinado:
            raise ValueError(f"RAG '{rag.nome}' ainda não foi treinado")
        
        try:
            # Inicializar RAG customizado
            rag_service = RAGService.inicializar_rag_service(rag, db)
            
            # Usar top_k configurado ou padrão do RAG
            num_results = top_k if top_k else rag.top_k
            
            # Realizar busca
            logger.info(f"Realizando busca: '{query}' (top_k={num_results})")
            resultados = rag_service.search(query, top_k=num_results)
            
            logger.info(f"Busca retornou {len(resultados)} resultados")
            return resultados
            
        except Exception as e:
            logger.error(f"Erro ao buscar no RAG: {str(e)}", exc_info=True)
            raise ValueError(f"Erro ao buscar no RAG: {str(e)}")

    @staticmethod
    def obter_chunks(db: Session, rag_id: int, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Obtém chunks do RAG."""
        rag = RAGService.obter_por_id(db, rag_id)
        if not rag:
            raise ValueError(f"RAG {rag_id} não encontrado")
        
        try:
            rag_service = RAGService.inicializar_rag_service(rag, db)
            return rag_service.get_chunks(limit=limit, offset=offset)
        except Exception as e:
            logger.error(f"Erro ao obter chunks: {str(e)}", exc_info=True)
            return []

    @staticmethod
    def obter_chunk_por_id(db: Session, rag_id: int, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Obtém um chunk específico por ID (O(1))."""
        rag = RAGService.obter_por_id(db, rag_id)
        if not rag:
            raise ValueError(f"RAG com ID {rag_id} não encontrado")
        
        try:
            rag_service = RAGService.inicializar_rag_service(rag, db)
            return rag_service.get_chunk_by_id(chunk_id)
        except Exception as e:
            logger.error(f"Erro ao obter chunk: {str(e)}", exc_info=True)
            return None

    @staticmethod
    def deletar_chunk(db: Session, rag_id: int, chunk_id: str) -> bool:
        """Deleta um chunk específico."""
        rag = RAGService.obter_por_id(db, rag_id)
        if not rag:
            raise ValueError(f"RAG com ID {rag_id} não encontrado")
        
        try:
            rag_service = RAGService.inicializar_rag_service(rag, db)
            sucesso = rag_service.delete_chunk(chunk_id)
            
            if sucesso:
                # Atualizar contador de chunks
                rag.total_chunks = max(0, rag.total_chunks - 1)
                db.commit()
            
            return sucesso
        except Exception as e:
            logger.error(f"Erro ao deletar chunk: {str(e)}", exc_info=True)
            return False

    @staticmethod
    def resetar_rag(db: Session, rag_id: int) -> bool:
        """Reseta o RAG, removendo todos os embeddings."""
        rag = RAGService.obter_por_id(db, rag_id)
        if not rag:
            return False
        
        try:
            # Resetar ChromaDB
            rag_service = RAGService.inicializar_rag_service(rag, db)
            rag_service.reset()
            
            # Atualizar RAG
            rag.treinado = False
            rag.treinado_em = None
            rag.total_chunks = 0
            
            db.commit()
            return True
            
        except Exception as e:
            logger.error(f"Erro ao resetar RAG: {str(e)}", exc_info=True)
            return False

    @staticmethod
    def obter_estatisticas(db: Session, rag_id: int) -> Dict[str, Any]:
        """Obtém estatísticas do RAG."""
        rag = RAGService.obter_por_id(db, rag_id)
        if not rag:
            return {}
        
        try:
            rag_service = RAGService.inicializar_rag_service(rag, db)
            stats = rag_service.get_stats()
            
            return {
                "rag": {
                    "nome": rag.nome,
                    "provider": rag.provider,
                    "modelo": rag.modelo_embed,
                    "treinado": rag.treinado,
                    "criado_em": rag.criado_em
                },
                "chunks": {
                    "total": stats.get("total_chunks", 0)
                }
            }
        except Exception as e:
            logger.error(f"Erro ao obter estatísticas: {str(e)}", exc_info=True)
            return {}