"""
Captura screenshots das telas principais do Fluxi em fluxo guiado.

Roteiro:
  1. /signup?bootstrap=1 — primeira tela (vazia)
  2. Mesma tela com formulário preenchido (antes do submit)
  3. /  — dashboard após signup
  4. /sessoes/ — lista (vazia)
  5. /sessoes/nova — opção WhatsApp default
  6. /sessoes/nova — opção Telegram com campo bot_token
  7. /sessoes/nova — opção Web Chat com hint
  8. /sessoes/ — lista com sessão criada (Web Chat)
  9. /sessoes/{id}/detalhes — painel da sessão
 10. /agentes/{id} — painel do agente
 11. /skills, /ferramentas, /rags, /mcp, /provedores-llm, /configuracoes
 12. /chat/{id} — Web Chat público (anônimo)

Roda dentro do container Docker:
    docker exec whatsapp-ai-agent-fluxi-fluxi-1 python /tmp/screenshot_telas.py
Depois:
    docker cp whatsapp-ai-agent-fluxi-fluxi-1:/tmp/screenshots ./data/
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

BASE = os.getenv("FLUXI_URL", "http://localhost:8000")
OUT_DIR = Path("/tmp/screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)

USER_EMAIL = "demo@fluxi.example.com"
USER_NOME = "Demo Admin"
USER_SENHA = "FluxiDemo2026"

VIEWPORT = {"width": 1440, "height": 900}


async def shot(page: Page, nome: str) -> None:
    """Tira screenshot e loga."""
    caminho = OUT_DIR / nome
    await page.screenshot(path=str(caminho), full_page=False)
    print(f"  ✓ {nome}")


async def submit_form(page: Page, action_substring: str | None = None) -> None:
    """Submete o form principal da página. Se `action_substring` for dado,
    procura o form cujo `action` contém esse substring — necessário porque o
    layout autenticado tem um form pequeno de /logout no header.
    """
    if action_substring:
        # Mantemos o JS simples e injetamos o substring via JSON-encode pra
        # evitar problemas de escape de aspas.
        import json as _json
        alvo = _json.dumps(action_substring)
        js = f"""
            const alvo = {alvo};
            const f = [...document.forms].find(f =>
                (f.getAttribute('action') || '').includes(alvo));
            if (!f) throw new Error('form alvo nao encontrado: ' + alvo);
            f.submit();
        """
    else:
        # Pega o form de maior área visível — heurística que evita o logout do header
        js = """
            const fs = [...document.forms].filter(f => f.offsetWidth > 0 && f.offsetHeight > 0);
            const maior = fs.reduce((a, b) =>
                (a.getBoundingClientRect().width * a.getBoundingClientRect().height >
                 b.getBoundingClientRect().width * b.getBoundingClientRect().height) ? a : b);
            maior.submit();
        """
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=15_000):
        await page.evaluate(js)


async def goto(page: Page, rota: str, *, wait: str = "networkidle") -> None:
    try:
        await page.goto(f"{BASE}{rota}", wait_until=wait, timeout=15_000)
    except Exception as e:
        print(f"     [warn] goto {rota}: {e}")
    await page.wait_for_timeout(500)


# =========================================================================
# Etapas do tour
# =========================================================================

async def etapa_signup_admin(page: Page) -> None:
    """1) /signup vazio → 2) preenchido → 3) submit → / (dashboard)"""
    print("\n[1/n] Signup admin")
    await goto(page, "/signup?bootstrap=1", wait="domcontentloaded")
    await page.wait_for_timeout(400)
    await shot(page, "01_signup_vazio.png")

    # Preenche o form sem submeter — pra capturar estado "pronto pra enviar"
    await page.fill('input[name="nome"]', USER_NOME)
    await page.fill('input[name="email"]', USER_EMAIL)
    await page.fill('input[name="senha"]', USER_SENHA)
    await page.fill('input[name="senha_confirmar"]', USER_SENHA)
    # Dispara o oninput pra atualizar o medidor de força
    await page.evaluate("document.querySelector('input[name=\\'senha\\']').dispatchEvent(new Event('input'))")
    await page.evaluate("document.querySelector('input[name=\\'senha_confirmar\\']').dispatchEvent(new Event('input'))")
    await page.wait_for_timeout(300)
    await shot(page, "02_signup_preenchido.png")

    await submit_form(page, action_substring="/signup")
    print(f"     pós-signup url={page.url}")
    if "/signup" in page.url:
        # Pega texto de erro pra debug
        erro_url = page.url
        from urllib.parse import urlparse, parse_qs, unquote
        q = parse_qs(urlparse(erro_url).query)
        msg = unquote(q.get("erro", ["?"])[0])
        raise RuntimeError(f"Signup falhou. Mensagem: {msg}")
    await page.wait_for_timeout(800)
    await shot(page, "03_dashboard.png")


async def etapa_login(page: Page) -> None:
    """Mostra a tela de login (após admin existir, em sessão anônima)."""
    print("\n[*] Tela de login (sessão limpa)")
    ctx = page.context
    novo = await ctx.browser.new_context(viewport=VIEWPORT)
    pg = await novo.new_page()
    await goto(pg, "/login", wait="domcontentloaded")
    await pg.wait_for_timeout(300)
    await shot(pg, "04_login.png")
    await novo.close()


async def etapa_sessoes_lista_vazia(page: Page) -> None:
    print("\n[*] Lista de sessões (vazia)")
    await goto(page, "/sessoes/")
    await shot(page, "05_sessoes_vazia.png")


async def etapa_sessao_nova_whatsapp(page: Page) -> None:
    print("\n[*] Nova sessão — WhatsApp (default)")
    await goto(page, "/sessoes/nova")
    await page.wait_for_timeout(400)
    await shot(page, "06_sessao_nova_whatsapp.png")


async def etapa_sessao_nova_telegram(page: Page) -> None:
    print("\n[*] Nova sessão — Telegram (campo bot_token aparece)")
    # Já estamos em /sessoes/nova. Trocar select pra Telegram via JS.
    await page.evaluate("""
        const s = document.querySelector('select[name=\\'plataforma\\']');
        s.value = 'telegram';
        s.dispatchEvent(new Event('change'));
    """)
    await page.wait_for_timeout(400)
    await shot(page, "07_sessao_nova_telegram.png")


async def etapa_sessao_nova_webchat(page: Page) -> None:
    print("\n[*] Nova sessão — Web Chat (hint público)")
    await page.evaluate("""
        const s = document.querySelector('select[name=\\'plataforma\\']');
        s.value = 'webchat';
        s.dispatchEvent(new Event('change'));
        document.querySelector('input[name=\\'nome\\']').value = 'Chat do Site';
    """)
    await page.wait_for_timeout(400)
    await shot(page, "08_sessao_nova_webchat.png")


async def criar_sessao_webchat(page: Page) -> int:
    """Submete o form com plataforma=webchat e retorna o id da sessão criada."""
    print("\n[*] Criando sessão Web Chat de verdade")
    await goto(page, "/sessoes/nova")
    await page.fill('input[name="nome"]', "Chat do Site")
    await page.evaluate("""
        const s = document.querySelector('select[name=\\'plataforma\\']');
        s.value = 'webchat';
        s.dispatchEvent(new Event('change'));
    """)
    await submit_form(page, action_substring="/sessoes/criar")
    # Após criar, volta pra /sessoes/. Vamos pegar o ID via DB pra ser robusto.
    import sqlite3
    con = sqlite3.connect("/app/data/fluxi.db")
    row = con.execute(
        "SELECT id FROM sessoes WHERE plataforma='webchat' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    con.close()
    if not row:
        raise RuntimeError("Sessão Web Chat não foi criada")
    return int(row[0])


async def etapa_sessoes_lista_com_dados(page: Page) -> None:
    print("\n[*] Lista de sessões (com sessão criada)")
    await goto(page, "/sessoes/")
    await shot(page, "09_sessoes_lista.png")


async def etapa_sessao_detalhes(page: Page, sessao_id: int) -> None:
    print(f"\n[*] Detalhes da sessão {sessao_id}")
    await goto(page, f"/sessoes/{sessao_id}/detalhes")
    await page.wait_for_timeout(500)
    await shot(page, "10_sessao_detalhes.png")


async def etapa_agente(page: Page) -> None:
    print("\n[*] Painel do agente")
    # Pega o primeiro agente da sessão recém criada.
    import sqlite3
    con = sqlite3.connect("/app/data/fluxi.db")
    row = con.execute("SELECT id FROM agentes ORDER BY id LIMIT 1").fetchone()
    con.close()
    if not row:
        print("     (sem agente — pulando)")
        return
    await goto(page, f"/agentes/{row[0]}")
    await page.wait_for_timeout(600)
    await shot(page, "11_agente.png")


async def etapa_modulos_globais(page: Page) -> None:
    print("\n[*] Demais módulos do painel")
    mapa = [
        ("/skills", "12_skills.png"),
        ("/ferramentas", "13_ferramentas.png"),
        ("/rags", "14_rags.png"),
        ("/mcp", "15_mcp.png"),
        ("/provedores-llm", "16_provedores_llm.png"),
        ("/configuracoes", "17_configuracoes.png"),
    ]
    for rota, arq in mapa:
        await goto(page, rota)
        await page.wait_for_timeout(400)
        await shot(page, arq)


async def etapa_webchat_publico(ctx_anon: BrowserContext, sessao_id: int) -> None:
    print(f"\n[*] Web Chat público /chat/{sessao_id} (sessão anônima)")
    pg = await ctx_anon.new_page()
    # SSE mantém a conexão aberta — não esperar networkidle
    await pg.goto(f"{BASE}/chat/{sessao_id}", wait_until="load", timeout=15_000)
    await pg.wait_for_timeout(2000)
    await shot(pg, "18_webchat.png")
    await pg.close()


# =========================================================================
# main
# =========================================================================

async def main() -> None:
    print(f"Capturando telas de {BASE} → {OUT_DIR}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport=VIEWPORT)
        page = await ctx.new_page()

        await etapa_signup_admin(page)
        await etapa_login(page)
        await etapa_sessoes_lista_vazia(page)
        await etapa_sessao_nova_whatsapp(page)
        await etapa_sessao_nova_telegram(page)
        await etapa_sessao_nova_webchat(page)

        sessao_id = await criar_sessao_webchat(page)
        await etapa_sessoes_lista_com_dados(page)
        await etapa_sessao_detalhes(page, sessao_id)
        await etapa_agente(page)
        await etapa_modulos_globais(page)

        ctx_anon = await browser.new_context(viewport=VIEWPORT)
        try:
            await etapa_webchat_publico(ctx_anon, sessao_id)
        finally:
            await ctx_anon.close()

        await browser.close()
    print(f"\n✔ Pronto. {len(list(OUT_DIR.glob('*.png')))} screenshots em {OUT_DIR}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n✗ Erro: {type(e).__name__}: {e}")
        sys.exit(1)
