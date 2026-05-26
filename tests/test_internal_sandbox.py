"""
Testes das principais funcionalidades do módulo internal_sandbox.

Cobertura:
  - ShellService  : exec, background, view, kill, list
  - FileService   : write, read, append, replace, find, grep, list_path
  - CodeService   : PythonSession persistente, timeout, isolamento, subprocess
  - InternalService: dispatcher via executar_tool (shell + file + jupyter)
  - Tools schema  : obter_internal_tools() / obter_sandbox_tools()

Execução:
    pip install pytest pytest-asyncio
    pytest tests/test_internal_sandbox.py -v

Nota: asyncio_mode=auto no pytest.ini detecta automaticamente testes async.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

# Adiciona o root do projeto ao path para imports funcionarem sem instalação
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from internal_sandbox.shell_service import ShellService
from internal_sandbox.file_service import FileService
from internal_sandbox import code_service as CodeService
from internal_sandbox.internal_tools import obter_internal_tools
from internal_sandbox.tools import obter_sandbox_tools

IS_WINDOWS = sys.platform == "win32"


# ═══════════════════════════════════════════════════════════════════════════════
# ShellService
# ═══════════════════════════════════════════════════════════════════════════════

class TestShellService:

    async def test_exec_echo(self, tmp_path):
        """Execução simples: echo retorna o texto esperado."""
        result = await ShellService.exec_command(
            command="echo hello_fluxi",
            exec_dir=str(tmp_path),
        )
        assert result["exit_code"] == 0
        assert "hello_fluxi" in result["output"]
        assert result["status"] == "done"
        assert "session_id" in result

    async def test_exec_exit_code_nonzero(self, tmp_path):
        """Comando com falha retorna exit_code != 0."""
        result = await ShellService.exec_command(
            command="exit 42",
            exec_dir=str(tmp_path),
        )
        assert result["exit_code"] != 0

    async def test_exec_multiline_output(self, tmp_path):
        """Múltiplas linhas de output são capturadas (usa python para ser cross-platform)."""
        result = await ShellService.exec_command(
            command=f'{sys.executable} -c "print(\\"linha1\\"); print(\\"linha2\\"); print(\\"linha3\\")"',
            exec_dir=str(tmp_path),
        )
        assert result["exit_code"] == 0
        assert "linha1" in result["output"]
        assert "linha3" in result["output"]

    async def test_exec_background_returns_session(self, tmp_path):
        """Modo background retorna session_id imediatamente."""
        result = await ShellService.exec_command(
            command="sleep 1 && echo bg_done",
            exec_dir=str(tmp_path),
            background=True,
        )
        assert "session_id" in result
        assert result["status"] == "running"

        # Cleanup
        sid = result["session_id"]
        await ShellService.kill_session(sid)

    @pytest.mark.skipif(IS_WINDOWS, reason="sleep não disponível no Windows via subprocess")
    async def test_exec_timeout_returns_running(self, tmp_path):
        """Timeout durante execução retorna status=running com session_id."""
        result = await ShellService.exec_command(
            command="sleep 10",
            exec_dir=str(tmp_path),
            timeout=0.3,
        )
        assert result["status"] == "running"
        assert "session_id" in result

        # Cleanup
        await ShellService.kill_session(result["session_id"])

    async def test_list_sessions_contains_active(self, tmp_path):
        """Sessão em background aparece no list_sessions."""
        result = await ShellService.exec_command(
            command="sleep 2",
            exec_dir=str(tmp_path),
            background=True,
        )
        sid = result["session_id"]

        sessions = ShellService.list_sessions()
        ids = [s["id"] for s in sessions]
        assert sid in ids

        await ShellService.kill_session(sid)

    async def test_view_session(self, tmp_path):
        """view_session retorna output acumulado de sessão existente."""
        result = await ShellService.exec_command(
            command="echo view_test",
            exec_dir=str(tmp_path),
        )
        sid = result["session_id"]
        view = ShellService.view_session(sid)
        assert "view_test" in view["output"]
        assert view["status"] == "done"

    async def test_view_session_not_found(self):
        """view_session com ID inválido retorna erro."""
        view = ShellService.view_session("nao_existe_xyzabc")
        assert "error" in view

    async def test_kill_session(self, tmp_path):
        """kill_session termina processo e retorna success=True."""
        result = await ShellService.exec_command(
            command="sleep 30",
            exec_dir=str(tmp_path),
            background=True,
        )
        sid = result["session_id"]
        kill = await ShellService.kill_session(sid)
        assert kill["success"] is True

        # Sessão removida do registro
        sessions = ShellService.list_sessions()
        assert sid not in [s["id"] for s in sessions]


# ═══════════════════════════════════════════════════════════════════════════════
# FileService
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileService:

    def test_write_and_read(self, tmp_path):
        """Escreve arquivo e lê conteúdo de volta."""
        path = str(tmp_path / "teste.txt")
        write = FileService.write_file(path, "conteudo_fluxi")
        assert write.get("success") is True or "error" not in write

        read = FileService.read_file(path)
        assert "conteudo_fluxi" in read["content"]

    def test_read_nonexistent(self, tmp_path):
        """Ler arquivo inexistente retorna chave 'error'."""
        read = FileService.read_file(str(tmp_path / "nao_existe.txt"))
        assert "error" in read

    def test_append_file(self, tmp_path):
        """Append adiciona conteúdo sem sobrescrever."""
        path = str(tmp_path / "append.txt")
        FileService.write_file(path, "linha1\n")
        FileService.write_file(path, "linha2\n", append=True)

        read = FileService.read_file(path)
        assert "linha1" in read["content"]
        assert "linha2" in read["content"]

    def test_overwrite_file(self, tmp_path):
        """Escrita sem append sobrescreve conteúdo anterior."""
        path = str(tmp_path / "overwrite.txt")
        FileService.write_file(path, "antigo")
        FileService.write_file(path, "novo")

        read = FileService.read_file(path)
        assert read["content"] == "novo"
        assert "antigo" not in read["content"]

    def test_partial_read_lines(self, tmp_path):
        """Leitura parcial com start_line/end_line retorna só as linhas pedidas."""
        path = str(tmp_path / "linhas.txt")
        content = "\n".join(f"linha{i}" for i in range(10))
        FileService.write_file(path, content)

        read = FileService.read_file(path, start_line=2, end_line=5)
        assert "linha2" in read["content"]
        assert "linha5" not in read["content"]
        assert "linha0" not in read["content"]

    def test_delete_file_via_os(self, tmp_path):
        """Após remover o arquivo com os.remove, leitura retorna erro."""
        path = str(tmp_path / "para_deletar.txt")
        FileService.write_file(path, "temp")
        os.remove(path)

        read = FileService.read_file(path)
        assert "error" in read

    def test_replace_in_file(self, tmp_path):
        """replace_in_file substitui string corretamente."""
        path = str(tmp_path / "replace.txt")
        FileService.write_file(path, "valor_antigo")

        result = FileService.replace_in_file(path, "valor_antigo", "valor_novo")
        assert result.get("success") is True

        read = FileService.read_file(path)
        assert "valor_novo" in read["content"]
        assert "valor_antigo" not in read["content"]

    def test_list_path(self, tmp_path):
        """list_path retorna os arquivos criados no diretório."""
        FileService.write_file(str(tmp_path / "a.txt"), "a")
        FileService.write_file(str(tmp_path / "b.txt"), "b")

        result = FileService.list_path(str(tmp_path))
        names = [e["name"] for e in result.get("files", [])]
        assert "a.txt" in names
        assert "b.txt" in names

    def test_find_files(self, tmp_path):
        """find_files localiza arquivos por glob pattern."""
        FileService.write_file(str(tmp_path / "foo.py"), "x = 1")
        FileService.write_file(str(tmp_path / "bar.txt"), "y = 2")

        result = FileService.find_files(str(tmp_path), "*.py")
        assert any("foo.py" in f for f in result.get("files", []))
        assert not any("bar.txt" in f for f in result.get("files", []))

    def test_grep_files(self, tmp_path):
        """grep_files encontra padrão no conteúdo dos arquivos."""
        FileService.write_file(str(tmp_path / "grep_me.txt"), "fluxi_grep_target\noutra linha")

        result = FileService.grep_files(str(tmp_path), pattern="fluxi_grep_target")
        assert len(result.get("matches", [])) >= 1

    def test_write_creates_parent_dirs(self, tmp_path):
        """write_file cria diretórios intermediários automaticamente."""
        path = str(tmp_path / "subdir" / "deep" / "arquivo.txt")
        result = FileService.write_file(path, "nested")
        assert "error" not in result

        read = FileService.read_file(path)
        assert read["content"] == "nested"


# ═══════════════════════════════════════════════════════════════════════════════
# CodeService
# ═══════════════════════════════════════════════════════════════════════════════

class TestCodeService:

    async def test_session_hello(self):
        """PythonSession executa print e captura saída (cross-platform, sem subprocess)."""
        session = CodeService.get_python_session("test_hello")
        result = await session.execute("print('hello_from_fluxi')")
        assert result["success"] is True
        assert "hello_from_fluxi" in "".join(result["outputs"])
        CodeService.delete_python_session("test_hello")

    async def test_session_arithmetic(self):
        """Cálculo aritmético Python produz resultado correto."""
        session = CodeService.get_python_session("test_arith")
        result = await session.execute("print(2 ** 10)")
        assert result["success"] is True
        assert "1024" in "".join(result["outputs"])
        CodeService.delete_python_session("test_arith")

    async def test_session_error(self):
        """Código com erro retorna success=False com traceback."""
        session = CodeService.get_python_session("test_err")
        result = await session.execute("raise ValueError('erro_de_teste')")
        assert result["success"] is False
        assert "ValueError" in "".join(result["outputs"])
        CodeService.delete_python_session("test_err")

    async def test_session_syntax_error(self):
        """Sintaxe inválida retorna success=False."""
        session = CodeService.get_python_session("test_syn")
        result = await session.execute("def broken(:\n    pass")
        assert result["success"] is False
        CodeService.delete_python_session("test_syn")

    async def test_session_timeout(self):
        """Loop infinito é interrompido por timeout."""
        session = CodeService.get_python_session("test_timeout")
        result = await session.execute("import time\nwhile True: time.sleep(0.01)", timeout=0.5)
        assert result["success"] is False
        assert "timeout" in "".join(result["outputs"]).lower() or result["status"] == "error"
        CodeService.delete_python_session("test_timeout")

    @pytest.mark.skipif(IS_WINDOWS, reason="python3 não disponível em subprocess no Windows")
    async def test_execute_code_subprocess(self, tmp_path):
        """execute_code via subprocess (python3 — POSIX/Docker)."""
        result = await CodeService.execute_code(
            code="print('subprocess_ok')",
            language="python",
            cwd=str(tmp_path),
        )
        assert result["success"] is True
        assert "subprocess_ok" in result["output"]

    async def test_python_session_persistence(self):
        """PythonSession mantém variáveis entre execuções."""
        session = CodeService.get_python_session("test_persistence")
        result1 = await session.execute("x = 42")
        assert result1["success"] is True

        result2 = await session.execute("print(x)")
        assert result2["success"] is True
        assert "42" in result2["outputs"][0]

        CodeService.delete_python_session("test_persistence")

    async def test_python_session_isolation(self):
        """Sessões diferentes não compartilham estado."""
        s1 = CodeService.get_python_session("session_a")
        s2 = CodeService.get_python_session("session_b")

        await s1.execute("val = 'fluxi_a'")
        result = await s2.execute("print(val)")

        # session_b não deve ter 'val' → deve lançar NameError
        assert result["success"] is False

        CodeService.delete_python_session("session_a")
        CodeService.delete_python_session("session_b")

    def test_list_python_sessions(self):
        """list_python_sessions reflete sessões criadas."""
        CodeService.get_python_session("list_test_1")
        CodeService.get_python_session("list_test_2")

        sessions = CodeService.list_python_sessions()
        ids = [s["session_id"] for s in sessions]
        assert "list_test_1" in ids
        assert "list_test_2" in ids

        CodeService.delete_python_session("list_test_1")
        CodeService.delete_python_session("list_test_2")

    def test_delete_python_session(self):
        """delete_python_session remove sessão do registry."""
        CodeService.get_python_session("del_test")
        deleted = CodeService.delete_python_session("del_test")
        assert deleted is True

        # Segunda deleção retorna False
        assert CodeService.delete_python_session("del_test") is False

    async def test_python_session_capture_stdout(self):
        """Saída de print() é capturada nos outputs."""
        session = CodeService.get_python_session("stdout_test")
        result = await session.execute("print('capturado')\nprint('segundo')")
        assert result["success"] is True
        combined = "".join(result["outputs"])
        assert "capturado" in combined
        assert "segundo" in combined

        CodeService.delete_python_session("stdout_test")


# ═══════════════════════════════════════════════════════════════════════════════
# InternalService — Dispatcher
# ═══════════════════════════════════════════════════════════════════════════════

class MockDb:
    """Mock mínimo do DB — ConfiguracaoService.obter_valor retorna default."""
    pass


class TestInternalServiceDispatcher:
    """Testa o dispatcher InternalService.executar_tool() para as principais tools."""

    @pytest.fixture(autouse=True)
    def mock_db(self, monkeypatch):
        """Faz ConfiguracaoService.obter_valor retornar o default sem acessar DB."""
        from config import config_service
        monkeypatch.setattr(
            config_service.ConfiguracaoService,
            "obter_valor",
            lambda db, chave, default=None: default,
        )
        return MockDb()

    AGENTE_ID = 999

    async def test_dispatch_shell_exec(self, mock_db, tmp_path):
        """Dispatcher encaminha sandbox_shell_exec corretamente."""
        from internal_sandbox.internal_service import InternalService

        result = await InternalService.executar_tool(
            db=mock_db,
            agente_id=self.AGENTE_ID,
            tool_name="sandbox_shell_exec",
            arguments={"command": "echo dispatcher_ok", "exec_dir": str(tmp_path)},
        )
        assert "dispatcher_ok" in str(result)

    async def test_dispatch_file_write(self, mock_db, tmp_path):
        """Dispatcher encaminha sandbox_file_write corretamente."""
        from internal_sandbox.internal_service import InternalService

        path = str(tmp_path / "dispatch_write.txt")
        result = await InternalService.executar_tool(
            db=mock_db,
            agente_id=self.AGENTE_ID,
            tool_name="sandbox_file_write",
            arguments={"file": path, "content": "escrita_via_dispatcher"},
        )
        assert "error" not in str(result).lower() or "success" in str(result).lower()

        read = FileService.read_file(path)
        assert "escrita_via_dispatcher" in read.get("content", "")

    async def test_dispatch_file_read(self, mock_db, tmp_path):
        """Dispatcher encaminha sandbox_file_read corretamente."""
        from internal_sandbox.internal_service import InternalService

        path = str(tmp_path / "dispatch_read.txt")
        FileService.write_file(path, "leitura_via_dispatcher")

        result = await InternalService.executar_tool(
            db=mock_db,
            agente_id=self.AGENTE_ID,
            tool_name="sandbox_file_read",
            arguments={"file": path},
        )
        assert "leitura_via_dispatcher" in str(result)

    async def test_dispatch_jupyter_execute(self, mock_db):
        """Dispatcher encaminha sandbox_jupyter_execute (PythonSession — cross-platform)."""
        from internal_sandbox.internal_service import InternalService

        result = await InternalService.executar_tool(
            db=mock_db,
            agente_id=self.AGENTE_ID,
            tool_name="sandbox_jupyter_execute",
            arguments={"code": "print('python_via_dispatcher')", "session_id": "test_dispatch"},
        )
        assert "python_via_dispatcher" in str(result)
        CodeService.delete_python_session("test_dispatch")

    async def test_dispatch_unknown_tool(self, mock_db):
        """Tool desconhecida retorna erro sem exceção não tratada."""
        from internal_sandbox.internal_service import InternalService

        result = await InternalService.executar_tool(
            db=mock_db,
            agente_id=self.AGENTE_ID,
            tool_name="sandbox_tool_que_nao_existe",
            arguments={},
        )
        assert "erro" in str(result).lower() or "error" in str(result).lower() or "unknown" in str(result).lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Tools Schema (OpenAI function calling)
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolsSchema:

    def test_obter_sandbox_tools_returns_list(self):
        """obter_sandbox_tools retorna uma lista não-vazia."""
        tools = obter_sandbox_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_obter_internal_tools_matches_sandbox_tools(self):
        """obter_internal_tools() retorna as mesmas tools que obter_sandbox_tools()."""
        internal = obter_internal_tools()
        sandbox = obter_sandbox_tools()
        assert len(internal) == len(sandbox)

    def test_tools_have_required_openai_structure(self):
        """Cada tool segue o schema OpenAI: type='function' + function.name + function.parameters."""
        tools = obter_internal_tools()
        for tool in tools:
            assert tool.get("type") == "function", f"Tool sem type='function': {tool}"
            fn = tool.get("function", {})
            assert "name" in fn, f"Tool sem 'name': {tool}"
            assert "description" in fn, f"Tool sem 'description': {fn['name']}"
            assert "parameters" in fn, f"Tool sem 'parameters': {fn['name']}"

    def test_tools_names_have_sandbox_prefix(self):
        """Quase todas as tools têm prefixo 'sandbox_'.
        Exceções conhecidas e intencionais: enviar_arquivo_whatsapp, enviar_screenshot_whatsapp.
        """
        KNOWN_EXCEPTIONS = {"enviar_arquivo_whatsapp", "enviar_screenshot_whatsapp"}
        tools = obter_internal_tools()
        bad = [
            t["function"]["name"]
            for t in tools
            if not t["function"]["name"].startswith("sandbox_")
            and t["function"]["name"] not in KNOWN_EXCEPTIONS
        ]
        assert bad == [], f"Tools inesperadas sem prefixo 'sandbox_': {bad}"

    def test_tools_cover_main_categories(self):
        """Há tools de shell, file, browser, python e code."""
        names = {t["function"]["name"] for t in obter_internal_tools()}
        categories = {
            "shell":   any("shell" in n for n in names),
            "file":    any("file" in n for n in names),
            "browser": any("browser" in n for n in names),
            "python":  any("python" in n for n in names),
        }
        missing = [cat for cat, found in categories.items() if not found]
        assert missing == [], f"Categorias de tools ausentes: {missing}"

    def test_tools_parameter_types_are_valid(self):
        """Parâmetros de tools possuem 'type' em cada propriedade."""
        tools = obter_internal_tools()
        for tool in tools:
            fn = tool["function"]
            params = fn.get("parameters", {})
            props = params.get("properties", {})
            for prop_name, prop_def in props.items():
                assert "type" in prop_def, (
                    f"Propriedade '{prop_name}' de '{fn['name']}' sem 'type'"
                )

    def test_no_duplicate_tool_names(self):
        """Não há nomes de tools duplicados."""
        names = [t["function"]["name"] for t in obter_internal_tools()]
        assert len(names) == len(set(names)), f"Nomes duplicados: {set(n for n in names if names.count(n) > 1)}"


# ═══════════════════════════════════════════════════════════════════════════════
# Browser (requer playwright install — pulado se binário ausente)
# ═══════════════════════════════════════════════════════════════════════════════

def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        import subprocess
        result = subprocess.run(
            ["playwright", "install", "--dry-run"],
            capture_output=True, timeout=5
        )
        # Verifica se o executável do chromium existe
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exec_path = p.chromium.executable_path
        return os.path.exists(exec_path)
    except Exception:
        return False


@pytest.mark.skipif(not _playwright_available(), reason="Playwright Chromium não instalado")
class TestBrowserService:

    async def test_navigate_example(self):
        """navigate() carrega página e retorna title/url."""
        from internal_sandbox.browser_service import InternalBrowserService

        bsvc = InternalBrowserService.obter_instancia(agente_id=9999)
        try:
            result = await bsvc.navigate("https://example.com", timeout=30)
            assert result.get("success") is True
            assert "example" in result.get("title", "").lower()
        finally:
            InternalBrowserService.remover_instancia(9999)

    async def test_screenshot_returns_base64(self):
        """screenshot() retorna string base64 não-vazia."""
        import base64
        from internal_sandbox.browser_service import InternalBrowserService

        bsvc = InternalBrowserService.obter_instancia(agente_id=9998)
        try:
            await bsvc.navigate("https://example.com", timeout=30)
            shot = await bsvc.screenshot()
            assert shot.get("success") is True
            data = shot.get("data", "")
            assert len(data) > 0
            # Verifica que é base64 válido
            base64.b64decode(data)
        finally:
            InternalBrowserService.remover_instancia(9998)
