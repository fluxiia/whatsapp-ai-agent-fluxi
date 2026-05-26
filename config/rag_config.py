"""
Configurações específicas para RAG.
"""
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from config.config_service import ConfiguracaoService


class RAGConfig:
    """Configurações padrão e personalizadas para RAG."""
    
    # Configurações padrão
    DEFAULT_CONFIG = {
        # OpenAI
        "rag_openai_model": "text-embedding-3-small",
        "rag_openai_chunk_size": 1000,
        "rag_openai_chunk_overlap": 200,
        "rag_openai_top_k": 3,

        # OpenRouter
        "rag_openrouter_model": "openai/text-embedding-3-small",
        "rag_openrouter_chunk_size": 1000,
        "rag_openrouter_chunk_overlap": 200,
        "rag_openrouter_top_k": 3,

        # Cohere
        "rag_cohere_model": "embed-english-v3.0",
        "rag_cohere_chunk_size": 1000,
        "rag_cohere_chunk_overlap": 200,
        "rag_cohere_top_k": 3,

        # HuggingFace
        "rag_huggingface_model": "sentence-transformers/all-mpnet-base-v2",
        "rag_huggingface_chunk_size": 1000,
        "rag_huggingface_chunk_overlap": 200,
        "rag_huggingface_top_k": 3,

        # Google
        "rag_google_model": "models/embedding-001",
        "rag_google_chunk_size": 1000,
        "rag_google_chunk_overlap": 200,
        "rag_google_top_k": 3,

        # Configurações gerais
        "rag_default_provider": "openai",
        "rag_max_chunk_size": 5000,
        "rag_min_chunk_size": 100,
        "rag_max_chunk_overlap": 1000,
        "rag_max_top_k": 20,
        "rag_min_top_k": 1,
        "rag_score_threshold_default": 0.7,
    }
    
    @staticmethod
    def get_config(db: Session, provider: str = None) -> Dict[str, Any]:
        """Obtém configurações para um provider específico ou padrão."""
        config = {}
        
        # Se provider especificado, buscar configurações específicas
        if provider:
            prefix = f"rag_{provider}_"
            for key, default_value in RAGConfig.DEFAULT_CONFIG.items():
                if key.startswith(prefix):
                    config_key = key.replace(prefix, "")
                    config[config_key] = ConfiguracaoService.obter_valor(
                        db, key, default_value
                    )
        else:
            # Buscar configurações gerais
            for key, default_value in RAGConfig.DEFAULT_CONFIG.items():
                if not any(provider in key for provider in ["openai", "openrouter", "cohere", "huggingface", "google"]):
                    config_key = key.replace("rag_", "").replace("_default", "")
                    config[config_key] = ConfiguracaoService.obter_valor(
                        db, key, default_value
                    )
        
        return config
    
    @staticmethod
    def get_provider_config(db: Session, provider: str) -> Dict[str, Any]:
        """Obtém configurações específicas de um provider."""
        return RAGConfig.get_config(db, provider)
    
    @staticmethod
    def get_default_provider(db: Session) -> str:
        """Obtém o provider padrão."""
        return ConfiguracaoService.obter_valor(
            db, "rag_default_provider", "openai"
        )
    
    @staticmethod
    def get_available_providers() -> list:
        """Lista providers disponíveis."""
        return ["openai", "openrouter", "cohere", "huggingface", "google"]
    
    @staticmethod
    def get_provider_models(provider: str) -> list:
        """Lista modelos disponíveis para um provider."""
        models = {
            "openai": [
                "text-embedding-3-small",
                "text-embedding-3-large",
                "text-embedding-ada-002"
            ],
            "openrouter": [
                "openai/text-embedding-3-small",
                "openai/text-embedding-3-large",
                "openai/text-embedding-ada-002"
            ],
            "cohere": [
                "embed-english-v3.0",
                "embed-multilingual-v3.0",
                "embed-english-light-v3.0"
            ],
            "huggingface": [
                "sentence-transformers/all-mpnet-base-v2",
                "sentence-transformers/all-MiniLM-L6-v2",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            ],
            "google": [
                "models/embedding-001",
                "models/text-embedding-004"
            ]
        }
        return models.get(provider, [])
    
    @staticmethod
    def validate_config(config: Dict[str, Any]) -> Dict[str, str]:
        """Valida configurações e retorna erros."""
        errors = {}
        
        # Validar chunk_size
        chunk_size = config.get("chunk_size", 1000)
        if not isinstance(chunk_size, int) or chunk_size < 100 or chunk_size > 5000:
            errors["chunk_size"] = "Chunk size deve ser entre 100 e 5000"
        
        # Validar chunk_overlap
        chunk_overlap = config.get("chunk_overlap", 200)
        if not isinstance(chunk_overlap, int) or chunk_overlap < 0 or chunk_overlap > 1000:
            errors["chunk_overlap"] = "Chunk overlap deve ser entre 0 e 1000"
        
        # Validar top_k
        top_k = config.get("top_k", 3)
        if not isinstance(top_k, int) or top_k < 1 or top_k > 20:
            errors["top_k"] = "Top K deve ser entre 1 e 20"
        
        # Validar score_threshold
        score_threshold = config.get("score_threshold")
        if score_threshold is not None:
            try:
                threshold = float(score_threshold)
                if threshold < 0 or threshold > 1:
                    errors["score_threshold"] = "Score threshold deve ser entre 0.0 e 1.0"
            except ValueError:
                errors["score_threshold"] = "Score threshold deve ser um número"
        
        return errors
