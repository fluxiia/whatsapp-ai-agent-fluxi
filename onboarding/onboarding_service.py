"""
Servicos do onboarding guiado.

Concentra logica fora do router:
- deteccao de provedores LLM locais (LM Studio, Ollama)
- teste rapido de conexao de provedor
- templates de agente prontos (papel, objetivo, politicas, etc)
- helpers de estado do wizard (vive em request.session['onboarding'])
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from llm_providers.llm_providers_model import ProvedorLLM
from sessao.sessao_model import Sessao

logger = logging.getLogger(__name__)


# Provedores locais que tentamos auto-detectar.
PROVEDORES_LOCAIS = [
    {
        "nome": "LM Studio",
        "tipo": "lm_studio",
        "base_url": "http://localhost:1234/v1",
        "descricao": "Servidor local OpenAI-compativel (LM Studio).",
        "icone": "fa-microchip",
    },
    {
        "nome": "Ollama",
        "tipo": "ollama",
        "base_url": "http://localhost:11434/v1",
        "descricao": "Servidor local Ollama (modo OpenAI).",
        "icone": "fa-cube",
    },
]


# Provedor cloud (OpenRouter). Configurado por API key.
PROVEDOR_OPENROUTER = {
    "nome": "OpenRouter",
    "tipo": "openrouter",
    "base_url": "https://openrouter.ai/api/v1",
    "descricao": "Acesso a centenas de modelos pagos (GPT, Claude, Gemini, Llama, etc).",
    "icone": "fa-cloud",
}


# Templates de agente. Cada um pre-preenche os 7 campos do system prompt
# com texto editavel. Codigo "01" e usado em todos pq cada sessao tem
# seu proprio namespace de codigos.
TEMPLATES_AGENTE: List[Dict[str, str]] = [
    {
        "id": "atendente",
        "nome": "Atendente Comercial",
        "descricao": "Recebe leads, qualifica, agenda contato. Bom para vendas e pre-venda.",
        "icone": "fa-handshake",
        "cor": "var(--color-success)",
        "agente_papel": (
            "Voce e um atendente comercial atencioso e proativo. Recebe contatos novos, "
            "qualifica interesse, esclarece duvidas iniciais e encaminha proximos passos."
        ),
        "agente_objetivo": (
            "Converter contatos em conversas qualificadas, coletando nome, interesse e "
            "melhor horario para retorno."
        ),
        "agente_politicas": (
            "Sempre cumprimente pelo primeiro nome quando possivel. Nao prometa precos "
            "ou prazos sem confirmacao. Nao seja insistente. Encaminhe para humano se "
            "o cliente pedir."
        ),
        "agente_tarefa": (
            "Conversar com leads, entender necessidade, coletar dados essenciais "
            "(nome, contato, interesse) e marcar proximo passo."
        ),
        "agente_objetivo_explicito": "Qualificar leads e marcar retorno comercial.",
        "agente_publico": "Pessoas interessadas em contratar produto ou servico.",
        "agente_restricoes": (
            "Responder em portugues brasileiro. Mensagens curtas, no maximo 3 paragrafos. "
            "Nao inventar informacoes sobre preco ou disponibilidade."
        ),
    },
    {
        "id": "assistente",
        "nome": "Assistente Pessoal",
        "descricao": "Conversa geral, ajuda com tarefas, lembretes, perguntas variadas.",
        "icone": "fa-user-tie",
        "cor": "var(--color-primary)",
        "agente_papel": (
            "Voce e um assistente pessoal versatil e cordial. Combina conhecimento de "
            "especialista multidisciplinar com empatia de consultor de confianca."
        ),
        "agente_objetivo": (
            "Ajudar com qualquer pedido razoavel: responder perguntas, organizar ideias, "
            "redigir textos, lembrar de tarefas, dar opinioes ponderadas."
        ),
        "agente_politicas": (
            "Ser claro e direto. Adaptar o tom ao perfil de quem conversa. Admitir quando "
            "nao sabe. Nao dar conselhos medicos, juridicos ou financeiros definitivos."
        ),
        "agente_tarefa": "Conversar e ajudar no que for solicitado.",
        "agente_objetivo_explicito": "Ser util de forma rapida e confiavel.",
        "agente_publico": "Usuario individual em conversas do dia a dia.",
        "agente_restricoes": (
            "Responder em portugues brasileiro. Evitar respostas excessivamente longas "
            "quando uma resposta curta resolve."
        ),
    },
    {
        "id": "suporte",
        "nome": "Suporte Tecnico",
        "descricao": "Responde duvidas, troubleshoot inicial, escalona problemas complexos.",
        "icone": "fa-headset",
        "cor": "var(--color-warning)",
        "agente_papel": (
            "Voce e um agente de suporte tecnico paciente e metodico. Acolhe o cliente, "
            "entende o problema e oferece caminhos claros para resolver."
        ),
        "agente_objetivo": (
            "Resolver duvidas em primeiro contato sempre que possivel. Quando nao for "
            "possivel, registrar o caso de forma clara para um humano dar sequencia."
        ),
        "agente_politicas": (
            "Confirmar entendimento antes de propor solucao. Usar linguagem simples. "
            "Pedir prints/dados especificos quando necessario. Nunca prometer prazo "
            "sem confirmacao."
        ),
        "agente_tarefa": (
            "Acolher chamado, perguntar dados essenciais, sugerir primeiros passos de "
            "verificacao, escalonar quando necessario."
        ),
        "agente_objetivo_explicito": "Resolver ou encaminhar o problema do cliente.",
        "agente_publico": "Clientes com duvida ou problema relacionado ao produto.",
        "agente_restricoes": (
            "Responder em portugues brasileiro. Nao inventar passos tecnicos quando nao "
            "souber o produto especifico. Nao revelar dados internos."
        ),
    },
]


def obter_template_agente(template_id: str) -> Optional[Dict[str, str]]:
    """Busca um template de agente pelo id (atendente|assistente|suporte)."""
    for tpl in TEMPLATES_AGENTE:
        if tpl["id"] == template_id:
            return tpl
    return None


# -------------------- Estado do wizard --------------------


ESTADO_PADRAO: Dict[str, Any] = {
    "step": 1,
    "provedor_id": None,
    "sessao_id": None,
    "canal": None,
    "agente_id": None,
    "finalizado": False,
}


def obter_estado(request) -> Dict[str, Any]:
    """Le estado atual do wizard da sessao HTTP. Cria se nao existe."""
    estado = request.session.get("onboarding")
    if not isinstance(estado, dict):
        estado = dict(ESTADO_PADRAO)
        request.session["onboarding"] = estado
    return estado


def salvar_estado(request, **patch) -> Dict[str, Any]:
    """Atualiza chaves do estado e persiste na sessao HTTP."""
    estado = obter_estado(request)
    estado.update(patch)
    request.session["onboarding"] = estado
    return estado


def limpar_estado(request) -> None:
    """Remove o estado do wizard (apos finalizar/pular)."""
    request.session.pop("onboarding", None)


# -------------------- Deteccao e teste de provedores --------------------


def detectar_provedores_locais(timeout: float = 1.5) -> List[Dict[str, Any]]:
    """Tenta GET {base_url}/models nos provedores locais conhecidos.

    Retorna lista no formato:
      [{nome, tipo, base_url, descricao, icone, disponivel, modelos: [...]}]
    """
    resultado: List[Dict[str, Any]] = []
    for cfg in PROVEDORES_LOCAIS:
        entry = dict(cfg)
        entry["disponivel"] = False
        entry["modelos"] = []
        url = cfg["base_url"].rstrip("/") + "/models"
        try:
            r = httpx.get(url, timeout=timeout)
            if r.status_code == 200:
                entry["disponivel"] = True
                data = r.json()
                # OpenAI-style: {"data":[{"id":...}]}
                modelos = []
                for m in (data.get("data") or [])[:10]:
                    mid = m.get("id") or m.get("name") or ""
                    if mid:
                        modelos.append(mid)
                entry["modelos"] = modelos
        except Exception:
            # Silencioso: provedor offline e estado esperado.
            pass
        resultado.append(entry)
    return resultado


def testar_conexao(base_url: str, api_key: Optional[str] = None, timeout: float = 5.0) -> Dict[str, Any]:
    """Faz GET {base_url}/models. Retorna {ok, mensagem, modelos, tempo_ms}."""
    url = base_url.rstrip("/") + "/models"
    headers: Dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    inicio = time.time()
    try:
        r = httpx.get(url, timeout=timeout, headers=headers)
        tempo_ms = (time.time() - inicio) * 1000.0
        if r.status_code == 200:
            data = r.json()
            modelos = []
            for m in (data.get("data") or [])[:15]:
                mid = m.get("id") or m.get("name") or ""
                if mid:
                    modelos.append(mid)
            return {
                "ok": True,
                "mensagem": f"Conectado ({len(modelos)} modelos disponiveis)",
                "modelos": modelos,
                "tempo_ms": round(tempo_ms, 1),
            }
        return {
            "ok": False,
            "mensagem": f"Servidor respondeu HTTP {r.status_code}",
            "modelos": [],
            "tempo_ms": round(tempo_ms, 1),
        }
    except httpx.ConnectError:
        return {"ok": False, "mensagem": "Nao consegui conectar (servidor offline?)", "modelos": [], "tempo_ms": None}
    except httpx.TimeoutException:
        return {"ok": False, "mensagem": "Tempo esgotado", "modelos": [], "tempo_ms": None}
    except Exception as e:
        return {"ok": False, "mensagem": f"Erro: {e}", "modelos": [], "tempo_ms": None}


# -------------------- Helpers de estado global --------------------


def sistema_ja_configurado(db: Session) -> bool:
    """True se ja existe pelo menos uma Sessao ou um ProvedorLLM."""
    if db.query(Sessao).count() > 0:
        return True
    if db.query(ProvedorLLM).count() > 0:
        return True
    return False


def proximo_codigo_agente(db: Session, sessao_id: int) -> str:
    """Devolve proximo codigo livre ('01', '02', ...) para uma sessao."""
    from agente.agente_model import Agente

    existentes = {
        a.codigo for a in db.query(Agente.codigo).filter(Agente.sessao_id == sessao_id).all()
    }
    for i in range(1, 100):
        candidato = f"{i:02d}"
        if candidato not in existentes:
            return candidato
    return "99"
