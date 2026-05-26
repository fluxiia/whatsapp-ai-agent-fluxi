"""
CodeService — Execução de código (Python, Node.js, bash) internamente.
Python com sessões persistentes (like Jupyter). Outros via subprocess.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import time
import traceback
from typing import Any, Dict, List, Optional

# Importar validações de segurança
try:
    from security import CodeExecutionValidator, SecurityConfig
except ImportError:
    # Fallback se o módulo de segurança não estiver disponível
    class CodeExecutionValidator:
        @staticmethod
        def validate_python_code(code: str):
            return True, None

    class SecurityConfig:
        SANDBOX_MAX_OUTPUT_SIZE = 100000

DEFAULT_CWD: str = os.environ.get(
    "INTERNAL_SANDBOX_CWD",
    os.path.join(os.path.expanduser("~"), "fluxi_sandbox"),
)


# ── Execução genérica via subprocess ────────────────────────────

async def execute_code(
    code: str,
    language: str = "python",
    timeout: float = 60,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa código em subprocess. Suporta python, node, bash, ruby."""
    # Validação de segurança para Python
    if language in ["python", "python3"]:
        is_valid, error_msg = CodeExecutionValidator.validate_python_code(code)
        if not is_valid:
            return {
                "error": f"Código inválido: {error_msg}",
                "success": False,
                "output": ""
            }

    work_dir = cwd or DEFAULT_CWD
    os.makedirs(work_dir, exist_ok=True)

    lang_map: Dict[str, tuple] = {
        "python":     (".py",  ["python3"]),
        "python3":    (".py",  ["python3"]),
        "javascript": (".js",  ["node"]),
        "nodejs":     (".js",  ["node"]),
        "node":       (".js",  ["node"]),
        "bash":       (".sh",  ["bash"]),
        "sh":         (".sh",  ["bash"]),
        "ruby":       (".rb",  ["ruby"]),
    }

    if language not in lang_map:
        return {"error": f"Linguagem '{language}' não suportada", "success": False, "output": ""}

    ext, cmd_parts = lang_map[language]

    with tempfile.NamedTemporaryFile(
        suffix=ext, dir=work_dir, delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=work_dir,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace")

            # Sanitizar output
            if hasattr(CodeExecutionValidator, 'sanitize_output'):
                output = CodeExecutionValidator.sanitize_output(output)

            return {
                "output": output,
                "exit_code": process.returncode,
                "success": process.returncode == 0,
            }
        except asyncio.TimeoutError:
            process.kill()
            return {
                "output": f"Timeout após {timeout}s",
                "exit_code": -1,
                "success": False,
            }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── Sessões Python persistentes (Jupyter-like) ──────────────────

class PythonSession:
    """Sessão Python com globals compartilhados entre execuções (kernel Jupyter simples)."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        self._globals: Dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }

    async def execute(self, code: str, timeout: float = 120) -> Dict[str, Any]:
        """Executa código Python no contexto da sessão (non-blocking via executor)."""

        # Validação de segurança
        is_valid, error_msg = CodeExecutionValidator.validate_python_code(code)
        if not is_valid:
            return {
                "outputs": [f"Código inválido: {error_msg}"],
                "status": "error",
                "success": False
            }

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, self._run_sync, code),
                timeout=timeout,
            )
            return result
        except asyncio.TimeoutError:
            return {"outputs": [f"Timeout após {timeout}s"], "status": "error", "success": False}

    def _run_sync(self, code: str) -> Dict[str, Any]:
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = stdout_buf
        sys.stderr = stderr_buf
        outputs: List[str] = []
        try:
            exec(compile(code, "<jupyter>", "exec"), self._globals)  # noqa: S102
            out = stdout_buf.getvalue()
            err = stderr_buf.getvalue()
            if out:
                # Sanitizar output se disponível
                if hasattr(CodeExecutionValidator, 'sanitize_output'):
                    out = CodeExecutionValidator.sanitize_output(out)
                outputs.append(out)
            if err:
                err_sanitized = CodeExecutionValidator.sanitize_output(err) if hasattr(CodeExecutionValidator, 'sanitize_output') else err
                outputs.append(f"[stderr]\n{err_sanitized}")
            return {"outputs": outputs, "status": "ok", "success": True}
        except Exception:
            tb = traceback.format_exc()
            # Sanitizar traceback para não expor informações sensíveis
            if hasattr(CodeExecutionValidator, 'sanitize_output'):
                tb = CodeExecutionValidator.sanitize_output(tb)
            outputs.append(tb)
            return {"outputs": outputs, "status": "error", "success": False}
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr


# ── Registry de sessões ──────────────────────────────────────────

_python_sessions: Dict[str, PythonSession] = {}


def get_python_session(session_id: str) -> PythonSession:
    if session_id not in _python_sessions:
        _python_sessions[session_id] = PythonSession(session_id)
    return _python_sessions[session_id]


def list_python_sessions() -> List[Dict[str, Any]]:
    return [
        {
            "session_id": s.session_id,
            "age_s": round(time.time() - s.created_at, 1),
            "globals_count": len(s._globals),
        }
        for s in _python_sessions.values()
    ]


def delete_python_session(session_id: str) -> bool:
    return _python_sessions.pop(session_id, None) is not None


# ── Node.js execução direta ──────────────────────────────────────

async def execute_nodejs(
    code: str,
    timeout: float = 60,
    cwd: Optional[str] = None,
    session_id: Optional[str] = None,
    stdin: Optional[str] = None,
) -> Dict[str, Any]:
    return await execute_code(code, language="node", timeout=timeout, cwd=cwd)


# ── Informações do ambiente ──────────────────────────────────────

async def get_python_packages() -> List[str]:
    """Lista pacotes instalados via pip."""
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "list", "--format=columns",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return stdout.decode("utf-8", errors="replace").splitlines()
    except Exception:
        return []


async def get_nodejs_info() -> Dict[str, Any]:
    """Obtém versão do Node.js e npm."""
    async def _run(cmd: List[str]) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return out.decode().strip()
        except Exception:
            return "não disponível"

    return {
        "node_version": await _run(["node", "--version"]),
        "npm_version": await _run(["npm", "--version"]),
        "runtime_directory": DEFAULT_CWD,
    }
