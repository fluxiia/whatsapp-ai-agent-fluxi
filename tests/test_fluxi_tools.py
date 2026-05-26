"""
Testa as 5 ferramentas fluxi_* via API interna (servidor deve estar rodando em :8000).
Cada teste chama POST /api/ferramentas/{id}/executar ou simula o código Python diretamente.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import httpx

BASE = "http://localhost:8000"
OK = "[OK]"
FAIL = "[FALHOU]"


def sep(titulo=""):
    print(f"\n{'='*60}")
    if titulo:
        print(f"  {titulo}")
        print("-" * 60)


def check(label, res, expect_key=None, expect_value=None):
    """Imprime resultado e retorna True se passou."""
    if isinstance(res, dict) and "erro" in res and not res.get("sucesso", True):
        print(f"{FAIL} {label}: {res}")
        return False
    if expect_key and expect_key not in str(res):
        print(f"{FAIL} {label}: chave '{expect_key}' não encontrada em {res}")
        return False
    print(f"{OK} {label}: {str(res)[:200]}")
    return True


def exec_tool(tool_id: int, argumentos: dict) -> dict:
    """Executa uma ferramenta CODE via endpoint interno."""
    # O endpoint de execução não existe publicamente — executamos o código Python
    # diretamente como o sistema faz internamente usando exec()
    r = httpx.get(f"{BASE}/api/ferramentas/{tool_id}", timeout=10)
    if r.status_code != 200:
        return {"erro": f"Ferramenta {tool_id} não encontrada"}
    tool = r.json()
    codigo = tool.get("codigo_python", "")
    if not codigo:
        return {"erro": "Sem código Python"}

    namespace = {
        "argumentos": argumentos,
        "resultado": None,
        "json": json,
        "__import__": __import__,
    }
    try:
        exec(codigo, namespace)
        return namespace.get("resultado", {"erro": "resultado não definido"})
    except Exception as e:
        return {"erro": str(e)}


def get_tool_id(nome: str) -> int | None:
    r = httpx.get(f"{BASE}/api/ferramentas/", timeout=10)
    for f in r.json():
        if f["nome"] == nome:
            return f["id"]
    return None


def main():
    erros = 0

    # ── Obter IDs ─────────────────────────────────────────────────────────
    sep("Obtendo IDs das ferramentas fluxi_*")
    ids = {}
    for nome in ["fluxi_ferramentas", "fluxi_skills", "fluxi_agentes", "fluxi_mcp", "fluxi_rag"]:
        fid = get_tool_id(nome)
        ids[nome] = fid
        if fid:
            print(f"{OK} {nome} ->ID {fid}")
        else:
            print(f"{FAIL} {nome} ->NÃO ENCONTRADA")
            erros += 1

    # ── fluxi_ferramentas ─────────────────────────────────────────────────
    sep("fluxi_ferramentas — listar")
    res = exec_tool(ids["fluxi_ferramentas"], {"acao": "listar"})
    if not check("listar", res, "ferramentas"): erros += 1
    else: print(f"   total: {res.get('total')}")

    # ── fluxi_skills ──────────────────────────────────────────────────────
    sep("fluxi_skills — listar")
    res = exec_tool(ids["fluxi_skills"], {"acao": "listar"})
    if not check("listar", res, "skills"): erros += 1
    else: print(f"   total: {res.get('total')}")

    # ── fluxi_agentes ─────────────────────────────────────────────────────
    sep("fluxi_agentes — listar")
    res = exec_tool(ids["fluxi_agentes"], {"acao": "listar"})
    if not check("listar", res, "agentes"): erros += 1
    else: print(f"   total: {res.get('total')}")

    # ── fluxi_mcp ─────────────────────────────────────────────────────────
    sep("fluxi_mcp — listar_presets")
    res = exec_tool(ids["fluxi_mcp"], {"acao": "listar_presets"})
    if not check("listar_presets", res, "presets"): erros += 1
    else: print(f"   total presets: {res.get('total')}")

    # ── fluxi_rag — listar ────────────────────────────────────────────────
    sep("fluxi_rag — listar")
    res = exec_tool(ids["fluxi_rag"], {"acao": "listar"})
    if not check("listar", res, "rags"): erros += 1
    else: print(f"   total RAGs: {res.get('total')}")

    # ── fluxi_rag — criar ─────────────────────────────────────────────────
    sep("fluxi_rag — criar")
    res = exec_tool(ids["fluxi_rag"], {
        "acao": "criar",
        "nome": "RAG Teste Automatico",
        "descricao": "Criado pelo script de teste — pode deletar"
    })
    if not check("criar", res, "sucesso"): erros += 1

    rag_id = res.get("id") if res.get("sucesso") else None

    if rag_id:
        # ── fluxi_rag — adicionar_texto ───────────────────────────────────
        sep(f"fluxi_rag — adicionar_texto (RAG {rag_id})")
        res = exec_tool(ids["fluxi_rag"], {
            "acao": "adicionar_texto",
            "rag_id": rag_id,
            "titulo": "Chunk de teste",
            "texto": (
                "Este é um texto de teste para verificar se o RAG está funcionando. "
                "O sistema deve dividir este texto em chunks e indexá-los corretamente. "
                "Quanto mais texto, mais chunks serão criados pelo processo de chunking."
            )
        })
        if not check("adicionar_texto", res, "chunks_criados"): erros += 1
        else: print(f"   chunks criados: {res.get('chunks_criados')}")

        # ── fluxi_rag — obter ─────────────────────────────────────────────
        sep(f"fluxi_rag — obter (RAG {rag_id})")
        res = exec_tool(ids["fluxi_rag"], {"acao": "obter", "rag_id": rag_id})
        if not check("obter", res, "rag"): erros += 1

        # ── fluxi_rag — resetar ───────────────────────────────────────────
        sep(f"fluxi_rag — resetar (RAG {rag_id})")
        res = exec_tool(ids["fluxi_rag"], {"acao": "resetar", "rag_id": rag_id})
        if not check("resetar", res, "sucesso"): erros += 1

        # ── fluxi_rag — deletar (limpeza) ─────────────────────────────────
        sep(f"fluxi_rag — deletar (RAG {rag_id})")
        res = exec_tool(ids["fluxi_rag"], {"acao": "deletar", "rag_id": rag_id})
        if not check("deletar", res): erros += 1

    # ── Resultado final ───────────────────────────────────────────────────
    sep()
    if erros == 0:
        print(f"{OK} TODOS OS TESTES PASSARAM")
    else:
        print(f"{FAIL} {erros} TESTE(S) FALHARAM")
    return erros


if __name__ == "__main__":
    sys.exit(main())
