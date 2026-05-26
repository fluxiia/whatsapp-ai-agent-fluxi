"""
InternalBrowserService — Controla Chromium próprio via Playwright.

- Usa playwright.chromium.launch() → inicia Chrome próprio localmente
- Headless por padrão; usa DISPLAY se disponível (Linux com Xvfb)
- VNC substituído por screenshot streaming via WebSocket no frontend

Mantém EXATAMENTE a mesma API do BrowserService para compatibilidade total.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from typing import Any, Dict, List, Optional

from log.log_service import fluxi_log


class InternalBrowserService:
    """Controla Chromium próprio via Playwright (headless ou com display)."""

    _instances: Dict[int, "InternalBrowserService"] = {}
    _instances_lock = asyncio.Lock()  # protege criação concorrente do singleton

    def __init__(self, agente_id: int):
        self.agente_id = agente_id
        self._playwright = None
        self._browser = None
        self._page = None
        self._context = None
        self._lock = asyncio.Lock()
        self._headless: bool = not bool(os.environ.get("DISPLAY"))

    # ─── Singleton por agente ─────────────────────────────────────

    @classmethod
    async def obter_instancia_async(cls, agente_id: int) -> "InternalBrowserService":
        """Versão async-safe do singleton (preferida em contextos assíncronos)."""
        async with cls._instances_lock:
            if agente_id not in cls._instances:
                cls._instances[agente_id] = InternalBrowserService(agente_id)
            return cls._instances[agente_id]

    @classmethod
    def obter_instancia(cls, agente_id: int) -> "InternalBrowserService":
        """Versão sync — segura pois dict é GIL-protected e criação é idempotente."""
        if agente_id not in cls._instances:
            cls._instances[agente_id] = InternalBrowserService(agente_id)
        return cls._instances[agente_id]

    @classmethod
    def remover_instancia(cls, agente_id: int):
        inst = cls._instances.pop(agente_id, None)
        if inst:
            asyncio.create_task(_safe_close(inst))

    # ─── Ciclo de vida ────────────────────────────────────────────

    async def _ensure_connected(self):
        async with self._lock:
            if self._browser is not None:
                try:
                    if self._browser.is_connected():
                        await self._ensure_page()
                        return
                except Exception:
                    pass

            from playwright.async_api import async_playwright

            if self._playwright is None:
                fluxi_log.info("sandbox", "browser", "Iniciando Playwright", extra={"agente_id": self.agente_id})
                try:
                    self._playwright = await asyncio.wait_for(
                        async_playwright().start(), timeout=30.0
                    )
                except asyncio.TimeoutError:
                    raise RuntimeError(
                        "[INTERNAL-BROWSER] Timeout (30s) ao iniciar Playwright. "
                        "Execute 'playwright install chromium' e verifique a instalação."
                    )

            launch_args = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--window-size=1280,1024",
            ]
            if os.environ.get("DISPLAY"):
                launch_args.append(f"--display={os.environ['DISPLAY']}")

            fluxi_log.info("sandbox", "browser", "Iniciando Chromium", extra={"headless": self._headless, "agente_id": self.agente_id})
            try:
                self._browser = await asyncio.wait_for(
                    self._playwright.chromium.launch(
                        headless=self._headless,
                        args=launch_args,
                    ),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                # Limpa playwright para não deixar estado inválido
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
                raise RuntimeError(
                    "[INTERNAL-BROWSER] Timeout (60s) ao iniciar Chromium. "
                    "Verifique se playwright e chromium estão instalados corretamente."
                )
            await self._ensure_page()
            fluxi_log.info("sandbox", "browser", "Chromium iniciado", extra={"agente_id": self.agente_id})

    async def _ensure_page(self):
        if self._context is None or not self._browser.contexts:
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 1024},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                ),
            )
        else:
            self._context = self._browser.contexts[0]

        pages = self._context.pages
        if pages:
            self._page = pages[-1]
        else:
            self._page = await self._context.new_page()

    async def _page_atual(self):
        await self._ensure_connected()
        if self._page is None or self._page.is_closed():
            await self._ensure_page()
        return self._page

    async def desconectar(self):
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._browser = None
        self._playwright = None
        self._page = None
        self._context = None

    # ─── Screenshot ───────────────────────────────────────────────

    async def screenshot(self, full_page: bool = False) -> bytes:
        page = await self._page_atual()
        return await page.screenshot(full_page=full_page, type="png")

    # ─── Detecção de CAPTCHA ──────────────────────────────────────

    async def detect_captcha(self) -> Dict:
        page = await self._page_atual()
        try:
            title = await asyncio.wait_for(page.title(), timeout=5)
        except Exception:
            title = ""
        url = page.url
        try:
            result = await asyncio.wait_for(page.evaluate("""
            () => {
                const title = document.title.toLowerCase();
                if (title.includes('just a moment') || title.includes('checking your browser') ||
                    document.querySelector('#challenge-form') ||
                    document.querySelector('.cf-browser-verification')) {
                    return {type: 'cloudflare', found: true};
                }
                if (document.querySelector('iframe[src*="recaptcha"]') ||
                    document.querySelector('div.g-recaptcha') ||
                    document.querySelector('[data-sitekey]')) {
                    return {type: 'recaptcha', found: true};
                }
                if (document.querySelector('iframe[src*="hcaptcha"]') ||
                    document.querySelector('.h-captcha')) {
                    return {type: 'hcaptcha', found: true};
                }
                if (title.includes('captcha')) {
                    return {type: 'generic_captcha', found: true};
                }
                return {type: null, found: false};
            }
        """), timeout=10)
        except Exception:
            result = {"type": None, "found": False}
        captcha_found = result.get("found", False)
        captcha_type = result.get("type")
        response: Dict[str, Any] = {
            "captcha_detected": captcha_found,
            "captcha_type": captcha_type,
            "url": url,
            "title": title,
        }
        if captcha_found:
            response["instrucao"] = (
                f"CAPTCHA detectado ({captcha_type}). "
                "Abra o painel do sandbox interno para resolver manualmente. "
                "Depois use sandbox_browser_wait_user para aguardar."
            )
        return response

    async def wait_user(self, seconds: float = 30.0, mensagem: str = "") -> Dict:
        fluxi_log.info("sandbox", "browser", "Aguardando usuario", extra={"seconds": seconds})
        await asyncio.sleep(seconds)
        page = await self._page_atual()
        title = await page.title()
        return {
            "success": True,
            "waited_seconds": seconds,
            "current_url": page.url,
            "current_title": title,
            "mensagem": mensagem or f"Aguardou {seconds}s para interação do usuário.",
        }

    # ─── Navegação ────────────────────────────────────────────────

    async def navigate(self, url: str, wait_until: str = "domcontentloaded", timeout: float = 30) -> Dict:
        page = await self._page_atual()
        # Nunca usar networkidle — SPAs ficam em background requests infinitos
        safe_wait = wait_until if wait_until in ("load", "domcontentloaded") else "domcontentloaded"
        # Nunca mais que 30s — evita timeout de 300s do InternalService
        safe_timeout = min(float(timeout), 30.0)
        response = None
        _timed_out = False
        try:
            # asyncio.wait_for é o hard-timeout real: page.goto() sozinho não dispara
            # quando a conexão TCP fica aberta sem resposta (Google anti-bot, etc.)
            response = await asyncio.wait_for(
                page.goto(url, wait_until=safe_wait, timeout=int(safe_timeout * 1000)),
                timeout=safe_timeout + 2,  # 2s de folga além do timeout Playwright
            )
        except asyncio.TimeoutError:
            _timed_out = True
        except Exception:
            pass
        if _timed_out:
            # Fechar TODO o browser — page.close() é insuficiente.
            # Após timeout de navegação, a conexão CDP fica congestionada com comandos
            # sem resposta. Calls subsequentes como page.evaluate() (detect_captcha,
            # get_page_state, etc.) também travarão indefinidamente na mesma conexão.
            try:
                await asyncio.wait_for(self.desconectar(), timeout=8)
            except Exception:
                self._browser = None
                self._playwright = None
                self._page = None
                self._context = None
            page = None
            try:
                page = await self._page_atual()
            except Exception:
                pass
        try:
            title = await asyncio.wait_for(page.title(), timeout=5) if page is not None else ""
        except Exception:
            title = ""
        try:
            current_url = page.url if page is not None else ""
        except Exception:
            current_url = ""
        result: Dict[str, Any] = {
            "success": True,
            "url": current_url,
            "title": title,
            "status": response.status if response else None,
        }
        if _timed_out:
            result["warning"] = f"Navegação para {url} atingiu timeout de {int(safe_timeout)}s. Página pode ter carregado parcialmente."
        try:
            captcha = await asyncio.wait_for(self.detect_captcha(), timeout=10)
            if captcha["captcha_detected"]:
                result["captcha_detected"] = True
                result["captcha_type"] = captcha["captcha_type"]
                result["instrucao"] = captcha["instrucao"]
        except Exception:
            pass
        return result

    async def back(self) -> Dict:
        page = await self._page_atual()
        await page.go_back()
        return {"success": True, "url": page.url}

    async def forward(self) -> Dict:
        page = await self._page_atual()
        await page.go_forward()
        return {"success": True, "url": page.url}

    async def reload(self) -> Dict:
        page = await self._page_atual()
        await page.reload()
        return {"success": True, "url": page.url}

    async def wait(self, timeout: float = 1.0) -> Dict:
        await asyncio.sleep(timeout)
        return {"success": True, "waited_seconds": timeout}

    # ─── Interação ────────────────────────────────────────────────

    async def click(self, selector: Optional[str] = None, index: Optional[int] = None,
                    x: Optional[float] = None, y: Optional[float] = None) -> Dict:
        page = await self._page_atual()
        if x is not None and y is not None:
            await page.mouse.click(x, y)
        elif selector:
            if index is not None:
                elements = await page.query_selector_all(selector)
                if index < len(elements):
                    await elements[index].click()
                else:
                    return {"success": False, "error": f"Índice {index} fora do range ({len(elements)} elementos)"}
            else:
                await page.click(selector)
        else:
            return {"success": False, "error": "Forneça selector ou coordenadas x,y"}
        return {"success": True}

    async def fill(self, text: str, selector: Optional[str] = None, index: Optional[int] = None) -> Dict:
        page = await self._page_atual()
        if selector:
            if index is not None:
                elements = await page.query_selector_all(selector)
                if index < len(elements):
                    await elements[index].fill(text)
                else:
                    return {"success": False, "error": f"Índice {index} fora do range ({len(elements)} elementos)"}
            else:
                await page.fill(selector, text)
        else:
            await page.keyboard.type(text)
        return {"success": True}

    async def type_text(self, text: str, delay: Optional[float] = None) -> Dict:
        page = await self._page_atual()
        kwargs: Dict[str, Any] = {}
        if delay is not None:
            kwargs["delay"] = delay
        await page.keyboard.type(text, **kwargs)
        return {"success": True}

    async def press_key(self, key: str) -> Dict:
        page = await self._page_atual()
        await page.keyboard.press(key)
        return {"success": True}

    async def hot_key(self, keys: List[str]) -> Dict:
        page = await self._page_atual()
        key_map = {"ctrl": "Control", "alt": "Alt", "shift": "Shift", "meta": "Meta", "cmd": "Meta"}
        normalized = [key_map.get(k.lower(), k) for k in keys]
        combo = "+".join(normalized)
        await page.keyboard.press(combo)
        return {"success": True, "combo": combo}

    async def scroll(self, direction: str = "down", amount: int = 3) -> Dict:
        page = await self._page_atual()
        delta = amount * 150
        if direction == "down":
            await page.mouse.wheel(0, delta)
        elif direction == "up":
            await page.mouse.wheel(0, -delta)
        elif direction == "right":
            await page.mouse.wheel(delta, 0)
        elif direction == "left":
            await page.mouse.wheel(-delta, 0)
        return {"success": True, "direction": direction, "amount": amount}

    async def scroll_to_element(self, selector: str) -> Dict:
        page = await self._page_atual()
        element = await page.query_selector(selector)
        if element:
            await element.scroll_into_view_if_needed()
            return {"success": True}
        return {"success": False, "error": f"Elemento '{selector}' não encontrado"}

    async def hover(self, selector: Optional[str] = None, x: Optional[float] = None, y: Optional[float] = None) -> Dict:
        page = await self._page_atual()
        if x is not None and y is not None:
            await page.mouse.move(x, y)
        elif selector:
            await page.hover(selector)
        else:
            return {"success": False, "error": "Forneça selector ou coordenadas x,y"}
        return {"success": True}

    async def select_option(self, selector: str, value: Optional[str] = None,
                             label: Optional[str] = None, index: Optional[int] = None) -> Dict:
        page = await self._page_atual()
        if value is not None:
            await page.select_option(selector, value=value)
        elif label is not None:
            await page.select_option(selector, label=label)
        elif index is not None:
            await page.select_option(selector, index=index)
        else:
            return {"success": False, "error": "Forneça value, label ou index"}
        return {"success": True}

    async def check(self, selector: str) -> Dict:
        page = await self._page_atual()
        await page.check(selector)
        return {"success": True}

    async def uncheck(self, selector: str) -> Dict:
        page = await self._page_atual()
        await page.uncheck(selector)
        return {"success": True}

    async def upload_file(self, selector: str, files: List[str]) -> Dict:
        page = await self._page_atual()
        await page.set_input_files(selector, files)
        return {"success": True, "files": files}

    async def fill_form(self, items: List[Dict]) -> Dict:
        page = await self._page_atual()
        filled = 0
        for item in items:
            sel = item.get("selector")
            text = item.get("text", "")
            if sel:
                try:
                    await page.fill(sel, str(text))
                    filled += 1
                except Exception as e:
                    fluxi_log.warning("sandbox", "browser", "fill_form erro", extra={"selector": sel, "erro": str(e)})
        return {"success": True, "filled": filled, "total": len(items)}

    async def evaluate(self, js: str) -> Dict:
        page = await self._page_atual()
        result = await page.evaluate(js)
        return {"result": result}

    # ─── Extração de conteúdo ─────────────────────────────────────

    _INTERACTIVE_SEL = (
        "a[href]:not([href='']), button:not([disabled]), "
        "input:not([disabled]):not([type='hidden']), select:not([disabled]), "
        "textarea:not([disabled]), [role='button']:not([disabled]), [role='link'], "
        "[role='checkbox'], [role='radio'], [role='menuitem'], [role='tab'], "
        "[role='option'], [role='combobox'], [role='searchbox']"
    )

    async def get_page_state(self, max_content: int = 15000) -> Dict:
        page = await self._page_atual()
        title = await page.title()
        url = page.url
        data = await page.evaluate("""
            () => {
                const SEL = ["a[href]:not([href=''])","button:not([disabled])","input:not([disabled]):not([type='hidden'])","select:not([disabled])","textarea:not([disabled])","[role='button']:not([disabled])","[role='link']","[role='checkbox']","[role='radio']","[role='menuitem']","[role='tab']","[role='searchbox']","[role='combobox']","[role='option']"].join(',');
                function name(el){const al=el.getAttribute('aria-label');if(al&&al.trim())return al.trim();if(el.id){const l=document.querySelector('label[for="'+el.id+'"]');if(l&&l.textContent.trim())return l.textContent.trim();}if(el.placeholder&&el.placeholder.trim())return el.placeholder.trim();if(el.title&&el.title.trim())return el.title.trim();const inner=(el.innerText||'').trim();if(inner)return inner;if(el.value&&el.tagName==='INPUT')return el.value.trim();return '';}
                function role(el){const r=el.getAttribute('role');if(r)return r;const t=el.tagName.toLowerCase(),tp=(el.type||'').toLowerCase();if(t==='a')return 'link';if(t==='button')return 'button';if(t==='select')return 'combobox';if(t==='textarea')return 'textbox';if(t==='input'){if(tp==='checkbox')return 'checkbox';if(tp==='radio')return 'radio';if(['submit','button','reset'].includes(tp))return 'button';return 'textbox';}return t;}
                const els=Array.from(document.querySelectorAll(SEL)).filter(el=>{const r=el.getBoundingClientRect();return r.width>0||r.height>0||el.type==='radio'||el.type==='checkbox';});
                const interactive=[],lines=[];
                els.forEach((el,i)=>{const n=name(el).slice(0,120);if(!n)return;const ro=role(el),val=(el.value||'').slice(0,80),chk=(el.type==='checkbox'||el.type==='radio')?el.checked:null,href=el.href||'';interactive.push({index:i,role:ro,name:n,value:val,checked:chk,href});const c=chk!==null?(chk?'[x]':'[ ]'):'',v=val&&!['link','button'].includes(ro)?" = '"+val+"'":'';lines.push('['+i+']<'+ro+'>'+c+' '+n+v);});
                const txt=[];document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h=>{const t=h.innerText.trim();if(t)txt.push('#'.repeat(parseInt(h.tagName[1]))+' '+t);});
                const main=document.querySelector('main')||document.querySelector('[role="main"]')||document.querySelector('article')||document.body;
                if(main){const w=document.createTreeWalker(main,NodeFilter.SHOW_TEXT);const seen=new Set();let n;while((n=w.nextNode())&&txt.join('').length<15000){const t=n.textContent.trim(),p=n.parentElement&&n.parentElement.tagName;if(t.length>10&&!seen.has(t)&&p!=='SCRIPT'&&p!=='STYLE'&&p!=='NOSCRIPT'&&p!=='NAV'&&p!=='FOOTER'){seen.add(t);txt.push(t);}}}
                return {interactive,interactive_lines:lines.join('\\n'),page_text:txt.join('\\n')};
            }
        """)
        interactive = data.get("interactive", [])
        il = data.get("interactive_lines", "")
        pt = data.get("page_text", "")
        combined = []
        if il:
            combined.append("=== Elementos interativos ===\n" + il)
        if pt:
            combined.append("\n=== Conteúdo da página ===\n" + pt)
        content = "\n".join(combined)
        if not content.strip():
            content = await page.evaluate("document.body ? document.body.innerText.slice(0,15000) : ''")
        return {
            "url": url,
            "title": title,
            "content": content[:max_content],
        }

    async def click_index(self, index: int) -> Dict:
        page = await self._page_atual()
        result = await page.evaluate("""
            (index) => {
                const sel=["a[href]:not([href=''])","button:not([disabled])","input:not([disabled]):not([type='hidden'])","select:not([disabled])","textarea:not([disabled])","[role='button']:not([disabled])","[role='link']","[role='checkbox']","[role='radio']","[role='menuitem']","[role='tab']","[role='option']"].join(',');
                const els=Array.from(document.querySelectorAll(sel)).filter(el=>el.offsetParent!==null||el.type==='radio'||el.type==='checkbox');
                if(index>=els.length)return{success:false,error:'Índice '+index+' fora do range ('+els.length+' elementos)'};
                const el=els[index];el.scrollIntoView({behavior:'instant',block:'center'});el.click();
                return{success:true,tag:el.tagName.toLowerCase(),text:(el.innerText||el.value||el.getAttribute('aria-label')||'').trim().slice(0,80),href:el.href||''};
            }
        """, index)
        return result

    async def get_text(self) -> Dict:
        page = await self._page_atual()
        text = await page.evaluate("document.body ? document.body.innerText : ''")
        title = await page.title()
        return {"text": text[:8000], "title": title, "url": page.url}

    async def get_html(self, outer: bool = False) -> Dict:
        page = await self._page_atual()
        html = await page.evaluate("document.documentElement.outerHTML") if outer else await page.content()
        return {"html": html, "title": await page.title(), "url": page.url}

    async def get_markdown(self) -> Dict:
        page = await self._page_atual()
        title = await page.title()
        url = page.url
        try:
            await page.add_script_tag(url="https://cdn.jsdelivr.net/npm/@mozilla/readability@0.5.0/Readability.min.js")
            result = await page.evaluate("""
                () => {
                    try{const doc=document.cloneNode(true);const r=new Readability(doc);const a=r.parse();if(a&&a.textContent&&a.textContent.length>100)return{ok:true,title:a.title,text:a.textContent,excerpt:a.excerpt};}catch(e){}
                    return{ok:false};
                }
            """)
            if result.get("ok"):
                at = result.get("title") or title
                md = f"# {at}\n\nURL: {url}\n"
                if result.get("excerpt"):
                    md += f"\n> {result['excerpt']}\n"
                md += f"\n{result.get('text','').strip()}"
                return {"markdown": md[:12000], "title": at, "url": url, "method": "readability"}
        except Exception:
            pass
        text = await page.evaluate("document.body ? document.body.innerText : ''")
        return {"markdown": f"# {title}\n\n{text[:8000]}", "title": title, "url": url, "method": "innertext"}

    async def get_elements(self, selector: Optional[str] = None) -> Dict:
        page = await self._page_atual()
        sel = selector or self._INTERACTIVE_SEL
        elements = await page.evaluate(f"""
            () => {{
                return Array.from(document.querySelectorAll({json.dumps(sel)})).slice(0,100).map((el,i) => ({{
                    index: i,
                    tag: el.tagName.toLowerCase(),
                    text: (el.innerText || el.value || '').trim().slice(0, 100),
                    href: el.href || '',
                    id: el.id || '',
                    class: el.className || '',
                }}));
            }}
        """)
        return {"elements": elements, "count": len(elements)}

    # ─── Tabs ─────────────────────────────────────────────────────

    async def tabs_list(self) -> Dict:
        await self._ensure_connected()
        pages = self._context.pages if self._context else []
        tabs = []
        for i, p in enumerate(pages):
            tabs.append({"index": i, "url": p.url, "title": await p.title()})
        return {"tabs": tabs, "active": len(pages) - 1}

    async def tabs_new(self, url: Optional[str] = None) -> Dict:
        await self._ensure_connected()
        assert self._context
        page = await self._context.new_page()
        self._page = page
        if url:
            await page.goto(url)
        return {"success": True, "url": page.url, "index": len(self._context.pages) - 1}

    async def tabs_close(self, index: int = 0) -> Dict:
        await self._ensure_connected()
        assert self._context
        pages = self._context.pages
        if index < len(pages):
            await pages[index].close()
            remaining = self._context.pages
            self._page = remaining[-1] if remaining else None
            return {"success": True}
        return {"success": False, "error": f"Tab {index} não existe"}

    async def tabs_switch(self, index: int) -> Dict:
        await self._ensure_connected()
        assert self._context
        pages = self._context.pages
        if index < len(pages):
            self._page = pages[index]
            return {"success": True, "url": self._page.url}
        return {"success": False, "error": f"Tab {index} não existe"}

    # ─── Cookies ─────────────────────────────────────────────────

    async def cookies_get(self, url: Optional[str] = None) -> Dict:
        await self._ensure_connected()
        assert self._context
        cookies = await self._context.cookies(url) if url else await self._context.cookies()
        return {"cookies": cookies}

    async def cookies_set(self, cookies: List[Dict]) -> Dict:
        await self._ensure_connected()
        assert self._context
        await self._context.add_cookies(cookies)
        return {"success": True}

    async def cookies_clear(self) -> Dict:
        await self._ensure_connected()
        assert self._context
        await self._context.clear_cookies()
        return {"success": True}


async def _safe_close(inst: InternalBrowserService):
    try:
        await inst.desconectar()
    except Exception:
        pass
