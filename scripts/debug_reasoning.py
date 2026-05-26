#!/usr/bin/env python3
"""
Debug script para auditar respostas RAW da OpenRouter.
Faz uma chamada direta à API e dumpa o JSON completo para análise.

Uso:
    python scripts/debug_reasoning.py
    python scripts/debug_reasoning.py --model google/gemini-3.1-flash-lite-preview
    python scripts/debug_reasoning.py --no-tools
    python scripts/debug_reasoning.py --effort medium
"""
import asyncio
import json
import sys
import os
import argparse
from datetime import datetime

# Adicionar o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    parser = argparse.ArgumentParser(description="Debug OpenRouter reasoning responses")
    parser.add_argument("--model", default="google/gemini-3.1-flash-lite-preview",
                        help="Model to test")
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high"],
                        help="Reasoning effort level")
    parser.add_argument("--no-tools", action="store_true",
                        help="Send without tools")
    parser.add_argument("--no-reasoning", action="store_true",
                        help="Send without reasoning parameter (baseline)")
    parser.add_argument("--prompt", default="Crie um plano detalhado para implementar um dashboard de vendas com HTML, CSS e JavaScript. Pense passo a passo antes de responder.",
                        help="Test prompt")
    parser.add_argument("--output", default=None,
                        help="Save full response to file")
    args = parser.parse_args()

    # Pegar API key do .env ou banco
    import httpx
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        # Tentar ler do banco SQLite
        try:
            import sqlite3
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fluxi.db")
            if not os.path.exists(db_path):
                db_path = "/app/data/fluxi.db"
            if not os.path.exists(db_path):
                db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "fluxi.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT valor FROM configuracoes WHERE chave = 'openrouter_api_key'")
            row = cursor.fetchone()
            if row:
                api_key = row[0]
            conn.close()
        except Exception as e:
            print(f"[ERRO] Não conseguiu ler API key: {e}")

    if not api_key:
        print("[ERRO] OPENROUTER_API_KEY não encontrada. Defina via env ou banco.")
        sys.exit(1)

    print(f"{'='*80}")
    print(f"  DEBUG OPENROUTER REASONING")
    print(f"  Modelo: {args.model}")
    print(f"  Effort: {args.effort}")
    print(f"  Tools:  {'NÃO' if args.no_tools else 'SIM (2 tools de exemplo)'}")
    print(f"  Reasoning param: {'NÃO' if args.no_reasoning else 'SIM'}")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    print(f"{'='*80}")

    messages = [
        {"role": "system", "content": "Você é um assistente de programação. Pense cuidadosamente antes de responder."},
        {"role": "user", "content": args.prompt},
    ]

    payload = {
        "model": args.model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4000,
    }

    if not args.no_reasoning:
        payload["reasoning"] = {"effort": args.effort}

    if not args.no_tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "file_write",
                    "description": "Escreve conteúdo em um arquivo",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "think",
                    "description": "Ferramenta para pensar e planejar",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "thought": {"type": "string"},
                        },
                        "required": ["thought"],
                    },
                },
            },
        ]

    print(f"\n[REQUEST] Payload keys: {list(payload.keys())}")
    if "reasoning" in payload:
        print(f"[REQUEST] reasoning = {json.dumps(payload['reasoning'])}")
    print(f"[REQUEST] Enviando...")

    async with httpx.AsyncClient() as client:
        t0 = datetime.now()
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://fluxi.ai",
                "X-Title": "Fluxi Debug Script",
            },
            json=payload,
            timeout=180.0,
        )
        elapsed = (datetime.now() - t0).total_seconds()

    print(f"\n[RESPONSE] Status: {response.status_code} ({elapsed:.1f}s)")

    if response.status_code != 200:
        print(f"[ERRO] {response.text}")
        sys.exit(1)

    data = response.json()

    # Salvar JSON completo se pedido
    output_path = args.output or f"debug_reasoning_{datetime.now().strftime('%H%M%S')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[SALVO] JSON completo em: {output_path}")

    # ── Análise detalhada ──
    print(f"\n{'='*80}")
    print(f"  ANÁLISE DA RESPOSTA")
    print(f"{'='*80}")

    # Top-level keys
    print(f"\n[TOP-LEVEL] keys: {list(data.keys())}")

    # Usage
    usage = data.get("usage", {})
    print(f"\n[TOKENS]")
    print(f"  prompt_tokens:     {usage.get('prompt_tokens', '?')}")
    print(f"  completion_tokens: {usage.get('completion_tokens', '?')}")
    print(f"  total_tokens:      {usage.get('total_tokens', '?')}")
    # Reasoning tokens específicos (se existirem)
    for k, v in usage.items():
        if "reason" in k.lower() or "think" in k.lower():
            print(f"  {k}: {v}")

    # Choices
    choices = data.get("choices", [])
    print(f"\n[CHOICES] count: {len(choices)}")

    for i, choice in enumerate(choices):
        print(f"\n  --- Choice {i} ---")
        print(f"  finish_reason: {choice.get('finish_reason')}")
        print(f"  index: {choice.get('index')}")

        # Choice-level keys
        print(f"  keys: {list(choice.keys())}")

        message = choice.get("message", {})
        print(f"\n  [MESSAGE] keys: {list(message.keys())}")
        print(f"  role: {message.get('role')}")

        # Content
        content = message.get("content", "")
        if content:
            print(f"  content: {len(content)} chars")
            print(f"  content_preview: {repr(content[:300])}")
        else:
            print(f"  content: VAZIO/NULL ({repr(content)})")

        # Tool calls
        tool_calls = message.get("tool_calls")
        if tool_calls:
            print(f"\n  [TOOL_CALLS] count: {len(tool_calls)}")
            for j, tc in enumerate(tool_calls):
                fn = tc.get("function", {})
                fn_args = fn.get("arguments", "")
                print(f"    [{j}] {fn.get('name')} | id={tc.get('id')} | args={len(fn_args)} chars")
                if len(fn_args) < 500:
                    print(f"         args_preview: {fn_args[:300]}")

        # ── REASONING (o ponto crítico) ──
        print(f"\n  [REASONING ANALYSIS]")

        # Verificar TODAS as chaves que podem conter reasoning
        reasoning_keys = [k for k in message.keys()
                          if any(x in k.lower() for x in ["reason", "think", "thought"])]
        print(f"  reasoning-related keys in message: {reasoning_keys}")

        # Checar campo 'reasoning' (string)
        reasoning_str = message.get("reasoning")
        if reasoning_str is not None:
            print(f"  message.reasoning: type={type(reasoning_str).__name__}, len={len(reasoning_str) if isinstance(reasoning_str, str) else '?'}")
            if isinstance(reasoning_str, str) and reasoning_str:
                print(f"  reasoning_preview: {repr(reasoning_str[:500])}")
            elif reasoning_str == "":
                print(f"  reasoning: STRING VAZIA")
            else:
                print(f"  reasoning: {repr(reasoning_str)}")
        else:
            print(f"  message.reasoning: NÃO EXISTE")

        # Checar campo 'reasoning_details' (array)
        reasoning_details = message.get("reasoning_details")
        if reasoning_details is not None:
            print(f"  message.reasoning_details: type={type(reasoning_details).__name__}")
            if isinstance(reasoning_details, list):
                print(f"  reasoning_details count: {len(reasoning_details)}")
                for k, detail in enumerate(reasoning_details):
                    print(f"    [{k}] type={type(detail).__name__}")
                    if isinstance(detail, dict):
                        print(f"         keys: {list(detail.keys())}")
                        print(f"         type_field: {detail.get('type', '?')}")
                        content_field = detail.get("content", "")
                        print(f"         content: type={type(content_field).__name__}, len={len(content_field) if isinstance(content_field, str) else '?'}")
                        if content_field:
                            print(f"         content_preview: {repr(content_field[:300])}")
                        else:
                            print(f"         content: VAZIO ({repr(content_field)})")
                    elif isinstance(detail, str):
                        print(f"         string: {repr(detail[:300])}")
                    else:
                        print(f"         raw: {repr(detail)}")
            else:
                print(f"  reasoning_details raw: {repr(reasoning_details)}")
        else:
            print(f"  message.reasoning_details: NÃO EXISTE")

        # Checar choice-level reasoning (alguns providers botam fora do message)
        choice_reasoning_keys = [k for k in choice.keys()
                                  if any(x in k.lower() for x in ["reason", "think"])]
        if choice_reasoning_keys:
            print(f"\n  [CHOICE-LEVEL] reasoning keys: {choice_reasoning_keys}")
            for k in choice_reasoning_keys:
                v = choice[k]
                print(f"    {k}: type={type(v).__name__}, preview={repr(str(v)[:200])}")

    # Top-level reasoning (raro mas possível)
    top_reasoning = [k for k in data.keys() if "reason" in k.lower()]
    if top_reasoning:
        print(f"\n[TOP-LEVEL REASONING] keys: {top_reasoning}")
        for k in top_reasoning:
            print(f"  {k}: {repr(str(data[k])[:200])}")

    # ── Diagnóstico final ──
    print(f"\n{'='*80}")
    print(f"  DIAGNÓSTICO")
    print(f"{'='*80}")

    has_reasoning = bool(reasoning_str)
    has_details = bool(reasoning_details and any(
        (d.get("content", "") if isinstance(d, dict) else str(d))
        for d in (reasoning_details if isinstance(reasoning_details, list) else [])
    ))

    if has_reasoning and has_details:
        print(f"  ✅ REASONING FUNCIONA: tanto 'reasoning' quanto 'reasoning_details' têm conteúdo")
    elif has_reasoning:
        print(f"  ✅ REASONING FUNCIONA: campo 'reasoning' tem conteúdo ({len(reasoning_str)} chars)")
        if reasoning_details is not None:
            print(f"  ⚠️  'reasoning_details' existe mas sem conteúdo útil — BUG no código antigo!")
    elif has_details:
        print(f"  ✅ REASONING FUNCIONA: campo 'reasoning_details' tem conteúdo")
    else:
        print(f"  ❌ SEM REASONING: nenhum campo de reasoning com conteúdo")
        if reasoning_str is not None or reasoning_details is not None:
            print(f"  ⚠️  Campos existem mas vazios — modelo pode não suportar reasoning")
        else:
            print(f"  ⚠️  Campos nem existem na resposta — verificar se modelo suporta reasoning")

    print(f"\n  Modelo retornado: {data.get('model', '?')}")
    print(f"  Tempo resposta: {elapsed:.1f}s")
    print(f"  JSON completo salvo em: {output_path}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
