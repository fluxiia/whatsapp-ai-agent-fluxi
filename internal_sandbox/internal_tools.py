"""
Tools OpenAI (function calling) do Sandbox Interno Fluxi.
"""
from __future__ import annotations

from typing import Any, Dict, List

from internal_sandbox.tools import obter_sandbox_tools


def obter_internal_tools() -> List[Dict[str, Any]]:
    """Retorna as tools do sandbox interno no formato OpenAI function calling."""
    return obter_sandbox_tools()
