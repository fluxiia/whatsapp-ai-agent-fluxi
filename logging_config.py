"""
Configuração de logging para o sistema RAG.
"""
import logging
import sys
from datetime import datetime

# No Windows o console costuma ser cp1252; logs/prints com emoji quebram com UnicodeEncodeError.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def setup_logging():
    """Configura o sistema de logging."""
    
    # Criar logger principal
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remover handlers existentes
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Criar formatter
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler para console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Handler para arquivo (logs específicos do RAG)
    file_handler = logging.FileHandler('rag_processing.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Configurar loggers específicos
    rag_logger = logging.getLogger('rag')
    rag_logger.setLevel(logging.DEBUG)
    
    # Silenciar logs verbosos do watchfiles
    logging.getLogger('watchfiles').setLevel(logging.WARNING)
    logging.getLogger('watchfiles.main').setLevel(logging.WARNING)
    
    # Log de início
    logger.info("=" * 50)
    logger.info("SISTEMA DE LOGGING INICIADO")
    logger.info(f"Timestamp: {datetime.now()}")
    logger.info("=" * 50)
    
    return logger

# Configurar logging ao importar
setup_logging()
