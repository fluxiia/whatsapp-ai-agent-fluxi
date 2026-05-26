import asyncio
from playwright.async_api import async_playwright

async def capture_chat():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Criamos um contexto
        context = await browser.new_context(viewport={'width': 1280, 'height': 1024})
        page = await context.new_page()
        
        print("Acessando a interface de chat...")
        try:
            # Acessa a URL local
            await page.goto("http://localhost:8000/coding/chat/1", wait_until="networkidle")
            # Espera um pouco para o JS carregar as tasks e mensagens
            await asyncio.sleep(5)
            
            # Tira screenshot
            await page.screenshot(path="debug_chat_ui.png", full_page=True)
            print("Screenshot salvo em debug_chat_ui.png")
            
            # Captura logs do console do navegador para ver se há erros de JS
            # (Poderíamos configurar isso com page.on("console"), mas vamos olhar o HTML por enquanto)
            content = await page.content()
            with open("debug_chat_dom.html", "w", encoding="utf-8") as f:
                f.write(content)
                
        except Exception as e:
            print(f"Erro ao acessar interface: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(capture_chat())
