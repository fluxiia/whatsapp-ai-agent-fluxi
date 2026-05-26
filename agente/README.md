# Módulo `agente` — Documentação Técnica

> **Audiência principal:** modelos LLM usados como assistentes de desenvolvimento.
> Leia este documento inteiro antes de modificar qualquer arquivo deste módulo.

---

## 1. Visão Geral

O módulo `agente` é o **núcleo de inteligência** do sistema Fluxi. Ele representa uma persona LLM configurável que:

- Recebe mensagens via WhatsApp (e outros canais)
- Mantém um histórico de conversa por telefone
- Executa um **loop agentic** com suporte a tool-calling real
- Integra RAG, Skills, Ferramentas HTTP/Code, MCP clients e Sandbox interno
- Retorna uma resposta final em texto para ser enviada ao usuário

Cada **Sessão WhatsApp** possui múltiplos agentes, mas apenas um `agente_ativo_id` por vez processa as mensagens recebidas.

---

## 2. Estrutura de Arquivos

```
agente/
├── agente_model.py           # SQLAlchemy ORM (tabelas: agentes, agente_ferramenta)
├── agente_schema.py          # Pydantic schemas (AgenteCriar, AgenteAtualizar, AgenteResposta)
├── agente_service.py         # Lógica de negócio + loop agentic principal
├── agente_router.py          # REST API /api/agentes/...
├── agente_frontend_router.py # Rotas web /agentes/... (templates Jinja2)
└── README.md                 # Este arquivo
```

---

## 3. Modelo de Dados

### 3.1 Tabela `agentes`

```python
# agente_model.py — classe Agente
class Agente(Base):
    __tablename__ = "agentes"

    # Identificação
    id              : Integer, PK, autoincrement
    sessao_id       : Integer, FK("sessoes.id", ondelete="CASCADE"), NOT NULL, indexed
    codigo          : String(10), NOT NULL          # "01", "02"... único por sessão
    nome            : String(100), NOT NULL
    descricao       : Text, nullable                # nota interna, não vai ao LLM

    # System Prompt — 7 campos estruturados
    agente_papel               : Text   # "Você é..."
    agente_objetivo            : Text   # Objetivo macro
    agente_politicas           : Text   # Tom de voz, emojis, linguagem
    agente_tarefa              : Text   # Fluxo passo-a-passo
    agente_objetivo_explicito  : Text   # Meta mensurável
    agente_publico             : Text   # Público-alvo
    agente_restricoes          : Text   # O que NUNCA fazer

    # Configuração LLM (nullable = usa padrão global da config)
    provedor_llm_id   : Integer, FK("provedores_llm.id"), nullable
    modelo_llm        : String(100), nullable  # "google/gemini-flash-3.1-lite-preview"
    temperatura       : Float, nullable         # 0.0–2.0 (default 0.7)
    max_tokens        : Integer, nullable       # (default 2000)
    top_p             : Float, nullable         # 0.0–1.0 (default 1.0)
    frequency_penalty : Float, nullable         # -2.0–2.0 (default 0.0)
    presence_penalty  : Float, nullable         # -2.0–2.0 (default 0.0)

    # Integrações
    rag_id                 : Integer, FK("rags.id"), nullable
    internal_sandbox_ativo : Boolean, default=False
    is_coding_agent        : Boolean, default=False

    # Status
    ativo       : Boolean, default=True
    criado_em   : DateTime, server_default=now()
    atualizado_em: DateTime, onupdate=now()
```

### 3.2 Tabela de Associação `agente_ferramenta`

```python
agente_ferramenta = Table(
    "agente_ferramenta", Base.metadata,
    Column("agente_id",     Integer, ForeignKey("agentes.id",    ondelete="CASCADE"), primary_key=True),
    Column("ferramenta_id", Integer, ForeignKey("ferramentas.id",ondelete="CASCADE"), primary_key=True),
    Column("ativa",     Boolean,  default=True),
    Column("criado_em", DateTime, server_default=func.now()),
)
```

### 3.3 Tabela de Associação `agente_skill`

```python
# Definida em skill/skill_model.py — referenciada pelo agente
agente_skill = Table(
    "agente_skill", Base.metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("agente_id", Integer, ForeignKey("agentes.id",  ondelete="CASCADE")),
    Column("skill_id",  Integer, ForeignKey("skills.id",   ondelete="CASCADE")),
    Column("posicao",   Integer, default=0),    # ordem de exibição
    Column("ativa",     Boolean, default=True),
    UniqueConstraint("agente_id", "skill_id"),
)
```

### 3.4 Relacionamentos SQLAlchemy

```python
Agente.sessao         -> Sessao          (back_populates="agentes")
Agente.ferramentas    -> List[Ferramenta] via agente_ferramenta (lazy="dynamic")
Agente.rag            -> RAG             (back_populates="agentes")
Agente.mcp_clients    -> List[MCPClient] (cascade="all, delete-orphan")
Agente.skills         -> List[Skill]     via agente_skill (lazy="dynamic")
Agente.coding_session -> CodingSession   (uselist=False, cascade="all, delete-orphan")
```

---

## 4. Schemas Pydantic

```python
# agente_schema.py

class AgenteBase(BaseModel):
    codigo                   : str
    nome                     : str
    descricao                : Optional[str] = None
    agente_papel             : str
    agente_objetivo          : str
    agente_politicas         : str
    agente_tarefa            : str
    agente_objetivo_explicito: str
    agente_publico           : str
    agente_restricoes        : str
    provedor_llm_id          : Optional[int]   = None
    modelo_llm               : Optional[str]   = None
    temperatura              : Optional[float] = None
    max_tokens               : Optional[int]   = None
    top_p                    : Optional[float] = None
    frequency_penalty        : Optional[float] = None
    presence_penalty         : Optional[float] = None
    ativo                    : bool = True

class AgenteCriar(AgenteBase):
    sessao_id: int            # obrigatório

class AgenteAtualizar(BaseModel):
    # Todos os campos de AgenteBase são Optional (partial update)
    ...

class AgenteResposta(AgenteBase):
    id                     : int
    sessao_id              : int
    rag_id                 : Optional[int]  = None
    internal_sandbox_ativo : Optional[bool] = False
    criado_em              : datetime
    atualizado_em          : Optional[datetime] = None

class AgenteFerramentasAtualizar(BaseModel):
    ferramentas: List[int]    # IDs; máximo definido por config "agente_max_ferramentas" (padrão 20)
```

---

## 5. AgenteService — Métodos Públicos

### 5.1 CRUD

```python
AgenteService.listar_todos(db)                         -> List[Agente]
AgenteService.listar_por_sessao(db, sessao_id)         -> List[Agente]
AgenteService.listar_por_sessao_ativos(db, sessao_id)  -> List[Agente]
AgenteService.obter_por_id(db, agente_id)              -> Optional[Agente]
AgenteService.obter_por_codigo(db, sessao_id, codigo)  -> Optional[Agente]

AgenteService.criar(db, agente: AgenteCriar)           -> Agente
    # Raises ValueError se código já existe na sessão

AgenteService.atualizar(db, agente_id, agente: AgenteAtualizar) -> Optional[Agente]
    # Raises ValueError se novo código já existe em outra entrada da sessão

AgenteService.deletar(db, agente_id)                   -> bool
```

### 5.2 Ferramentas

```python
AgenteService.atualizar_ferramentas(db, agente_id, ferramentas_ids: List[int]) -> None
    # Valida limite via int(ConfiguracaoService.obter_valor(db, "agente_max_ferramentas", 20))
    # Limpa todas as associações existentes e insere as novas (transacional)
    # Raises ValueError se acima do limite

AgenteService.listar_ferramentas(db, agente_id) -> List[Ferramenta]
    # JOIN agente_ferramenta WHERE ativa=True AND Ferramenta.ativa=True
```

### 5.3 Agente Padrão

```python
AgenteService.criar_agente_padrao(db, sessao_id) -> Agente
    # Cria agente "Fluxi" código "01"
    # Lê 7 campos do system prompt de ConfiguracaoService (chaves: agente_*_padrao)
    # Associa ferramentas padrão (config: "agente_ferramentas_padrao" — lista de nomes)
```

### 5.4 System Prompt

```python
AgenteService.construir_system_prompt(agente: Agente, skills: Optional[List] = None) -> str
    # Monta string com os 7 campos do agente
    # Appenda bloco fixo de instrução de ferramentas
    # Se skills: appenda _construir_secao_skills(skills)
    # Esta função é chamada ANTES de cada chamada LLM

AgenteService._construir_secao_skills(skills: List) -> str
    # Agrupa skills por prefixo (ex: "vendas-abertura" -> família "vendas")
    # Instrui o LLM a usar `invocar_skill` para acessar skill completa
```

### 5.5 Processamento Principal

```python
async def AgenteService.processar_mensagem(
    db                 : Session,
    sessao             : Sessao,         # objeto com .id, .agente_ativo_id
    mensagem           : Mensagem,       # objeto com .conteudo_texto, .tipo, .telefone_cliente
    historico_mensagens: List[Mensagem], # lista ordenada por criado_em ASC
    agente             : Optional[Agente] = None,  # se None, usa sessao.agente_ativo_id
    jid_destino        : Optional[str] = None      # JID WhatsApp resolvido (formato LID)
) -> Dict[str, Any]

# RETORNO:
{
    "texto"          : str,              # Resposta final para o usuário
    "tokens_input"   : int,              # Total acumulado de todas as iterações
    "tokens_output"  : int,
    "tempo_ms"       : int,
    "modelo"         : str,              # Ex: "google/gemini-3.1-flash-lite-preview"
    "ferramentas"    : List[Dict] | None # Ferramentas acionadas com args e resultados
}

# RAISES:
#   ValueError("Nenhum agente ativo configurado para esta sessão")
#   ValueError("Timeout de Xs atingido aguardando resposta do LLM...")
#   ValueError("Erro ao processar com LLM: ...")
```

---

## 6. Loop Agentic — Fluxo Completo

```
processar_mensagem()
│
├─ 1. RESOLVE AGENTE
│     Se agente=None -> agente = obter_por_id(sessao.agente_ativo_id)
│     Se ainda None  -> raises ValueError
│
├─ 2. PARÂMETROS LLM
│     modelo        = agente.modelo_llm  OR  config("openrouter_modelo_padrao")
│     temperatura   = agente.temperatura  OR  float(config("openrouter_temperatura",   0.7))
│     max_tokens    = agente.max_tokens   OR  int(config("openrouter_max_tokens",      2000))
│     top_p         = agente.top_p        OR  float(config("openrouter_top_p",         1.0))
│     freq_pen      = agente.frequency_penalty OR float(config(..., 0.0))
│     pres_pen      = agente.presence_penalty  OR float(config(..., 0.0))
│
├─ 3. SKILLS
│     skills_agente = SkillService.listar_skills_agente(db, agente.id)
│     system_prompt = construir_system_prompt(agente, skills_agente)
│
├─ 4. CONTEXTO DE MENSAGENS
│     historico = construir_historico_mensagens(historico_mensagens, mensagem)
│     # Filtra: direcao="recebida", últimas 10
│     # Par por mensagem: {"role":"user","content":txt} + {"role":"assistant","content":resposta}
│     # Imagem: content = [{"type":"text","text":...}, {"type":"image_url","image_url":{"url":"data:mime;base64,..."}}]
│
│     messages = [
│         {"role": "system",  "content": system_prompt},
│         *historico,
│         {"role": "user",    "content": conteudo_atual}
│     ]
│
├─ 5. MONTAGEM DE TOOLS
│     tools = []
│
│     # 5.1 Ferramentas normais (HTTP, Code, Native)
│     for f in listar_ferramentas(db, agente.id):
│         tools.append(FerramentaService.converter_para_openai_format(f))
│
│     # 5.2 Ferramentas MCP (exclui preset "aio-sandbox")
│     for client in MCPService.listar_ativos_por_agente(db, agente.id):
│         if client.preset_key == "aio-sandbox": continue
│         if not client.conectado: continue
│         for tool in MCPService.listar_tools_ativas(db, client.id):
│             tools.append(MCPService.converter_mcp_tool_para_openai(client, tool))
│             # Nome resultante: "mcp_{client.id}_{tool.nome}"
│
│     # 5.3 Meta-tool de skills
│     if skills_agente:
│         tools.append(_definir_tool_invocar_skill())
│         # Parâmetros da tool: {"skill_nome": str, "argumentos": dict}
│
│     # 5.4 Tool RAG
│     if agente.rag_id:
│         tools.append({"type":"function","function":{
│             "name": "buscar_base_conhecimento",
│             "parameters": {"query": str, "num_resultados": int (opcional)}
│         }})
│
├─ 6. LOOP PRINCIPAL
│     max_iter = int(config("agente_max_iteracoes_sandbox", 25))  # se sandbox ativo
│              = int(config("agente_max_iteracoes_loop",   10))   # modo normal
│
│     _ultimas_tools = []   # janela deslizante para detecção de loop
│
│     while iteracao < max_iter:
│         iteracao += 1
│
│         # Context management para sandbox
│         messages_llm = _trim_messages_sandbox(messages) if sandbox else messages
│         # _trim: mantém 2 últimas tool-results completas; trunca antigas para 350 chars
│
│         # CHAMADA LLM com timeout
│         resultado = await asyncio.wait_for(
│             LLMIntegrationService.processar_mensagem_com_llm(...),
│             timeout=300.0 if sandbox else 120.0
│         )
│         # raises ValueError em TimeoutError
│
│         messages.append({
│             "role": "assistant",
│             "content": resultado["conteudo"],
│             "tool_calls": resultado["tool_calls"]
│         })
│
│         tool_calls = resultado["tool_calls"]  # List[Dict] ou None
│
│         # SEM TOOL_CALLS -> resposta final
│         if not tool_calls:
│             texto_resposta_final = resultado["conteudo"]
│             break
│
│         # DETECÇÃO DE LOOP (janela de 3 chamadas consecutivas idênticas)
│         tool_names = sorted(tc["function"]["name"] for tc in tool_calls)
│         _ultimas_tools.append(tool_names)
│         if len(_ultimas_tools) > 3: _ultimas_tools.pop(0)
│         if len(_ultimas_tools) == 3 and all(t == _ultimas_tools[0] for t in _ultimas_tools):
│             texto_resposta_final = "Não foi possível concluir: ferramenta em loop."
│             break
│
│         # EXECUÇÃO DAS TOOLS
│         for tc in tool_calls:
│             name = tc["function"]["name"]
│             args_raw = tc["function"]["arguments"]
│             args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
│
│             if name.startswith("sandbox_") and agente.internal_sandbox_ativo:
│                 resultado_completo = await InternalService.executar_tool(db, agente.id, name, args)
│
│             elif name.startswith("mcp_"):
│                 # Parse: "mcp_{client_id}_{tool_nome}"
│                 parts = name.split("_", 2)
│                 client_id, tool_nome = int(parts[1]), parts[2]
│                 resultado_completo = await MCPService.executar_tool_mcp(db, client_id, tool_nome, args)
│
│             elif name == "buscar_base_conhecimento" and agente.rag_id:
│                 query = args["query"]
│                 n = args.get("num_resultados", int(config("agente_rag_resultados_padrao", 3)))
│                 resultados = RAGService.buscar(db, agente.rag_id, query, n)
│                 RAGMetricaService.registrar_busca(db, agente.rag_id, query, resultados, ...)
│                 resultado_completo = {"resultado": {"contextos": [...], "total": N}, "output": "llm"}
│
│             elif name == "invocar_skill":
│                 resultado_completo = await _executar_invocar_skill(db, agente, args, tools, messages)
│
│             elif name == "enviar_arquivo_whatsapp" and agente.internal_sandbox_ativo:
│                 resultado_completo = await _enviar_arquivo_sandbox(db, sessao.id, ...)
│
│             elif name == "enviar_screenshot_whatsapp" and agente.internal_sandbox_ativo:
│                 resultado_completo = await _enviar_screenshot_sandbox(sessao.id, ...)
│
│             else:
│                 resultado_completo = await FerramentaService.executar_ferramenta(
│                     db, name, args,
│                     sessao_id=sessao.id,
│                     telefone_cliente=mensagem.telefone_cliente
│                 )
│
│             # Intercepta imagens base64 em resultados sandbox -> envia ao WhatsApp
│             if sandbox and name.startswith("sandbox_"):
│                 resultado_completo = await _extrair_e_enviar_imagens_sandbox(...)
│
│             # Agrega no histórico LLM
│             output_type = resultado_completo.get("output", "llm")
│             content = json.dumps(resultado_completo["resultado"])
│             if resultado_completo.get("post_instruction"):
│                 content += f"\n\nInstrução: {post_instruction}"
│
│             if output_type in ("llm", "both"):
│                 messages.append({"role": "tool", "tool_call_id": tc["id"], "content": content})
│             else:  # output="user": LLM sabe que foi enviado ao usuário
│                 messages.append({"role": "tool", "tool_call_id": tc["id"],
│                                  "content": '{"status":"enviado_ao_usuario"}'})
│
│         continue  # próxima iteração com os resultados
│
└─ 7. RETORNO
      return {
          "texto":        texto_resposta_final,
          "tokens_input": tokens_input_total,
          "tokens_output": tokens_output_total,
          "tempo_ms":     int((time.time() - inicio) * 1000),
          "modelo":       modelo,
          "ferramentas":  ferramentas_usadas or None
      }
```

---

## 7. Integrações Externas — Contratos de Interface

### 7.1 `LLMIntegrationService`

```python
# llm_providers/llm_integration_service.py
resultado = await LLMIntegrationService.processar_mensagem_com_llm(
    db              = db,
    messages        = List[Dict],    # formato OpenAI messages array
    modelo          = str,           # "google/gemini-3.1-flash-lite-preview"
    agente_id       = Optional[int],
    temperatura     = float,
    max_tokens      = int,
    top_p           = float,
    frequency_penalty = float,
    presence_penalty  = float,
    tools           = Optional[List[Dict]],  # formato OpenAI tools
    stream          = False,         # sempre False no agente (True só no coding agent)
    on_text_delta   = None,
) -> {
    "conteudo"       : str,
    "tool_calls"     : List[{"id":str, "function":{"name":str, "arguments":str}}] | None,
    "tokens_input"   : int,
    "tokens_output"  : int,
    "finish_reason"  : str,    # "stop"|"tool_calls"|"length"|"tool_use"|"end_turn"|None
    "provedor_usado" : str,    # "local"|"openrouter"|"openrouter_fallback"
    "provedor_id"    : Optional[int],
    "tempo_total_ms" : float
}
```

**ARMADILHA CRÍTICA:** `finish_reason` NÃO é confiável para detectar tool_calls.
- Gemini via OpenRouter → retorna `"stop"` mesmo com tool_calls
- Claude/Anthropic → retorna `"tool_use"`
- Muitos modelos locais → retornam `None`

**Regra:** sempre cheque `if tool_calls:` antes de `finish_reason`.

**Seleção de Provedor (ordem):**
1. `config("llm_provedor_padrao") == "local"` + provedor configurado
2. `config("llm_provedor_padrao") == "openrouter"` + chave disponível
3. Modelos com prefixo `google/`, `anthropic/`, `openai/`, `meta-llama/` → forçam OpenRouter
4. Fallback automático para OpenRouter se `config("llm_fallback_openrouter") == True`

---

### 7.2 `FerramentaService`

```python
# ferramenta/ferramenta_service.py
tool_openai = FerramentaService.converter_para_openai_format(ferramenta) -> Optional[Dict]
# retorna None se ferramenta não é do tipo "principal"

resultado = await FerramentaService.executar_ferramenta(
    db,
    nome_ferramenta  : str,
    argumentos       : Dict[str, Any],
    sessao_id        : Optional[int] = None,
    telefone_cliente : Optional[str] = None
) -> {
    "resultado"       : Any,
    "output"          : "llm"|"user"|"both",
    "enviado_usuario" : bool,
    "channel"         : ChannelType  # opcional
}
```

---

### 7.3 `SkillService`

```python
# skill/skill_service.py
skills = SkillService.listar_skills_agente(db, agente_id) -> List[Skill]
# Filtra: agente_skill.ativa=True AND skill.ativa=True

dados = SkillService.executar_script(skill: Skill, argumentos: Dict) -> Dict[str, Any]
# Executa skill.script_codigo em namespace isolado
# Esperado: namespace.resultado = {...}
# Retorna namespace.resultado ou {} se sem script

ferramentas_extras = SkillService.obter_ferramentas_extras_da_skill(db, skill) -> List[Ferramenta]
# Lê skill.ferramentas_ids (JSON list de IDs) e retorna ferramentas ativas
```

**Modelo Skill (campos relevantes):**
```python
class Skill:
    nome                : str (unique)   # identificador usado em invocar_skill
    instrucao_completa  : Text           # template com {variavel} → substituído por dados do script
    script_codigo       : Text           # Python; define namespace.resultado = {...}
    script_parametros   : Text (JSON)    # schema dos parâmetros esperados
    ferramentas_ids     : Text (JSON)    # [1, 2, 3] IDs de ferramentas extras injetadas
    categoria           : str
    icone               : str (emoji)
    ativa               : bool
```

---

### 7.4 `MCPService`

```python
# mcp_client/mcp_service.py
clients    = MCPService.listar_ativos_por_agente(db, agente_id) -> List[MCPClient]
tools      = MCPService.listar_tools_ativas(db, mcp_client_id)  -> List[MCPTool]
tool_openai = MCPService.converter_mcp_tool_para_openai(client, tool) -> Dict
# Nome da tool resultante: "mcp_{client.id}_{tool.nome}"  ex: "mcp_3_search_web"

resultado = await MCPService.executar_tool_mcp(
    db,
    mcp_client_id : int,
    tool_name     : str,    # nome original, sem prefixo
    arguments     : Dict[str, Any]
) -> {"resultado": Any, "output": "llm"|"user", "tempo_ms": int}
```

**Parsing do prefixo MCP:**
```python
# "mcp_3_search_web" -> split("_", 2) -> ["mcp", "3", "search_web"]
parts         = function_name.split("_", 2)
mcp_client_id = int(parts[1])
original_name = parts[2]
```

---

### 7.5 `InternalService`

```python
# internal_sandbox/internal_service.py
# Ativado por agente.internal_sandbox_ativo = True

resultado = await InternalService.executar_tool(
    db, agente_id: int, tool_name: str, arguments: Dict
) -> {"resultado": Dict, "output": "llm", "enviado_usuario": bool, "tempo_ms": int}

# Métodos auxiliares (para _enviar_arquivo_sandbox e _enviar_screenshot_sandbox):
file_bytes = await InternalService.baixar_arquivo(agente_id, file_path: str) -> bytes
img_bytes  = await InternalService.tirar_screenshot(agente_id) -> bytes
img_bytes  = await InternalService.tirar_screenshot_pagina(agente_id, full_page=True) -> bytes
```

**Tools suportadas por `executar_tool`:**
```
Shell:   sandbox_shell_exec, sandbox_shell_view, sandbox_shell_write,
         sandbox_shell_kill, sandbox_shell_list_sessions, sandbox_shell_wait
File:    sandbox_file_read, sandbox_file_write, sandbox_file_list,
         sandbox_file_find, sandbox_file_grep, sandbox_file_replace,
         sandbox_file_search, sandbox_file_upload, sandbox_file_download
Browser: sandbox_browser_navigate, sandbox_browser_get_page_state,
         sandbox_browser_click_index, sandbox_browser_fill,
         sandbox_browser_screenshot, sandbox_browser_page_screenshot,
         sandbox_browser_wait_user
Code:    sandbox_code_exec
```

**Tools virtuais do agente** (não passadas via `executar_tool`, executadas diretamente):
- `enviar_arquivo_whatsapp(file_path, filename?, caption?)` → baixa + envia
- `enviar_screenshot_whatsapp(tipo, full_page?, caption?)` → captura + envia

---

### 7.6 `RAGService`

```python
# rag/rag_service.py
resultados = RAGService.buscar(db, rag_id, query: str, num_resultados: int) -> List[{
    "context"  : str,
    "metadata" : {"titulo": str, ...},
    "score"    : float
}]

# rag/rag_metrica_service.py
RAGMetricaService.registrar_busca(
    db,
    rag_id           : int,
    query            : str,
    resultados       : List[Dict],
    num_solicitados  : int,
    tempo_ms         : int,
    agente_id        : Optional[int],
    sessao_id        : Optional[int],
    telefone_cliente : Optional[str]
) -> Optional[RAGMetrica]
```

---

### 7.7 `ConfiguracaoService`

```python
# config/config_service.py
valor = ConfiguracaoService.obter_valor(db, chave: str, padrao: Any = None) -> Any
# Converte automaticamente (tipo armazenado: "int", "float", "bool", "json", "string")
# SEMPRE converta com int()/float() ao usar para comparações numéricas
```

**Chaves usadas por este módulo:**

| Chave | Tipo | Padrão |
|-------|------|--------|
| `openrouter_modelo_padrao` | string | `"google/gemini-3.1-flash-lite-preview"` |
| `openrouter_temperatura` | float | `0.7` |
| `openrouter_max_tokens` | int | `2000` |
| `openrouter_top_p` | float | `1.0` |
| `openrouter_frequency_penalty` | float | `0.0` |
| `openrouter_presence_penalty` | float | `0.0` |
| `agente_max_ferramentas` | int | `20` |
| `agente_max_iteracoes_loop` | int | `10` |
| `agente_max_iteracoes_sandbox` | int | `25` |
| `agente_rag_resultados_padrao` | int | `3` |
| `agente_papel_padrao` | string | — |
| `agente_objetivo_padrao` | string | — |
| `agente_politicas_padrao` | string | — |
| `agente_tarefa_padrao` | string | — |
| `agente_objetivo_explicito_padrao` | string | — |
| `agente_publico_padrao` | string | — |
| `agente_restricoes_padrao` | string | — |
| `agente_ferramentas_padrao` | json | lista de nomes |
| `llm_provedor_padrao` | string | `"auto"` |
| `llm_fallback_openrouter` | bool | `True` |

---

### 7.8 Modelo `Mensagem`

```python
# mensagem/mensagem_model.py — campos usados pelo agente
class Mensagem:
    id                     : Integer, PK
    sessao_id              : Integer, FK
    telefone_cliente       : String, indexed
    tipo                   : String   # "texto"|"imagem"|"documento"|"audio"|"video"
    direcao                : String   # "recebida"|"enviada"
    conteudo_texto         : Text
    conteudo_imagem_base64 : Text     # base64 puro (sem prefixo data:)
    conteudo_mime_type     : String   # "image/jpeg", "image/png"
    resposta_texto         : Text
    resposta_tokens_input  : Integer
    resposta_tokens_output : Integer
    resposta_tempo_ms      : Integer
    resposta_modelo        : String
    resposta_erro          : Text
    ferramentas_usadas     : JSON
    processada             : Boolean
    respondida             : Boolean
    criado_em              : DateTime
```

---

## 8. API REST — Referência

**Base:** `/api/agentes`

| Método | Path | Body | Retorno |
|--------|------|------|---------|
| GET | `/llm-opcoes` | — | provedores, modelos, config padrão |
| GET | `/` | `?sessao_id=int&apenas_ativos=bool` | `List[AgenteResposta]` |
| GET | `/{id}` | — | `AgenteResposta` |
| POST | `/` | `AgenteCriar` (JSON) | `AgenteResposta` |
| PUT | `/{id}` | `AgenteAtualizar` (JSON) | `AgenteResposta` |
| DELETE | `/{id}` | — | `{"mensagem": str}` |
| POST | `/{id}/ferramentas` | `AgenteFerramentasAtualizar` | `{"mensagem": str}` |
| GET | `/{id}/ferramentas` | — | `List[Ferramenta]` |
| POST | `/{id}/internal-sandbox` | `{"internal_sandbox_ativo": bool}` | `{"mensagem": str, "internal_sandbox_ativo": bool}` |
| POST | `/{id}/vincular-treinamento` | `{"rag_id": int \| null}` | `{"mensagem": str}` |

---

## 9. Rotas Web (Frontend)

**Base:** `/agentes`

| Método | Path | Renderiza / Redireciona |
|--------|------|------------------------|
| GET | `/sessao/{sessao_id}` | `agente/lista.html` |
| GET | `/sessao/{sessao_id}/novo` | `agente/form.html` |
| GET | `/{agente_id}` | `agente/detalhes.html` (5 abas) |
| POST | `/sessao/{sessao_id}/criar` | → `/agentes/sessao/{id}` |
| POST | `/{agente_id}/atualizar` | → `/agentes/{id}` |
| POST | `/{agente_id}/ferramentas/atualizar` | → `/agentes/{id}?tab=ferramentas` |
| POST | `/{agente_id}/deletar` | → `/agentes/sessao/{id}` |
| POST | `/{agente_id}/ativar` | define `sessao.agente_ativo_id` → lista |

Skills têm endpoint em `skill/skill_router.py`:
- `POST /agentes/{agente_id}/skills/atualizar` — FormData: `skill_ids` (CSV de IDs)

**Calls AJAX do frontend (detalhes.html):**
```javascript
// Salvar comportamento + config LLM
POST /agentes/{id}/atualizar          (FormData)

// Salvar ferramentas
POST /agentes/{id}/ferramentas/atualizar  (FormData: ferramenta_{id})

// Salvar skills
POST /agentes/{id}/skills/atualizar   (FormData: skill_ids="1,3,5")

// Vincular RAG
POST /api/agentes/{id}/vincular-treinamento  (JSON: {"rag_id": int|null})

// Toggle sandbox
POST /api/agentes/{id}/internal-sandbox  (JSON: {"internal_sandbox_ativo": bool})
```

---

## 10. Padrões e Convenções

### 10.1 Estrutura de Retorno de Tool

Todo executor de tool deve retornar:
```python
{
    "resultado"       : Any,           # conteúdo que vai ao LLM (ou ao usuário)
    "output"          : str,           # "llm" | "user" | "both"
    "enviado_usuario" : bool,          # True se já foi enviado diretamente
    "post_instruction": Optional[str], # instrução extra appended ao conteúdo para o LLM
    "tempo_ms"        : Optional[int]
}
```

- `"llm"` → resultado vai ao `messages` como `role: "tool"`
- `"user"` → LLM recebe `{"status": "enviado_ao_usuario"}` — evita duplicação
- `"both"` → resultado completo vai ao LLM E ao usuário

### 10.2 System Prompt — Estrutura

```
Você é: {agente_papel}.
Objetivo: {agente_objetivo}.
Políticas: {agente_politicas}.
Tarefa: {agente_tarefa}.
Objetivo explícito: {agente_objetivo_explicito}.
Público/usuário-alvo: {agente_publico}.
Restrições: {agente_restricoes}.

IMPORTANTE - USO DE FERRAMENTAS:
[bloco fixo com instruções de uso de tools — sempre presente]

SKILLS DISPONÍVEIS:     <- apenas se agente tem skills
[lista agrupada por família, instrui a usar invocar_skill]
```

### 10.3 Checkbox HTML em Forms

Checkboxes HTML **não enviam nada quando desmarcados**. Em `agente_frontend_router.py`:
```python
# CORRETO:
ativo: Optional[str] = Form(None)
ativo_bool = ativo is not None and ativo.lower() in ("true", "on", "1", "yes")

# ERRADO (sempre True, nunca pode desmarcar):
ativo: bool = Form(True)
```

### 10.4 ConfiguracaoService — Conversão de Tipo

`obter_valor()` pode retornar string quando o valor existe no banco:
```python
# CORRETO:
max_iteracoes = int(ConfiguracaoService.obter_valor(db, "agente_max_iteracoes_loop", 10))

# ERRADO (TypeError em while iteracao < max_iteracoes):
max_iteracoes = ConfiguracaoService.obter_valor(db, "agente_max_iteracoes_loop", 10)
```

### 10.5 Tool Arguments — Parsing Seguro

```python
# O campo "arguments" pode ser string JSON ou dict dependendo do provedor
args_raw = tc["function"]["arguments"]
args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
```

---

## 11. Extensibilidade — Como Adicionar Nova Tool

Para adicionar uma nova categoria de tool ao loop agentic:

1. **Defina a função OpenAI** (ou adicione ao banco via `ferramentas`)
2. **Adicione o dispatch** no bloco `for tc in tool_calls:` em `processar_mensagem()`:
   ```python
   elif name == "minha_nova_tool":
       resultado_completo = await MinhaNovaService.executar(db, args, ...)
   ```
3. **Siga o padrão de retorno** (seção 10.1)
4. **Registre no histórico** automaticamente (o código após o dispatch já faz isso)

Para nova integração via MCP (zero código novo):
- Crie um `MCPClient` para o agente via interface web ou API `/api/mcp-clients`
- O loop detecta pelo prefixo `mcp_` automaticamente

---

## 12. Grafo de Dependências

```
agente/agente_service.py
├── llm_providers.LLMIntegrationService    [toda chamada LLM — CRÍTICO]
├── ferramenta.FerramentaService           [tools HTTP, Code, Native]
├── skill.SkillService                     [skills dinâmicas por agente]
├── mcp_client.MCPService                  [integrações externas via MCP]
├── internal_sandbox.InternalService       [shell, browser, arquivo, code]
├── rag.RAGService                         [busca semântica]
├── rag.RAGMetricaService                  [métricas de uso do RAG]
├── sessao.gerenciador_sessoes             [cliente WhatsApp para envio]
├── config.ConfiguracaoService             [parâmetros globais]
└── mensagem.Mensagem                      [modelo da mensagem recebida]
```

Imports externos são **locais** (dentro dos métodos) para evitar ciclos de importação.

---

## 13. Armadilhas Documentadas

| Situação | Comportamento Incorreto | Solução |
|----------|------------------------|---------|
| `finish_reason` diferente de `"tool_calls"` | Tool calls ignoradas → resposta vazia | Checar `if tool_calls:` ignorando finish_reason |
| `obter_valor()` retorna string do banco | `TypeError` em comparações numéricas | Sempre envolver com `int()` ou `float()` |
| Checkbox desmarcado no form HTML | FastAPI recebe `None`, não `False` | `Optional[str] = Form(None)` + conversão manual |
| `sessao.agente_ativo_id` aponta para agente deletado | `obter_por_id()` retorna `None` silenciosamente | Checar retorno antes de usar |
| Tool `sandbox_*` chamada sem sandbox ativo | Cai no `else` → vai para `FerramentaService` que não conhece a tool | Verificar `agente.internal_sandbox_ativo` |
| `tool_call["function"]["arguments"]` é dict em modelos locais | `json.loads(dict)` levanta `TypeError` | `json.loads(x) if isinstance(x, str) else x` |
| Imagem base64 em resultado sandbox enviada ao LLM | Overflow de contexto no LLM | `_extrair_e_enviar_imagens_sandbox()` intercepta e substitui por resumo |
| `invocar_skill` com skill não associada ao agente | `SkillService` retorna None ou raise | Validar `skill in skills_agente` antes de executar |
