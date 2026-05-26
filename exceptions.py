"""Hierarquia de erros de dominio do Fluxi.

Cada subclasse representa uma CATEGORIA SEMANTICA de problema, com politica
de tratamento associada (recuperavel via retry vs. imprevisto que propaga
ate supervisor).

Regras:
- Capturar pela classe especifica no caminho, NUNCA `except Exception`
  generico no meio do fluxo de negocio (so no supervisor explicito).
- `to_tool_result()` eh o canal de comunicacao com o LLM: erro estruturado
  que o agente consegue ler e auto-corrigir.
- `to_dict()` eh o canal de comunicacao com o audit (`agent_failures`).
- Mensagem que vai ao USUARIO FINAL nao mora aqui — vive em
  `sistema_fallback_mensagem` (config no DB), editavel sem deploy.

Inspirado em Brisa_Zap/app/exceptions.py.
"""
from __future__ import annotations

from typing import Any, Optional


class FluxiError(Exception):
    """Classe base. Nao instancie diretamente — use uma subclasse."""

    # Codigo curto e estavel pra logs/audit/i18n. Ex: "validation.required".
    code: str = "fluxi.unknown"
    # Se True, o supervisor PODE tentar retry (com backoff). Default False:
    # melhor errar pelo lado seguro — quem souber que eh retryable declara.
    is_recoverable: bool = False

    def __init__(
        self,
        message: str,
        *,
        field: Optional[str] = None,
        suggestion: Optional[str] = None,
        meta: Optional[dict] = None,
        cause: Optional[BaseException] = None,
    ):
        super().__init__(message)
        self.message = message
        self.field = field
        self.suggestion = suggestion
        self.meta = meta or {}
        self.__cause__ = cause

    def to_dict(self) -> dict:
        """Serializacao pra audit (`agent_failures.payload`). Inclui contexto
        completo. NAO inclui traceback — esse vai em coluna separada."""
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "suggestion": self.suggestion,
            "meta": self.meta,
            "recoverable": self.is_recoverable,
            "cause_class": type(self.__cause__).__name__ if self.__cause__ else None,
            "cause_message": str(self.__cause__) if self.__cause__ else None,
        }

    def to_tool_result(self) -> dict:
        """Formato que o LLM consegue ler e tentar auto-corrigir.

        Convencao: dict com chaves `erro`, `field`, `suggestion`. O agente
        deve devolver isto via tool_result pro modelo no proximo turno.
        """
        out: dict[str, Any] = {"erro": self.message, "code": self.code}
        if self.field:
            out["field"] = self.field
        if self.suggestion:
            out["suggestion"] = self.suggestion
        return out

    def __repr__(self) -> str:
        return f"<{type(self).__name__} code={self.code!r} message={self.message!r}>"


# ────────────────────────────────────────────────────────────────────────
# CATEGORIAS — cada uma com politica de tratamento documentada.
# ────────────────────────────────────────────────────────────────────────


class ValidationError(FluxiError):
    """Entrada invalida — chamador (LLM ou humano) precisa corrigir.

    Politica: NAO retry. Devolver via `to_tool_result()` pro LLM ajustar
    args; ou devolver 400 ao cliente HTTP. Nao registrar como falha no
    `agent_failures` — eh comportamento esperado.
    """

    code = "validation.invalid"
    is_recoverable = False


class NotFoundError(FluxiError):
    """Recurso pedido nao existe.

    Politica: NAO retry. Devolver pro LLM/cliente. Nao audita como falha.
    """

    code = "not_found"
    is_recoverable = False


class PermissionDeniedError(FluxiError):
    """Operacao negada por politica/ownership.

    Politica: NAO retry. Audita em `agent_failures` so se for chamada
    indevida (tentativa de acesso cross-sessao); chamada legitima negada
    so loga em info.
    """

    code = "permission.denied"
    is_recoverable = False


class ConfigError(FluxiError):
    """Config ausente, mal formatada, ou inconsistente.

    Politica: IMPREVISTO. Propaga ate o supervisor. Em prod isso vira
    audit + alerta admin — config errada eh sempre bug de operacao, nao
    de usuario.
    """

    code = "config.invalid"
    is_recoverable = False


class IntegrationError(FluxiError):
    """Servico externo (HTTP, gRPC, fila) falhou de forma recuperavel.

    Politica: RETRY com exponential backoff + jitter. Limite explicito
    de tentativas. Apos esgotar, propaga pra supervisor que decide
    fallback/circuit-breaker.

    Causas tipicas:
    - timeout
    - 5xx
    - connection refused
    - DNS temporariamente fora
    """

    code = "integration.failed"
    is_recoverable = True


class LLMError(IntegrationError):
    """Erro especifico do provedor LLM (OpenRouter, etc.).

    Especializa IntegrationError porque alguns codigos exigem politica
    diferente (rate limit usa RateLimitError, ja com retry_after).
    """

    code = "llm.failed"
    is_recoverable = True


class RateLimitError(IntegrationError):
    """Provedor externo aplicou rate limit.

    Politica: retry, mas com backoff longo (respeitando `retry_after_s`
    se vier do servidor). Conta separada de IntegrationError comum pra
    nao acionar circuit breaker prematuramente.
    """

    code = "rate_limit.exceeded"
    is_recoverable = True

    def __init__(
        self,
        message: str,
        *,
        retry_after_s: Optional[float] = None,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.retry_after_s = retry_after_s
        if retry_after_s is not None:
            self.meta.setdefault("retry_after_s", retry_after_s)


class ToolError(FluxiError):
    """Ferramenta (tool do agente / sandbox / MCP) falhou.

    Politica: NAO retry automatico — o LLM eh quem decide o proximo passo
    (chamar outra tool, pedir info ao usuario, desistir). Sempre devolver
    via `to_tool_result()` no ciclo do agente.

    Falha de tool NUNCA derruba o turno; vai ao LLM como ferramenta_resultado
    de erro. Quem decide se eh fim de linha eh o LLM ou o supervisor depois
    de N falhas seguidas (turno_service na fase G).
    """

    code = "tool.failed"
    is_recoverable = False


class CanalError(FluxiError):
    """Erro ao falar com o canal (neonize/WA, telegram).

    Politica: depende do tipo. Timeout/socket = recuperavel via retry.
    Sessao desconectada / logout = IMPREVISTO, propaga ate supervisor
    reconectar.
    """

    code = "canal.failed"
    is_recoverable = True
