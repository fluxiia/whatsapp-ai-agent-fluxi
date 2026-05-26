"""
Debug: por que o coding agent trava após "Chamando LLM iter=1"?

Uso: docker-compose exec fluxi python debug_coding.py
"""
import asyncio
import time
import sys
import traceback

# Importar da mesma forma que main.py para garantir todos os models registrados
from dotenv import load_dotenv
load_dotenv()

import logging_config  # noqa
from database import criar_tabelas, SessionLocal

# TODOS os models — ordem importa para SQLAlchemy relationships
import config.config_model               # noqa
import sessao.sessao_model               # noqa
import sessao.sessao_comando_model       # noqa
import sessao.sessao_tipo_mensagem_model # noqa
import ferramenta.ferramenta_model       # noqa
import ferramenta.ferramenta_variavel_model  # noqa
import llm_providers.llm_providers_model # noqa
import mcp_client.mcp_client_model       # noqa
import mcp_client.mcp_tool_model         # noqa
import rag.rag_model                     # noqa
import rag.rag_metrica_model             # noqa
import mensagem.mensagem_model           # noqa
import agente.agente_model               # noqa
import skill.skill_model                 # noqa
import coding_agent.coding_model         # noqa
import log.log_model                     # noqa

criar_tabelas()
db = SessionLocal()


def ok(msg):  print(f"  ✅ {msg}")
def fail(msg): print(f"  ❌ {msg}")
def info(msg): print(f"  ℹ️  {msg}")
def section(t): print(f"\n{'='*60}\n  {t}\n{'='*60}")


# ══════════════════════════════════════════════════════════════
section("TESTE 1: API Key")
from config.config_service import ConfiguracaoService
val = ConfiguracaoService.obter_valor(db, "openrouter_api_key")
if val:
    ok(f"API key: {val[:8]}...{val[-4:]}")
else:
    fail("Sem API key!")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
section("TESTE 2: LLM simples")
from llm_providers.llm_integration_service import LLMIntegrationService

async def _t2():
    t0 = time.time()
    r = await asyncio.wait_for(
        LLMIntegrationService.processar_mensagem_com_llm(
            db=db,
            messages=[{"role": "user", "content": "Diga: ok"}],
            modelo="openai/gpt-4o-mini",
            max_tokens=10,
        ),
        timeout=30.0,
    )
    return r, int((time.time()-t0)*1000)

try:
    r, ms = asyncio.run(_t2())
    ok(f"'{r.get('conteudo','')}' em {ms}ms")
except Exception as e:
    fail(f"{e}")
    traceback.print_exc()


# ══════════════════════════════════════════════════════════════
section("TESTE 3: LLM com 30 tools")
from coding_agent.coding_tools import obter_coding_tools
tools = obter_coding_tools(active_skills=["browser"])
info(f"{len(tools)} tools")

async def _t3():
    t0 = time.time()
    r = await asyncio.wait_for(
        LLMIntegrationService.processar_mensagem_com_llm(
            db=db,
            messages=[
                {"role": "system", "content": "Responda brevemente."},
                {"role": "user", "content": "tudo bem?"},
            ],
            modelo="openai/gpt-4o-mini",
            max_tokens=4096,
            tools=tools,
        ),
        timeout=60.0,
    )
    return r, int((time.time()-t0)*1000)

try:
    r, ms = asyncio.run(_t3())
    ok(f"'{r.get('conteudo','')[:80]}' em {ms}ms, finish={r.get('finish_reason')}")
except Exception as e:
    fail(f"{e}")
    traceback.print_exc()


# ══════════════════════════════════════════════════════════════
section("TESTE 4: Estado da Task 18")
from coding_agent.coding_model import CodingSession, CodingTask

tasks = db.query(CodingTask).order_by(CodingTask.id.desc()).limit(5).all()
for t in tasks:
    msgs = t.get_messages()
    info(f"Task {t.id}: status={t.status} iter={t.iteracoes} msgs={len(msgs)} "
         f"titulo='{t.titulo[:40]}' err={t.error}")

cs = db.query(CodingSession).filter(CodingSession.ativa == True).first()
if cs:
    info(f"CodingSession {cs.id}: agente={cs.agente_id}, modelo={cs.modelo_coding}, "
         f"max_iter={cs.max_iteracoes}")
else:
    fail("Sem CodingSession ativa!")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
section("TESTE 5: CodingService.processar_mensagem (DIRETO)")
from coding_agent.coding_service import CodingService

async def _t5():
    tdb = SessionLocal()
    try:
        t0 = time.time()
        print(f"    [0ms] Chamando processar_mensagem...")
        r = await asyncio.wait_for(
            CodingService.processar_mensagem(
                db=tdb,
                coding_session_id=cs.id,
                mensagem="Diga apenas: debug ok",
                telefone_cliente=None,
                task_id=None,
            ),
            timeout=120.0,
        )
        ms = int((time.time()-t0)*1000)
        print(f"    [{ms}ms] Retornou!")
        return r, ms
    finally:
        tdb.close()

try:
    r, ms = asyncio.run(_t5())
    ok(f"Completou em {ms}ms!")
    ok(f"  status={r.get('status')}, resposta='{str(r.get('resposta',''))[:100]}'")
    ok(f"  task_id={r.get('task_id')}, iter={r.get('iteracoes')}")
    if r.get('erro'):
        fail(f"  erro: {r.get('erro')}")
except asyncio.TimeoutError:
    fail("TIMEOUT 120s — processar_mensagem travou!")
except Exception as e:
    fail(f"{e}")
    traceback.print_exc()


# ══════════════════════════════════════════════════════════════
section("TESTE 6: Background task com create_task")

async def _t6():
    tdb = SessionLocal()
    resultado = {}
    _refs = set()

    async def _bg():
        r = await CodingService.processar_mensagem(
            db=tdb,
            coding_session_id=cs.id,
            mensagem="Diga apenas: background ok",
            telefone_cliente=None,
            task_id=None,
        )
        resultado.update(r)

    t0 = time.time()
    task = asyncio.create_task(_bg())
    _refs.add(task)

    erros = {}
    def _done(t):
        _refs.discard(t)
        exc = t.exception() if not t.cancelled() else None
        if exc:
            erros["exc"] = f"{type(exc).__name__}: {exc}"

    task.add_done_callback(_done)

    print(f"    Aguardando background task...")
    try:
        await asyncio.wait_for(task, timeout=120.0)
    except asyncio.TimeoutError:
        fail("TIMEOUT 120s na background task!")
        tdb.close()
        return

    ms = int((time.time()-t0)*1000)
    tdb.close()

    if erros:
        fail(f"Erro: {erros}")
    else:
        ok(f"Background completou em {ms}ms!")
        ok(f"  status={resultado.get('status')}, resposta='{str(resultado.get('resposta',''))[:100]}'")

try:
    asyncio.run(_t6())
except Exception as e:
    fail(f"{e}")
    traceback.print_exc()


# ══════════════════════════════════════════════════════════════
section("RESULTADO")
print("""
  TESTE 2 falhou → Sem conexão com OpenRouter
  TESTE 3 falhou → Problema com payload de tools
  TESTE 5 falhou → Bug no CodingService (DB, task, historico)
  TESTE 5 ok, TESTE 6 falhou → Bug no create_task/background
  TODOS ok → Bug só aparece com event loop do neonize/WhatsApp
""")
db.close()
print("Done.")
