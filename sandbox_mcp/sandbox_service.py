"""
Serviço de integração direta com AIO Sandbox via SDK Python (agent-sandbox).
Usa AsyncSandbox para comunicação direta com o container, sem intermediação MCP.
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from agent_sandbox import AsyncSandbox

from config.config_service import ConfiguracaoService


class SandboxService:
    """Gerencia a conexão com o AIO Sandbox via SDK Python."""

    # Instâncias por agente_id → AsyncSandbox
    _clients: Dict[int, AsyncSandbox] = {}
    _base_urls: Dict[int, str] = {}

    # ─── Ciclo de vida ───────────────────────────────────────────

    @staticmethod
    def obter_cliente(agente_id: int) -> Optional[AsyncSandbox]:
        """Retorna o cliente AsyncSandbox ativo para o agente."""
        return SandboxService._clients.get(agente_id)

    @staticmethod
    def conectar(agente_id: int, base_url: str, timeout: float = 300) -> AsyncSandbox:
        """Cria e registra um AsyncSandbox para o agente."""
        client = AsyncSandbox(base_url=base_url, timeout=timeout)
        SandboxService._clients[agente_id] = client
        SandboxService._base_urls[agente_id] = base_url
        print(f"✅ [SANDBOX-SDK] Cliente conectado para agente {agente_id} em {base_url}")
        return client

    @staticmethod
    def desconectar(agente_id: int):
        """Remove o cliente SDK do agente."""
        SandboxService._clients.pop(agente_id, None)
        SandboxService._base_urls.pop(agente_id, None)
        print(f"🔌 [SANDBOX-SDK] Cliente desconectado para agente {agente_id}")

    @staticmethod
    def obter_base_url(agente_id: int) -> Optional[str]:
        return SandboxService._base_urls.get(agente_id)

    # ─── Execução de tools ───────────────────────────────────────

    @staticmethod
    async def executar_tool(
        db,
        agente_id: int,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Executa uma tool do sandbox via SDK direto.
        Retorna no formato padronizado Fluxi:
        {"resultado": {...}, "output": "llm", "enviado_usuario": False}
        """
        inicio = time.time()
        client = SandboxService.obter_cliente(agente_id)

        if not client:
            return {
                "resultado": {"erro": "Sandbox não conectado para este agente"},
                "output": "llm",
                "enviado_usuario": False,
            }

        timeout_sandbox = float(
            ConfiguracaoService.obter_valor(db, "mcp_timeout_sandbox", 300)
        )

        try:
            print(f"🚀 [SANDBOX-SDK] Executando '{tool_name}' (timeout={timeout_sandbox}s)...")
            resultado = await asyncio.wait_for(
                SandboxService._despachar_tool(client, tool_name, arguments),
                timeout=timeout_sandbox,
            )
            tempo_ms = int((time.time() - inicio) * 1000)
            print(f"✅ [SANDBOX-SDK] '{tool_name}' concluída em {tempo_ms}ms")
            return {
                "resultado": resultado,
                "output": "llm",
                "enviado_usuario": False,
                "tempo_ms": tempo_ms,
            }

        except asyncio.TimeoutError:
            tempo_ms = int((time.time() - inicio) * 1000)
            print(f"⏱️ [SANDBOX-SDK] TIMEOUT: '{tool_name}' excedeu {timeout_sandbox}s")
            return {
                "resultado": {
                    "erro": f"Timeout ao executar '{tool_name}' ({timeout_sandbox}s). "
                    "Tente novamente ou divida a tarefa em partes menores."
                },
                "output": "llm",
                "enviado_usuario": False,
                "tempo_ms": tempo_ms,
            }
        except Exception as e:
            tempo_ms = int((time.time() - inicio) * 1000)
            print(f"❌ [SANDBOX-SDK] ERRO em '{tool_name}': {type(e).__name__}: {e}")
            traceback.print_exc()
            return {
                "resultado": {"erro": f"Erro ao executar '{tool_name}': {str(e)}"},
                "output": "llm",
                "enviado_usuario": False,
                "tempo_ms": tempo_ms,
            }

    # ─── Dispatcher ──────────────────────────────────────────────

    @staticmethod
    async def _despachar_tool(
        client: AsyncSandbox, tool_name: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Mapeia o nome da tool para a chamada real do SDK."""

        # ── Shell ────────────────────────────────────────────────
        if tool_name == "sandbox_shell_exec":
            r = await client.shell.exec_command(
                command=args["command"],
                timeout=args.get("timeout"),
                exec_dir=args.get("exec_dir"),
            )
            return {
                "output": r.data.output if r.data else "",
                "exit_code": r.data.exit_code if r.data else None,
                "status": r.data.status if r.data else None,
            }

        if tool_name == "sandbox_shell_view":
            r = await client.shell.view(id=args["id"])
            return {"output": r.data.output if r.data else ""}

        if tool_name == "sandbox_shell_write":
            r = await client.shell.write_to_process(
                id=args["id"],
                input=args["input"],
                press_enter=args.get("press_enter", True),
            )
            return {"success": True}

        if tool_name == "sandbox_shell_kill":
            await client.shell.kill_process(id=args["id"])
            return {"success": True, "message": f"Processo {args['id']} terminado"}

        # ── File ─────────────────────────────────────────────────
        if tool_name == "sandbox_file_read":
            r = await client.file.read_file(
                file=args["file"],
                start_line=args.get("start_line"),
                end_line=args.get("end_line"),
                sudo=args.get("sudo", False),
            )
            return {"content": r.data.content if r.data else ""}

        if tool_name == "sandbox_file_write":
            r = await client.file.write_file(
                file=args["file"],
                content=args["content"],
                encoding=args.get("encoding"),
                append=args.get("append", False),
                leading_newline=args.get("leading_newline", False),
                trailing_newline=args.get("trailing_newline", False),
                sudo=args.get("sudo", False),
            )
            return {"success": True, "message": f"Arquivo {args['file']} escrito com sucesso"}

        if tool_name == "sandbox_file_list":
            r = await client.file.list_path(
                path=args["path"],
                recursive=args.get("recursive", False),
                show_hidden=args.get("show_hidden", False),
            )
            files = []
            if r.data and r.data.files:
                for f in r.data.files:
                    files.append({
                        "name": f.name if hasattr(f, "name") else str(f),
                        "type": f.type if hasattr(f, "type") else None,
                        "size": f.size if hasattr(f, "size") else None,
                    })
            return {"files": files}

        if tool_name == "sandbox_file_find":
            r = await client.file.find_files(path=args["path"], glob=args["glob"])
            files = r.data.files if r.data and hasattr(r.data, "files") else []
            return {"files": [str(f) for f in files]}

        if tool_name == "sandbox_file_grep":
            r = await client.file.grep_files(
                path=args["path"],
                pattern=args["pattern"],
                include=args.get("include"),
                case_insensitive=args.get("case_insensitive", True),
                max_results=args.get("max_results", 50),
            )
            matches = []
            if r.data and hasattr(r.data, "matches"):
                for m in r.data.matches:
                    matches.append(str(m))
            return {"matches": matches}

        if tool_name == "sandbox_file_upload":
            file_bytes = base64.b64decode(args["content_base64"])
            path = args.get("path", "/home/gem/")
            filename = args.get("filename", "upload")
            full_path = os.path.join(path, filename)
            # Escrever via file API com encoding base64
            await client.file.write_file(
                file=full_path,
                content=args["content_base64"],
                encoding="base64",
            )
            return {"success": True, "path": full_path}

        if tool_name == "sandbox_file_download":
            chunks = []
            async for chunk in client.file.download_file(path=args["path"]):
                chunks.append(chunk)
            file_bytes = b"".join(chunks)
            size_kb = len(file_bytes) / 1024
            # NÃO enviar base64 para o LLM — seria muito grande e estouraria o contexto.
            # Retornar apenas metadata. Para enviar ao usuário, use enviar_arquivo_whatsapp.
            return {
                "success": True,
                "path": args["path"],
                "size_kb": round(size_kb, 1),
                "message": f"Arquivo baixado ({size_kb:.1f} KB). Use enviar_arquivo_whatsapp para enviar ao usuário.",
            }

        if tool_name == "sandbox_file_replace":
            r = await client.file.replace_in_file(
                file=args["file"],
                old_str=args["old_str"],
                new_str=args["new_str"],
                sudo=args.get("sudo", False),
            )
            return {"success": True, "message": "Substituição realizada"}

        if tool_name == "sandbox_file_search":
            r = await client.file.search_in_file(
                file=args["file"],
                regex=args["regex"],
                sudo=args.get("sudo", False),
            )
            matches = []
            if r.data and hasattr(r.data, "matches"):
                for m in r.data.matches:
                    matches.append({
                        "line_number": m.line_number if hasattr(m, "line_number") else None,
                        "line": m.line if hasattr(m, "line") else str(m),
                        "match": m.match if hasattr(m, "match") else None,
                    })
            return {"matches": matches}

        # ── Browser ──────────────────────────────────────────────
        if tool_name == "sandbox_browser_screenshot":
            chunks = []
            async for chunk in client.browser.screenshot():
                chunks.append(chunk)
            img_bytes = b"".join(chunks)
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return {
                "type": "image",
                "image_base64": b64,
                "mime_type": "image/png",
                "size_kb": round(len(img_bytes) / 1024, 1),
            }

        if tool_name == "sandbox_browser_page_screenshot":
            chunks = []
            async for chunk in client.browser_page.screenshot(
                full_page=args.get("full_page", False),
            ):
                chunks.append(chunk)
            img_bytes = b"".join(chunks)
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return {
                "type": "image",
                "image_base64": b64,
                "mime_type": "image/png",
                "size_kb": round(len(img_bytes) / 1024, 1),
            }

        if tool_name == "sandbox_browser_get_info":
            r = await client.browser.get_info()
            return {
                "cdp_url": r.data.cdp_url if r.data else None,
                "viewport": str(r.data.viewport) if r.data else None,
            }

        # ── Browser Page ─────────────────────────────────────────
        if tool_name == "sandbox_browser_navigate":
            r = await client.browser_page.navigate(
                url=args["url"],
                wait_until=args.get("wait_until"),
                timeout=args.get("timeout"),
            )
            return {"success": True, "url": args["url"]}

        if tool_name == "sandbox_browser_click":
            r = await client.browser_page.click(
                selector=args.get("selector"),
                index=args.get("index"),
                x=args.get("x"),
                y=args.get("y"),
            )
            return {"success": True}

        if tool_name == "sandbox_browser_fill":
            r = await client.browser_page.fill(
                text=args["text"],
                selector=args.get("selector"),
                index=args.get("index"),
            )
            return {"success": True}

        if tool_name == "sandbox_browser_type":
            r = await client.browser_page.type_text(
                text=args["text"],
                delay=args.get("delay"),
            )
            return {"success": True}

        if tool_name == "sandbox_browser_press_key":
            r = await client.browser_page.press_key(key=args["key"])
            return {"success": True}

        if tool_name == "sandbox_browser_scroll":
            r = await client.browser_page.scroll(
                direction=args.get("direction", "down"),
                amount=args.get("amount", 3),
            )
            return {"success": True}

        if tool_name == "sandbox_browser_get_text":
            r = await client.browser_page.get_text()
            return {"text": r.data if r.data else ""}

        if tool_name == "sandbox_browser_get_html":
            r = await client.browser_page.get_html(outer=args.get("outer", False))
            return {"html": r.data if r.data else ""}

        if tool_name == "sandbox_browser_get_markdown":
            r = await client.browser_page.get_markdown()
            data = r.data if r.data else {}
            return {"markdown": data}

        if tool_name == "sandbox_browser_get_elements":
            r = await client.browser_page.get_elements()
            return {"elements": r.data if r.data else []}

        if tool_name == "sandbox_browser_select_option":
            r = await client.browser_page.select_option(
                selector=args["selector"],
                value=args.get("value"),
                label=args.get("label"),
                index=args.get("index"),
            )
            return {"success": True}

        if tool_name == "sandbox_browser_hover":
            r = await client.browser_page.hover(
                selector=args.get("selector"),
                x=args.get("x"),
                y=args.get("y"),
            )
            return {"success": True}

        if tool_name == "sandbox_browser_back":
            await client.browser_page.back()
            return {"success": True}

        if tool_name == "sandbox_browser_forward":
            await client.browser_page.forward()
            return {"success": True}

        if tool_name == "sandbox_browser_reload":
            await client.browser_page.reload()
            return {"success": True}

        if tool_name == "sandbox_browser_hot_key":
            r = await client.browser_page.hot_key(keys=args["keys"])
            return {"success": True}

        if tool_name == "sandbox_browser_tabs_list":
            r = await client.browser_tabs.list()
            return {"tabs": r.data if r.data else []}

        if tool_name == "sandbox_browser_tabs_new":
            r = await client.browser_tabs.create(url=args.get("url"))
            return {"success": True}

        if tool_name == "sandbox_browser_tabs_close":
            r = await client.browser_tabs.close(index=args.get("index", 0))
            return {"success": True}

        if tool_name == "sandbox_browser_tabs_switch":
            r = await client.browser_tabs.switch(index=args["index"])
            return {"success": True}

        # ── Jupyter ──────────────────────────────────────────────
        if tool_name == "sandbox_jupyter_execute":
            r = await client.jupyter.execute_code(
                code=args["code"],
                timeout=args.get("timeout", 120),
                session_id=args.get("session_id"),
                kernel_name=args.get("kernel_name"),
            )
            outputs = []
            if r.data and hasattr(r.data, "outputs"):
                for o in r.data.outputs:
                    outputs.append(str(o))
            status = r.data.status if r.data and hasattr(r.data, "status") else "ok"
            return {"outputs": outputs, "status": status, "success": status == "ok"}

        if tool_name == "sandbox_jupyter_info":
            r = await client.jupyter.get_info()
            info = {}
            if r.data:
                info = {
                    "available_kernels": r.data.available_kernels if hasattr(r.data, "available_kernels") else [],
                    "default_kernel": r.data.default_kernel if hasattr(r.data, "default_kernel") else "python3",
                    "session_timeout_seconds": r.data.session_timeout_seconds if hasattr(r.data, "session_timeout_seconds") else None,
                    "max_sessions": r.data.max_sessions if hasattr(r.data, "max_sessions") else None,
                }
            return info

        if tool_name == "sandbox_jupyter_list_sessions":
            r = await client.jupyter.list_sessions()
            sessions = []
            if r.data and hasattr(r.data, "sessions"):
                for s in r.data.sessions:
                    sessions.append(str(s))
            return {"sessions": sessions}

        if tool_name == "sandbox_jupyter_cleanup_session":
            session_id = args["session_id"]
            await client.jupyter.delete_session(session_id=session_id)
            return {"success": True, "message": f"Sessão Jupyter '{session_id}' removida"}

        # ── Node.js ───────────────────────────────────────────────
        if tool_name == "sandbox_nodejs_execute":
            kwargs = {
                "code": args["code"],
                "timeout": args.get("timeout", 60),
            }
            if args.get("session_id"):
                kwargs["session_id"] = args["session_id"]
            if args.get("files"):
                kwargs["files"] = args["files"]
            if args.get("stdin"):
                kwargs["stdin"] = args["stdin"]
            r = await client.nodejs.execute_nodejs_code(**kwargs)
            result = {"success": True}
            if r.data:
                result["status"] = r.data.status if hasattr(r.data, "status") else "ok"
                result["stdout"] = r.data.stdout if hasattr(r.data, "stdout") else ""
                result["stderr"] = r.data.stderr if hasattr(r.data, "stderr") else ""
                result["exit_code"] = r.data.exit_code if hasattr(r.data, "exit_code") else 0
                if hasattr(r.data, "outputs"):
                    result["outputs"] = [str(o) for o in r.data.outputs]
            return result

        if tool_name == "sandbox_nodejs_info":
            r = await client.nodejs.info()
            info = {}
            if r.data:
                info = {
                    "node_version": r.data.node_version if hasattr(r.data, "node_version") else "",
                    "npm_version": r.data.npm_version if hasattr(r.data, "npm_version") else "",
                    "runtime_directory": r.data.runtime_directory if hasattr(r.data, "runtime_directory") else "",
                }
            return info

        # ── Code (genérico) ──────────────────────────────────────
        if tool_name == "sandbox_code_execute":
            r = await client.code.execute(
                code=args["code"],
                language=args.get("language", "python"),
                timeout=args.get("timeout", 60),
            )
            output = ""
            if r.data:
                output = r.data.output if hasattr(r.data, "output") else str(r.data)
            return {"output": output, "success": True}

        # ── File str_replace_editor (Anthropic-style) ────────────
        if tool_name == "sandbox_file_editor":
            r = await client.file.str_replace_editor(
                command=args["command"],
                path=args["path"],
                file_text=args.get("file_text"),
                old_str=args.get("old_str"),
                new_str=args.get("new_str"),
                insert_line=args.get("insert_line"),
                view_range=args.get("view_range"),
            )
            output = ""
            if r.data:
                output = r.data.output if hasattr(r.data, "output") else str(r.data)
            return {"output": output, "success": True}

        # ── Browser Cookies ──────────────────────────────────────
        if tool_name == "sandbox_browser_cookies_get":
            r = await client.browser_cookies.get_cookies(
                url=args.get("url"),
            )
            return {"cookies": r.data if r.data else []}

        if tool_name == "sandbox_browser_cookies_set":
            r = await client.browser_cookies.set_cookies(
                cookies=args["cookies"],
            )
            return {"success": True}

        if tool_name == "sandbox_browser_cookies_clear":
            r = await client.browser_cookies.clear_cookies()
            return {"success": True}

        # ── Browser Record (screencast) ──────────────────────────
        if tool_name == "sandbox_browser_record":
            r = await client.browser_page.record(
                action=args.get("action", "once"),
                save_path=args.get("save_path"),
                duration=args.get("duration"),
                fps=args.get("fps"),
                quality=args.get("quality"),
            )
            return {"result": r.data if r.data else {}, "success": True}

        # ── Browser Form ─────────────────────────────────────────
        if tool_name == "sandbox_browser_fill_form":
            r = await client.browser_page.fill_form(items=args["items"])
            return {"success": True}

        if tool_name == "sandbox_browser_check":
            r = await client.browser_page.check(selector=args["selector"])
            return {"success": True}

        if tool_name == "sandbox_browser_uncheck":
            r = await client.browser_page.uncheck(selector=args["selector"])
            return {"success": True}

        if tool_name == "sandbox_browser_upload_file":
            r = await client.browser_page.upload_file(
                selector=args["selector"],
                files=args["files"],
            )
            return {"success": True}

        if tool_name == "sandbox_browser_scroll_to_element":
            r = await client.browser_page.scroll_to_element(selector=args["selector"])
            return {"success": True}

        # ── Shell sessions ─────────────────────────────────────────
        if tool_name == "sandbox_shell_list_sessions":
            r = await client.shell.list_sessions()
            sessions = []
            if r.data and hasattr(r.data, "sessions"):
                for s in r.data.sessions:
                    sessions.append(str(s))
            return {"sessions": sessions}

        if tool_name == "sandbox_shell_wait":
            r = await client.shell.wait_for_process(
                id=args["id"],
                timeout=args.get("timeout"),
            )
            return {
                "output": r.data.output if r.data and hasattr(r.data, "output") else "",
                "exit_code": r.data.exit_code if r.data and hasattr(r.data, "exit_code") else None,
            }

        # ── Browser GUI/VNC actions ────────────────────────────────
        if tool_name == "sandbox_browser_execute_action":
            action_type = args["action_type"]
            action_map = {
                "move_to": {"type": "move_to", "x": args.get("x", 0), "y": args.get("y", 0)},
                "click": {"type": "click", "x": args.get("x"), "y": args.get("y"),
                          "button": args.get("button", "left"), "num_clicks": args.get("num_clicks", 1)},
                "double_click": {"type": "double_click", "x": args.get("x"), "y": args.get("y")},
                "right_click": {"type": "right_click", "x": args.get("x"), "y": args.get("y")},
                "typing": {"type": "typing", "text": args.get("text", ""),
                           "use_clipboard": args.get("use_clipboard", False)},
                "press": {"type": "press", "key": args.get("key", "")},
                "hotkey": {"type": "hotkey", "keys": args.get("keys", [])},
                "scroll": {"type": "scroll", "dx": args.get("dx", 0), "dy": args.get("dy", 0)},
                "drag_to": {"type": "drag_to", "x": args.get("x", 0), "y": args.get("y", 0)},
                "mouse_down": {"type": "mouse_down", "button": args.get("button", "left")},
                "mouse_up": {"type": "mouse_up", "button": args.get("button", "left")},
                "key_down": {"type": "key_down", "key": args.get("key", "")},
                "key_up": {"type": "key_up", "key": args.get("key", "")},
            }
            action_data = action_map.get(action_type)
            if not action_data:
                return {"erro": f"Tipo de ação '{action_type}' não reconhecido"}
            # Remover None values
            action_data = {k: v for k, v in action_data.items() if v is not None}
            r = await client.browser.execute_action(request=action_data)
            return {"success": True, "action": action_type}

        # ── Sandbox info ─────────────────────────────────────────
        if tool_name == "sandbox_get_context":
            r = await client.sandbox.get_context()
            return {
                "home_dir": r.data.home_dir if r.data and hasattr(r.data, "home_dir") else "/home/gem",
                "info": str(r.data) if r.data else "",
            }

        if tool_name == "sandbox_python_packages":
            r = await client.sandbox.python_packages()
            packages = []
            if r.data:
                for p in r.data:
                    packages.append(str(p))
            return {"packages": packages}

        if tool_name == "sandbox_nodejs_packages":
            r = await client.sandbox.nodejs_packages()
            packages = []
            if r.data:
                for p in r.data:
                    packages.append(str(p))
            return {"packages": packages}

        # Tool não reconhecida
        return {"erro": f"Tool '{tool_name}' não reconhecida no sandbox SDK"}

    # ─── Utilitários para envio WhatsApp ─────────────────────────

    @staticmethod
    async def baixar_arquivo(agente_id: int, file_path: str) -> Optional[bytes]:
        """Baixa bytes de um arquivo do sandbox via SDK (file.download_file)."""
        client = SandboxService.obter_cliente(agente_id)
        if not client:
            return None
        try:
            chunks = []
            async for chunk in client.file.download_file(path=file_path):
                chunks.append(chunk)
            return b"".join(chunks)
        except Exception as e:
            print(f"❌ [SANDBOX-SDK] Erro ao baixar {file_path}: {e}")
            return None

    @staticmethod
    async def tirar_screenshot(agente_id: int) -> Optional[bytes]:
        """Tira screenshot da tela do sandbox e retorna os bytes PNG."""
        client = SandboxService.obter_cliente(agente_id)
        if not client:
            return None
        try:
            chunks = []
            async for chunk in client.browser.screenshot():
                chunks.append(chunk)
            return b"".join(chunks)
        except Exception as e:
            print(f"❌ [SANDBOX-SDK] Erro ao tirar screenshot: {e}")
            return None

    @staticmethod
    async def tirar_screenshot_pagina(
        agente_id: int, full_page: bool = False
    ) -> Optional[bytes]:
        """Tira screenshot da página do browser e retorna os bytes PNG."""
        client = SandboxService.obter_cliente(agente_id)
        if not client:
            return None
        try:
            chunks = []
            async for chunk in client.browser_page.screenshot(full_page=full_page):
                chunks.append(chunk)
            return b"".join(chunks)
        except Exception as e:
            print(f"❌ [SANDBOX-SDK] Erro ao tirar screenshot da página: {e}")
            return None
