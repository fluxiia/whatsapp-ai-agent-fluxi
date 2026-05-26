"""
InternalService — Dispatcher unificado do sandbox interno.
Substitui SandboxService com implementação 100% interna (sem agent-sandbox SDK).

Mesma interface pública: executar_tool(db, agente_id, tool_name, arguments)
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from typing import Any, Dict, List, Optional

from config.config_service import ConfiguracaoService
from internal_sandbox.browser_service import InternalBrowserService
from internal_sandbox.shell_service import ShellService
from internal_sandbox.file_service import FileService
from internal_sandbox import code_service as CodeService
from log.log_service import fluxi_log


class InternalService:
    """Dispatcher do sandbox interno para todas as tools sandbox_*."""

    # ─── Ciclo de vida ────────────────────────────────────────────

    @staticmethod
    def conectar(agente_id: int):
        """Prepara o sandbox interno para o agente (lazy — sem conexão real necessária)."""
        fluxi_log.info("sandbox", "execucao", "Sandbox interno pronto", extra={"agente_id": agente_id})

    @staticmethod
    def desconectar(agente_id: int):
        """Libera recursos do agente (fecha browser se aberto)."""
        InternalBrowserService.remover_instancia(agente_id)
        fluxi_log.info("sandbox", "execucao", "Desconectado", extra={"agente_id": agente_id})

    # ─── Ponto de entrada principal ───────────────────────────────

    @staticmethod
    async def executar_tool(
        db,
        agente_id: int,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        inicio = time.time()

        timeout_sandbox = float(
            ConfiguracaoService.obter_valor(db, "mcp_timeout_sandbox", 60)
        )

        try:
            fluxi_log.info("sandbox", "execucao", "Executando tool", extra={"tool_name": tool_name, "timeout": timeout_sandbox})
            resultado = await asyncio.wait_for(
                InternalService._despachar(agente_id, tool_name, arguments),
                timeout=timeout_sandbox,
            )
            tempo_ms = int((time.time() - inicio) * 1000)
            fluxi_log.info("sandbox", "execucao", "Tool concluida", extra={"tool_name": tool_name, "tempo_ms": tempo_ms})
            return {
                "resultado": resultado,
                "output": "llm",
                "enviado_usuario": False,
                "tempo_ms": tempo_ms,
            }

        except asyncio.TimeoutError:
            tempo_ms = int((time.time() - inicio) * 1000)
            return {
                "resultado": {
                    "erro": f"Timeout ao executar '{tool_name}' ({timeout_sandbox}s)."
                },
                "output": "llm",
                "enviado_usuario": False,
                "tempo_ms": tempo_ms,
            }
        except Exception as e:
            tempo_ms = int((time.time() - inicio) * 1000)
            fluxi_log.error("sandbox", "execucao", "Erro ao executar tool", exc_info=True, extra={"tool_name": tool_name})
            # Trunca stacktraces JS do Playwright — só a primeira linha é relevante para o LLM
            error_first_line = str(e).split("\n")[0][:300]
            return {
                "resultado": {"erro": f"Erro em '{tool_name}': {error_first_line}"},
                "output": "llm",
                "enviado_usuario": False,
                "tempo_ms": tempo_ms,
            }

    # ─── Dispatcher ───────────────────────────────────────────────

    @staticmethod
    async def _despachar(
        agente_id: int,
        tool_name: str,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:

        # ── Shell ─────────────────────────────────────────────────
        if tool_name == "sandbox_shell_exec":
            return await ShellService.exec_command(
                command=args["command"],
                exec_dir=args.get("exec_dir"),
                timeout=args.get("timeout"),
            )

        if tool_name == "sandbox_shell_view":
            return ShellService.view_session(args["id"])

        if tool_name == "sandbox_shell_write":
            return await ShellService.write_to_session(
                session_id=args["id"],
                input_text=args["input"],
                press_enter=args.get("press_enter", True),
            )

        if tool_name == "sandbox_shell_kill":
            return await ShellService.kill_session(args["id"])

        if tool_name == "sandbox_shell_list_sessions":
            return {"sessions": ShellService.list_sessions()}

        if tool_name == "sandbox_shell_wait":
            return await ShellService.wait_session(
                session_id=args["id"],
                timeout=args.get("timeout"),
            )

        # ── File ──────────────────────────────────────────────────
        if tool_name == "sandbox_file_read":
            return FileService.read_file(
                file=args["file"],
                start_line=args.get("start_line"),
                end_line=args.get("end_line"),
                sudo=args.get("sudo", False),
            )

        if tool_name == "sandbox_file_write":
            return FileService.write_file(
                file=args["file"],
                content=args["content"],
                append=args.get("append", False),
                encoding=args.get("encoding"),
                leading_newline=args.get("leading_newline", False),
                trailing_newline=args.get("trailing_newline", False),
            )

        if tool_name == "sandbox_file_list":
            return FileService.list_path(
                path=args["path"],
                recursive=args.get("recursive", False),
                show_hidden=args.get("show_hidden", False),
            )

        if tool_name == "sandbox_file_find":
            return FileService.find_files(path=args["path"], glob=args["glob"])

        if tool_name == "sandbox_file_grep":
            return FileService.grep_files(
                path=args["path"],
                pattern=args["pattern"],
                include=args.get("include"),
                case_insensitive=args.get("case_insensitive", True),
                max_results=args.get("max_results", 50),
            )

        if tool_name == "sandbox_file_replace":
            return FileService.replace_in_file(
                file=args["file"],
                old_str=args["old_str"],
                new_str=args["new_str"],
            )

        if tool_name == "sandbox_file_search":
            return FileService.search_in_file(
                file=args["file"],
                regex=args["regex"],
                sudo=args.get("sudo", False),
            )

        if tool_name == "sandbox_file_upload":
            return FileService.upload_file(
                path=args.get("path", FileService.DEFAULT_ROOT),
                filename=args.get("filename", "upload"),
                content_base64=args["content_base64"],
            )

        if tool_name == "sandbox_file_download":
            try:
                file_bytes = FileService.download_file_bytes(args["path"])
                size_kb = len(file_bytes) / 1024
                return {
                    "success": True,
                    "path": args["path"],
                    "size_kb": round(size_kb, 1),
                    "message": f"Arquivo disponível ({size_kb:.1f} KB). Use enviar_arquivo_whatsapp para enviar ao usuário.",
                }
            except Exception as e:
                return {"error": str(e)}

        if tool_name == "sandbox_file_editor":
            return FileService.str_replace_editor(
                command=args["command"],
                path=args["path"],
                file_text=args.get("file_text"),
                old_str=args.get("old_str"),
                new_str=args.get("new_str"),
                insert_line=args.get("insert_line"),
                view_range=args.get("view_range"),
            )

        # ── Code ──────────────────────────────────────────────────
        if tool_name == "sandbox_code_execute":
            return await CodeService.execute_code(
                code=args["code"],
                language=args.get("language", "python"),
                timeout=args.get("timeout", 60),
            )

        # ── Jupyter ───────────────────────────────────────────────
        if tool_name == "sandbox_jupyter_execute":
            session_id = args.get("session_id", "default")
            session = CodeService.get_python_session(session_id)
            return await session.execute(
                code=args["code"],
                timeout=args.get("timeout", 120),
            )

        if tool_name == "sandbox_jupyter_info":
            return {
                "available_kernels": ["python3"],
                "default_kernel": "python3",
                "session_timeout_seconds": 3600,
                "max_sessions": 10,
            }

        if tool_name == "sandbox_jupyter_list_sessions":
            return {"sessions": CodeService.list_python_sessions()}

        if tool_name == "sandbox_jupyter_cleanup_session":
            sid = args["session_id"]
            deleted = CodeService.delete_python_session(sid)
            return {"success": deleted, "message": f"Sessão '{sid}' {'removida' if deleted else 'não encontrada'}"}

        # ── Node.js ───────────────────────────────────────────────
        if tool_name == "sandbox_nodejs_execute":
            return await CodeService.execute_nodejs(
                code=args["code"],
                timeout=args.get("timeout", 60),
                session_id=args.get("session_id"),
                stdin=args.get("stdin"),
            )

        if tool_name == "sandbox_nodejs_info":
            return await CodeService.get_nodejs_info()

        # ── Python packages ───────────────────────────────────────
        if tool_name == "sandbox_python_packages":
            pkgs = await CodeService.get_python_packages()
            return {"packages": pkgs}

        if tool_name == "sandbox_nodejs_packages":
            return {"packages": [], "message": "npm list não implementado no sandbox interno"}

        # ── Sandbox info ──────────────────────────────────────────
        if tool_name == "sandbox_get_context":
            return {
                "home_dir": FileService.DEFAULT_ROOT,
                "info": f"Sandbox interno Fluxi | CWD: {ShellService.DEFAULT_CWD}",
            }

        # ── Browser Screenshot (tela) ─────────────────────────────
        if tool_name == "sandbox_browser_screenshot":
            bsvc = InternalBrowserService.obter_instancia(agente_id)
            img_bytes = await bsvc.screenshot(full_page=False)
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return {
                "type": "image",
                "image_base64": b64,
                "mime_type": "image/png",
                "size_kb": round(len(img_bytes) / 1024, 1),
            }

        if tool_name == "sandbox_browser_page_screenshot":
            bsvc = InternalBrowserService.obter_instancia(agente_id)
            img_bytes = await bsvc.screenshot(full_page=args.get("full_page", False))
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return {
                "type": "image",
                "image_base64": b64,
                "mime_type": "image/png",
                "size_kb": round(len(img_bytes) / 1024, 1),
            }

        if tool_name == "sandbox_browser_get_info":
            bsvc = InternalBrowserService.obter_instancia(agente_id)
            await bsvc._ensure_connected()
            page = await bsvc._page_atual()
            return {
                "cdp_url": "internal-playwright",
                "current_url": page.url,
                "headless": bsvc._headless,
            }

        # ── Browser GUI actions (pixel) — redirecionado para Playwright ──
        if tool_name == "sandbox_browser_execute_action":
            bsvc = InternalBrowserService.obter_instancia(agente_id)
            return await _execute_browser_action(bsvc, args)

        # ── Browser Page tools (via InternalBrowserService) ───────
        _BROWSER_PAGE_TOOLS = {
            "sandbox_browser_navigate", "sandbox_browser_click",
            "sandbox_browser_fill", "sandbox_browser_type",
            "sandbox_browser_press_key", "sandbox_browser_hot_key",
            "sandbox_browser_scroll", "sandbox_browser_scroll_to_element",
            "sandbox_browser_hover", "sandbox_browser_select_option",
            "sandbox_browser_check", "sandbox_browser_uncheck",
            "sandbox_browser_upload_file", "sandbox_browser_fill_form",
            "sandbox_browser_get_text", "sandbox_browser_get_html",
            "sandbox_browser_get_markdown", "sandbox_browser_get_elements",
            "sandbox_browser_back", "sandbox_browser_forward",
            "sandbox_browser_reload",
            "sandbox_browser_tabs_list", "sandbox_browser_tabs_new",
            "sandbox_browser_tabs_close", "sandbox_browser_tabs_switch",
            "sandbox_browser_cookies_get", "sandbox_browser_cookies_set",
            "sandbox_browser_cookies_clear",
            "sandbox_browser_detect_captcha", "sandbox_browser_wait_user",
            "sandbox_browser_get_page_state", "sandbox_browser_click_index",
            "sandbox_browser_record",
        }

        if tool_name in _BROWSER_PAGE_TOOLS:
            bsvc = InternalBrowserService.obter_instancia(agente_id)
            return await _executar_browser_tool(bsvc, tool_name, args)

        return {"erro": f"Tool '{tool_name}' não reconhecida no sandbox interno"}

    # ─── Utilitários para envio WhatsApp (mesma API que SandboxService) ──

    @staticmethod
    async def baixar_arquivo(agente_id: int, file_path: str) -> Optional[bytes]:
        try:
            return FileService.download_file_bytes(file_path)
        except Exception as e:
            fluxi_log.error("sandbox", "arquivo", "Erro ao baixar arquivo", exc_info=True, extra={"file_path": file_path})
            return None

    @staticmethod
    async def tirar_screenshot(agente_id: int) -> Optional[bytes]:
        try:
            bsvc = InternalBrowserService.obter_instancia(agente_id)
            return await bsvc.screenshot(full_page=False)
        except Exception as e:
            fluxi_log.error("sandbox", "screenshot", "Erro ao tirar screenshot", exc_info=True)
            return None

    @staticmethod
    async def tirar_screenshot_pagina(agente_id: int, full_page: bool = False) -> Optional[bytes]:
        try:
            bsvc = InternalBrowserService.obter_instancia(agente_id)
            return await bsvc.screenshot(full_page=full_page)
        except Exception as e:
            fluxi_log.error("sandbox", "screenshot", "Erro ao tirar screenshot da pagina", exc_info=True)
            return None


# ─── Browser dispatcher (igual ao sandbox_service.py) ─────────────

async def _executar_browser_tool(bsvc: InternalBrowserService, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name == "sandbox_browser_navigate":
        return await bsvc.navigate(url=args["url"], wait_until=args.get("wait_until", "domcontentloaded"), timeout=args.get("timeout", 60))
    if tool_name == "sandbox_browser_click":
        return await bsvc.click(selector=args.get("selector"), index=args.get("index"), x=args.get("x"), y=args.get("y"))
    if tool_name == "sandbox_browser_fill":
        return await bsvc.fill(text=args["text"], selector=args.get("selector"), index=args.get("index"))
    if tool_name == "sandbox_browser_type":
        return await bsvc.type_text(text=args["text"], delay=args.get("delay"))
    if tool_name == "sandbox_browser_press_key":
        return await bsvc.press_key(key=args["key"])
    if tool_name == "sandbox_browser_hot_key":
        return await bsvc.hot_key(keys=args["keys"])
    if tool_name == "sandbox_browser_scroll":
        return await bsvc.scroll(direction=args.get("direction", "down"), amount=args.get("amount", 3))
    if tool_name == "sandbox_browser_scroll_to_element":
        return await bsvc.scroll_to_element(selector=args["selector"])
    if tool_name == "sandbox_browser_hover":
        return await bsvc.hover(selector=args.get("selector"), x=args.get("x"), y=args.get("y"))
    if tool_name == "sandbox_browser_select_option":
        return await bsvc.select_option(selector=args["selector"], value=args.get("value"), label=args.get("label"), index=args.get("index"))
    if tool_name == "sandbox_browser_check":
        return await bsvc.check(selector=args["selector"])
    if tool_name == "sandbox_browser_uncheck":
        return await bsvc.uncheck(selector=args["selector"])
    if tool_name == "sandbox_browser_upload_file":
        return await bsvc.upload_file(selector=args["selector"], files=args["files"])
    if tool_name == "sandbox_browser_fill_form":
        return await bsvc.fill_form(items=args["items"])
    if tool_name == "sandbox_browser_get_text":
        return await bsvc.get_text()
    if tool_name == "sandbox_browser_get_html":
        return await bsvc.get_html(outer=args.get("outer", False))
    if tool_name == "sandbox_browser_get_markdown":
        return await bsvc.get_markdown()
    if tool_name == "sandbox_browser_get_elements":
        return await bsvc.get_elements(selector=args.get("selector"))
    if tool_name == "sandbox_browser_back":
        return await bsvc.back()
    if tool_name == "sandbox_browser_forward":
        return await bsvc.forward()
    if tool_name == "sandbox_browser_reload":
        return await bsvc.reload()
    if tool_name == "sandbox_browser_tabs_list":
        return await bsvc.tabs_list()
    if tool_name == "sandbox_browser_tabs_new":
        return await bsvc.tabs_new(url=args.get("url"))
    if tool_name == "sandbox_browser_tabs_close":
        return await bsvc.tabs_close(index=args.get("index", 0))
    if tool_name == "sandbox_browser_tabs_switch":
        return await bsvc.tabs_switch(index=args["index"])
    if tool_name == "sandbox_browser_cookies_get":
        return await bsvc.cookies_get(url=args.get("url"))
    if tool_name == "sandbox_browser_cookies_set":
        return await bsvc.cookies_set(cookies=args["cookies"])
    if tool_name == "sandbox_browser_cookies_clear":
        return await bsvc.cookies_clear()
    if tool_name == "sandbox_browser_detect_captcha":
        return await bsvc.detect_captcha()
    if tool_name == "sandbox_browser_wait_user":
        return await bsvc.wait_user(seconds=args.get("seconds", 30.0), mensagem=args.get("mensagem", ""))
    if tool_name == "sandbox_browser_get_page_state":
        return await bsvc.get_page_state(max_content=args.get("max_content", 6000))
    if tool_name == "sandbox_browser_click_index":
        return await bsvc.click_index(index=int(args["index"]))
    if tool_name == "sandbox_browser_record":
        return {"success": False, "message": "Gravação de vídeo não suportada no sandbox interno. Use sandbox_shell_exec com ffmpeg."}
    return {"erro": f"Tool '{tool_name}' não mapeada no InternalBrowserService"}


async def _execute_browser_action(bsvc: InternalBrowserService, args: Dict[str, Any]) -> Dict[str, Any]:
    """Executa ação GUI via Playwright (substitui VNC/execute_action)."""
    action_type = args["action_type"]
    page = await bsvc._page_atual()
    try:
        if action_type == "move_to":
            await page.mouse.move(args.get("x", 0), args.get("y", 0))
        elif action_type == "click":
            await page.mouse.click(args.get("x", 0), args.get("y", 0))
        elif action_type == "double_click":
            await page.mouse.dblclick(args.get("x", 0), args.get("y", 0))
        elif action_type == "right_click":
            await page.mouse.click(args.get("x", 0), args.get("y", 0), button="right")
        elif action_type == "typing":
            await page.keyboard.type(args.get("text", ""))
        elif action_type == "press":
            await page.keyboard.press(args.get("key", ""))
        elif action_type == "hotkey":
            keys = args.get("keys", [])
            await page.keyboard.press("+".join(keys))
        elif action_type == "scroll":
            await page.mouse.wheel(args.get("dx", 0), args.get("dy", 0))
        elif action_type in ("drag_to", "mouse_down", "mouse_up", "key_down", "key_up"):
            return {"success": False, "message": f"Ação '{action_type}' não suportada via Playwright direto"}
        else:
            return {"success": False, "error": f"Ação '{action_type}' desconhecida"}
        return {"success": True, "action": action_type}
    except Exception as e:
        return {"success": False, "error": str(e)}
