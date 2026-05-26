"""
Configurações e validações de segurança para o Fluxi.
Centraliza políticas de segurança, validações de input e sanitização.
"""
import os
import re
import base64
from typing import Optional, List, Tuple, Any
from pathlib import Path
from config.config_service import ConfiguracaoService


class SecurityConfig:
    """Configurações de segurança."""

    # Configurações de arquivo
    MAX_FILE_SIZE_MB: int = 10
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10MB

    # Tipos de MIME permitidos
    ALLOWED_IMAGE_TYPES: List[str] = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    ALLOWED_AUDIO_TYPES: List[str] = ["audio/mpeg", "audio/ogg", "audio/wav", "audio/mp4", "audio/aac"]
    ALLOWED_VIDEO_TYPES: List[str] = ["video/mp4", "video/webm", "video/avi"]

    # Sanitização de texto
    MAX_TEXT_LENGTH: int = 10000
    MAX_SYSTEM_PROMPT_LENGTH: int = 50000

    # Sandbox
    SANDBOX_TIMEOUT_SECONDS: int = 300
    SANDBOX_MAX_EXECUTION_TIME: int = 120
    SANDBOX_MAX_OUTPUT_SIZE: int = 100000  # 100KB

    @classmethod
    def load_from_config(cls, db_session=None):
        """Carrega configurações do banco de dados."""
        if db_session:
            cls.MAX_FILE_SIZE_MB = ConfiguracaoService.obter_valor(
                db_session, "sistema_max_file_size_mb", 10
            )
            cls.MAX_FILE_SIZE_BYTES = cls.MAX_FILE_SIZE_MB * 1024 * 1024

            allowed_images = ConfiguracaoService.obter_valor(
                db_session, "sistema_allowed_image_types", ""
            )
            if allowed_images:
                cls.ALLOWED_IMAGE_TYPES = allowed_images.split(",")


class SecurityValidator:
    """Validações de segurança para inputs e uploads."""

    @staticmethod
    def validate_file_size(file_bytes: bytes, max_size_mb: Optional[int] = None) -> bool:
        """
        Valida se o arquivo está dentro do tamanho máximo permitido.

        Args:
            file_bytes: Conteúdo do arquivo
            max_size_mb: Tamanho máximo em MB (usa padrão se não especificado)

        Returns:
            bool: True se válido, False se inválido

        Raises:
            ValueError: Se o arquivo for muito grande
        """
        max_size = max_size_mb * 1024 * 1024 if max_size_mb else SecurityConfig.MAX_FILE_SIZE_BYTES

        if len(file_bytes) > max_size:
            max_mb = max_size / (1024 * 1024)
            raise ValueError(f"Arquivo muito grande. Máximo permitido: {max_mb:.1f}MB")

        return True

    @staticmethod
    def validate_mime_type(mime_type: str, allowed_types: List[str]) -> bool:
        """
        Valida se o MIME type é permitido.

        Args:
            mime_type: MIME type do arquivo
            allowed_types: Lista de MIME types permitidos

        Returns:
            bool: True se válido, False se inválido
        """
        if not mime_type:
            return False

        # Remove parâmetros (ex: "audio/mpeg; codecs=opus" -> "audio/mpeg")
        mime_clean = mime_type.split(";")[0].strip().lower()

        allowed_clean = [t.lower() for t in allowed_types]
        return mime_clean in allowed_clean

    @staticmethod
    def validate_text_length(text: str, max_length: Optional[int] = None) -> bool:
        """
        Valida se o texto está dentro do tamanho máximo permitido.

        Args:
            text: Texto a validar
            max_length: Tamanho máximo (usa padrão se não especificado)

        Returns:
            bool: True se válido, False se inválido
        """
        if not text:
            return True

        max_len = max_length if max_length is not None else SecurityConfig.MAX_TEXT_LENGTH
        return len(text) <= max_len

    @staticmethod
    def sanitize_text(text: str, max_length: Optional[int] = None) -> str:
        """
        Sanitiza texto removendo caracteres perigosos e limitando tamanho.

        Args:
            text: Texto a sanitizar
            max_length: Tamanho máximo (usa padrão se não especificado)

        Returns:
            str: Texto sanitizado
        """
        if not text:
            return ""

        # Limitar tamanho
        max_len = max_length if max_length is not None else SecurityConfig.MAX_TEXT_LENGTH
        text = text[:max_len]

        # Remover caracteres nulos e controle
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')

        return text

    @staticmethod
    def validate_base64_image(base64_str: str, max_size_mb: Optional[int] = None) -> bool:
        """
        Valida uma string base64 que representa uma imagem.

        Args:
            base64_str: String base64 da imagem
            max_size_mb: Tamanho máximo em MB (usa padrão se não especificado)

        Returns:
            bool: True se válido, False se inválido

        Raises:
            ValueError: Se a string base64 for inválida ou muito grande
        """
        try:
            # Decodificar base64
            image_bytes = base64.b64decode(base64_str)

            # Validar tamanho
            SecurityValidator.validate_file_size(image_bytes, max_size_mb)

            # Verificar se parece uma imagem válida (assinatura de arquivo)
            if len(image_bytes) < 4:
                raise ValueError("Arquivo muito pequeno para ser uma imagem válida")

            return True

        except Exception as e:
            raise ValueError(f"Imagem base64 inválida: {str(e)}")

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitiza nome de arquivo removendo caracteres perigosos.

        Args:
            filename: Nome do arquivo

        Returns:
            str: Nome de arquivo sanitizado
        """
        if not filename:
            return "unknown"

        # Remover caracteres perigosos
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)

        # Limitar tamanho
        if len(sanitized) > 255:
            name, ext = os.path.splitext(sanitized)
            sanitized = name[:200] + ext

        return sanitized

    @staticmethod
    def validate_path(path: str, base_path: str) -> bool:
        """
        Valida se um caminho está dentro de um diretório base (previne path traversal).

        Args:
            path: Caminho a validar
            base_path: Diretório base permitido

        Returns:
            bool: True se válido, False se inválido

        Raises:
            ValueError: Se o caminho tentar acessar fora do diretório base
        """
        try:
            # Converter para caminhos absolutos
            abs_path = Path(path).resolve()
            abs_base = Path(base_path).resolve()

            # Verificar se está dentro do diretório base
            try:
                abs_path.relative_to(abs_base)
                return True
            except ValueError:
                raise ValueError(f"Caminho fora do diretório permitido: {path}")

        except Exception as e:
            raise ValueError(f"Erro ao validar caminho: {str(e)}")


class CodeExecutionValidator:
    """Validações específicas para execução de código no sandbox."""

    DANGEROUS_IMPORTS = [
        'os.system', 'subprocess', 'eval', 'exec', 'compile',
        'ctypes', 'pickle', 'shelve', 'marshal',
        'socket', 'telnetlib', 'ftplib', 'poplib',
        'imaplib', 'smtplib', 'urllib.request', 'urllib.urlopen',
        'open', 'file', '__import__'
    ]

    DANGEROUS_FUNCTIONS = [
        'open(', 'exec(', 'eval(', 'compile(',
        '__import__(', 'getattr(', 'setattr(',
        'delattr(', 'hasattr(', 'dir('
    ]

    @staticmethod
    def validate_python_code(code: str) -> Tuple[bool, Optional[str]]:
        """
        Valida código Python para execução no sandbox.

        Args:
            code: Código Python a validar

        Returns:
            Tuple[bool, Optional[str]]: (válido, motivo_erro)
        """
        if not code or not code.strip():
            return True, None

        # Verificar comprimento
        if len(code) > 50000:
            return False, "Código muito longo (máximo: 50000 caracteres)"

        # Verificar imports perigosos
        for dangerous in CodeExecutionValidator.DANGEROUS_IMPORTS:
            if dangerous in code:
                return False, f"Import perigoso detectado: {dangerous}"

        # Verificar funções perigosas
        for dangerous in CodeExecutionValidator.DANGEROUS_FUNCTIONS:
            if dangerous in code:
                return False, f"Função perigosa detectada: {dangerous}"

        # Tentar fazer parse da sintaxe
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            return False, f"Erro de sintaxe: {str(e)}"

        return True, None

    @staticmethod
    def sanitize_output(output: str, max_size: Optional[int] = None) -> str:
        """
        Sanitiza output de código executado.

        Args:
            output: Output do código
            max_size: Tamanho máximo (usa padrão se não especificado)

        Returns:
            str: Output sanitizado
        """
        if not output:
            return ""

        max_len = max_size if max_size is not None else SecurityConfig.SANDBOX_MAX_OUTPUT_SIZE

        # Truncar se muito grande
        if len(output) > max_len:
            output = output[:max_len] + "\n...[output truncado]"

        return output


class SecurityError(Exception):
    """Erro de segurança personalizado."""

    def __init__(self, message: str, code: str = "SECURITY_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)

    def __str__(self):
        return f"[{self.code}] {self.message}"


# Funções de conveniência
def validate_upload_file(
    file_bytes: bytes,
    mime_type: str,
    allowed_types: List[str],
    max_size_mb: Optional[int] = None
) -> bool:
    """
    Valida completamente um arquivo de upload.

    Args:
        file_bytes: Conteúdo do arquivo
        mime_type: MIME type do arquivo
        allowed_types: Lista de MIME types permitidos
        max_size_mb: Tamanho máximo em MB (usa padrão se não especificado)

    Returns:
        bool: True se válido

    Raises:
        SecurityError: Se o arquivo for inválido
    """
    try:
        # Validar tamanho
        SecurityValidator.validate_file_size(file_bytes, max_size_mb)

        # Validar tipo
        if not SecurityValidator.validate_mime_type(mime_type, allowed_types):
            raise SecurityError(
                f"Tipo de arquivo não permitido: {mime_type}",
                code="INVALID_FILE_TYPE"
            )

        return True

    except ValueError as e:
        raise SecurityError(str(e), code="FILE_VALIDATION_ERROR")


def sanitize_user_input(text: str, max_length: Optional[int] = None) -> str:
    """
    Sanitiza input do usuário.

    Args:
        text: Texto a sanitizar
        max_length: Tamanho máximo (usa padrão se não especificado)

    Returns:
        str: Texto sanitizado
    """
    return SecurityValidator.sanitize_text(text, max_length)