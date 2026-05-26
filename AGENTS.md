# AGENTS.md — instruções pra agentes de IA contribuindo no Fluxi

Este arquivo é o ponto de entrada pra LLMs (Claude Code, Codex, Cursor, etc.) que vão escrever, refatorar ou revisar código aqui. Ele deve responder em <2 minutos: "como funciona, o que evitar, como validar".

Pra documentação voltada a humanos finais, ver [`README.md`](README.md).

---

## TL;DR — leia primeiro

- **Stack:** FastAPI + Jinja2 (SSR puro, **zero JS framework**) + SQLAlchemy + SQLite + Pydantic v2 + Python 3.11+
- **Padrão de módulo:** cada domínio em sua pasta, arquivos prefixados com o nome (`agente_model.py`, `agente_service.py`, `agente_router.py`, etc.)
- **Sem chamadas REST do JS:** toda interação web é via navegação (`<a>`) ou formulário (`<form method="post">`). Exceção controlada: webchat usa `fetch` + SSE
- **Banco:** Base SQLAlchemy global em [`database.py`](database.py); migrations aditivas via SQL no `startup_event` de [`main.py`](main.py); SQLite por default
- **Toda rota protegida** por `AuthMiddleware` ([`auth/auth_dependencies.py`](auth/auth_dependencies.py)) — rotas públicas listadas em `ROTAS_PUBLICAS`
- **Não rode `Base.metadata.drop_all`**, não delete `data/fluxi.db`, não force migration destrutiva

---

## Arquitetura em uma página

```
                       ┌────────────────────────┐
                       │   Browser do operador  │  (autenticado)
                       └───────────┬────────────┘
                                   │  /sessoes /agentes /skills ...
                                   ▼
                           ┌──────────────┐
                           │  FastAPI app │ ← AuthMiddleware
                           └──────┬───────┘
                                  │
   ┌──────────────────────────────┼──────────────────────────────────┐
   │                              │                                  │
   ▼                              ▼                                  ▼
┌─────────┐               ┌──────────────┐                  ┌──────────────┐
│ canal/  │   ───────►    │  mensagem/   │    ───────►      │   agente/    │
│ WA/TG/  │   evento      │ pipeline +   │   chama          │  LLM + tools │
│ webchat │               │ roteamento   │                  │  + RAG + MCP │
└────┬────┘               └──────────────┘                  └──────┬───────┘
     │                                                              │
     │ envia resposta (texto/áudio/imagem)                          │
     └◄─────────────────────────────────────────────────────────────┘
```

Cada **canal** entrega um `EventoMensagem` normalizado pro `MensagemService`. O pipeline roteia comandos, salva no DB, chama o agente, e o agente devolve via `canal.enviar_*`.

---

## Estrutura de pastas

```
fluxi/
├── auth/               # Login, signup, middleware. Sempre cifre senhas com bcrypt.
├── canal/              # ★ Abstração multi-canal — NÃO importe neonize/PTB direto fora daqui
│   ├── canal_base.py      # CanalClient (Protocol) + EventoMensagem
│   ├── canal_whatsapp.py  # Adapter neonize + shims de compat (send_message/image/etc)
│   ├── canal_telegram.py  # Adapter python-telegram-bot v21 (loop async em thread)
│   ├── canal_webchat.py   # Filas asyncio por chat_id; consumidas por SSE
│   ├── canal_factory.py   # Decide qual adapter criar por sessao.plataforma
│   └── canal_credenciais.py # Fernet (cryptography). Chave em FLUXI_SECRET_KEY.
├── webchat/            # Rotas /chat/<id>: página HTML + POST /enviar + GET /stream (SSE)
├── sessao/             # Sessão = canal conectado. Gerenciador global de CanalClient.
├── agente/             # Agente: persona, ferramentas, ciclo LLM-tools.
├── coding_agent/       # Agente especial #code com sandbox.
├── mensagem/           # ★ Pipeline central. processar_evento_canal() roteia por plataforma.
├── ferramenta/         # Function-calling: APIs, Python code, wizard visual.
├── skill/              # Pacotes de instruções + ferramentas reutilizáveis.
├── rag/                # ChromaDB + ingest (PDF/DOCX/MD).
├── mcp_client/         # Cliente MCP (Model Context Protocol).
├── llm_providers/      # Cadastro de provedores LLM (OpenAI, Ollama, etc.)
├── audio/              # Transcrição (Groq/OpenAI/OpenRouter) — agnóstico de canal.
├── metrica/            # Tokens, latência, contagens.
├── log/                # Sistema de logging estruturado (fluxi_log).
├── internal_sandbox/   # Sandbox isolado por agente (filesystem + shell + Playwright).
├── agendamento/        # Tarefas agendadas via APScheduler.
├── templates/          # Jinja2. Cada módulo tem sua subpasta.
├── static/             # CSS/JS estáticos (mínimo — preferimos CSS inline em templates).
├── data/               # SQLite + uploads (volumes Docker).
├── main.py             # Bootstrap, registro de routers, migrations aditivas.
└── database.py         # Base, engine, SessionLocal, get_db().
```

⭐ = "ler antes de mexer em fluxo de mensagens".

---

## Convenções obrigatórias

### Estilo Python (ver skills `codigo-para-agente` e `padrao-modulo`)

- **Funções curtas**, foco único, idealmente 4–20 linhas
- **Arquivos abaixo de 300 linhas** quando possível
- **Tipos explícitos** com sintaxe 3.10+: `dict[str, int]`, `X | None`
- **Nomes grep-aveis**: `criar_agente_padrao`, não `helper` ou `process_data`
- **Guard clauses + early return**, evitar aninhamento profundo
- **Erros com contexto**: `ValueError(f"telefone inválido: {tel!r}")` em vez de `ValueError("inválido")`
- **Comentários explicam o *porquê***, não o *o quê*. Inclua proveniência: "neonize dispara MessageEv 2x — dedup é workaround"
- **Dependency Injection**: receber db, logger, http client por `Depends` ou parâmetro; nunca instanciar dentro da função

### Estrutura de módulo (ver skill `fastapi-modular`)

Cada domínio tem (quando aplicável):

```
modulo/
├── __init__.py
├── modulo_model.py         # SQLAlchemy: Base + classes
├── modulo_schema.py        # Pydantic: validação de entrada/saída
├── modulo_service.py       # Lógica de negócio (stateless, métodos estáticos OK)
├── modulo_router.py        # API REST (se houver) — JSON
├── modulo_frontend_router.py # Páginas HTMLResponse + form POST
└── README.md               # Resumo + decisões locais
```

Templates correspondentes em `templates/modulo/`.

### Regras de UI

- **Não use JS framework.** Jinja2 SSR. Pequenos scripts vanilla são OK quando necessário (drag-drop, MediaRecorder)
- **Toda interação web por navegação ou form POST.** Exceção: webchat (SSE + fetch)
- **CSS inline em template** quando localizado; CSS global em `static/css/`
- **Variáveis CSS já existem** (`--color-primary`, `--color-text`, etc.) — siga
- **Dark mode** já implementado — não quebre

### Banco de dados

- **Migrations aditivas no `startup_event`** de `main.py` — adicionar colunas com defaults; **nunca renomear** ou dropar
- **Não use Alembic** por enquanto (padrão atual é SQL direto via `inspect()` + `ALTER TABLE` idempotente)
- **Importe o `*_model.py` em `main.py` antes de `criar_tabelas()`** pra registrar na `Base.metadata`
- **`get_db()`** sempre via `Depends` em rotas; em threads/background, use `SessionLocal()` direto e feche no `finally`

### Segurança

- **Senhas:** bcrypt via `auth.auth_service.hash_senha`/`verificar_senha`. Nunca armazenar plain.
- **Credenciais de canais** (bot_token, etc.): cifrar com `canal.canal_credenciais.criptografar()`. Chave em `FLUXI_SECRET_KEY` (Fernet).
- **Inputs do usuário:** sempre passar por `security.sanitize_user_input()` antes de exibir/persistir.
- **Tokens em logs:** logger do `httpx` printa URL completa — pra Telegram isso vaza o bot_token. Filtre em produção.
- **`open_redirect`:** ao usar `?next=`, valide com helper local; só aceite paths que começam com `/` e não com `//`.

### Telegram + dedup

Telegram `message_id` é incremental **por chat** (não único global). Chave de dedup correta: `(plataforma, chat_id, mensagem_id_externo)`. Veja `MensagemService.processar_evento_telegram`.

### WhatsApp + JID

Manter `chat_id` como string. Adapter WA aceita `"user"` ou `"user@server"`. Default server: `s.whatsapp.net`. Casos LID já são raros — só warning log.

### Web Chat + SSE

- Cada visitante gera UUID em `localStorage`, enviado como `client_id` em todo request
- Adapter mantém `Dict[chat_id, asyncio.Queue]`; SSE consome dessa fila
- Queues inativas devem ser limpas (`canal.limpar_fila_inativa`) quando o browser fecha
- Mensagens não persistem se chegam offline — não é WebSocket persistente

---

## Comandos pra rodar

```bash
# Build e start
docker compose up -d --build

# Logs em tempo real
docker logs whatsapp-ai-agent-fluxi-fluxi-1 -f

# Healthcheck
curl http://localhost:10000/health

# Acessar shell dentro do container
docker exec -it whatsapp-ai-agent-fluxi-fluxi-1 bash

# Inspecionar SQLite
docker exec whatsapp-ai-agent-fluxi-fluxi-1 python -c "
import sqlite3; c = sqlite3.connect('/app/data/fluxi.db')
for r in c.execute('PRAGMA table_info(sessoes)'): print(r)"
```

**Sem suite de testes ainda.** Quando criar, prefira `pytest` headless em `tests/`.

---

## Variáveis de ambiente principais

| Var | Função |
|-----|--------|
| `DATABASE_URL` | SQLAlchemy URL. Default: `sqlite:///./data/fluxi.db` |
| `HOST_PORT` | Porta no host (default 10000). Container interno é 8000 fixo. |
| `SESSION_SECRET_KEY` | Cookie de sessão (itsdangerous) |
| `FLUXI_SECRET_KEY` | Fernet pra cifrar bot_tokens e outras credenciais |
| `FLUXI_ALLOW_SIGNUP` | `true` libera /signup; default `false` após o primeiro user |
| `FLUXI_ADMIN_RESET_EMAIL` + `FLUXI_ADMIN_RESET_PASSWORD` | Reset de senha no startup (remover depois!) |
| `INTERNAL_SANDBOX_ROOT` | Raiz do sandbox interno (Coding Agent) |

---

## Anti-padrões

- ❌ **Importar `neonize` ou `telegram` fora de `canal/`**. Use a interface `CanalClient`.
- ❌ **Chamar API REST do JS** em rotas administrativas. Use form POST.
- ❌ **`Base.metadata.drop_all`** ou recriar tabelas. Migrations aditivas, idempotentes.
- ❌ **Renomear colunas** existentes. Adicione coluna nova + backfill + deprecate.
- ❌ **Hardcode `whatsapp` ou `sessao.telefone`** em código de pipeline. Use `sessao.plataforma` e `canal.enviar_*`.
- ❌ **Salvar senha em texto** ou bot_token sem cifrar.
- ❌ **Adicionar pasta `node_modules`** ou bundler. Frontend é Jinja2 + vanilla.
- ❌ **Skip pre-commit hooks** com `--no-verify`.

---

## Onde olhar quando algo trava

| Sintoma | Onde investigar |
|---------|-----------------|
| Telegram "trava" no Ligar | `canal/canal_telegram.py`, logs grep por `TG[<id>]`; quase sempre token inválido ou credenciais cifradas com chave que mudou |
| Web Chat sem resposta | `webchat/webchat_router.py` SSE endpoint; verificar fila com `canal.obter_ou_criar_fila` |
| Mensagens WA duplicadas | Dedup em `CanalWhatsAppClient._dedup` (deque + set); neonize dispara 2x às vezes |
| Imagem não renderiza | `mensagem/mensagem_service.py` salvar_imagem — `uploads/sessao_X/<chat_id>/` |
| Auth não redireciona | `auth/auth_dependencies.py` — checar ordem de middleware (SessionMiddleware antes de AuthMiddleware? não — `add_middleware` aplica em ordem reversa) |
| QR Code não aparece | `CanalWhatsAppClient._registrar_handlers` callback `@cliente.qr` |
| Coding agent não roda | `coding_agent/coding_service.py`; precisa de loop FastAPI capturado em `MensagemService.set_fastapi_loop` |

---

## Quando criar novo canal (ex.: Discord, Slack)

1. Criar `canal/canal_discord.py` implementando o Protocol `CanalClient` ([`canal/canal_base.py`](canal/canal_base.py))
2. Adicionar `Plataforma.DISCORD = "discord"` em `canal_base.py`
3. Adicionar branch em `canal_factory.criar_canal()`
4. Construir `EventoMensagem` no callback; deixar `raw` com payload original
5. Mídia: baixar bytes ANTES de despachar pro callback (pra pipeline ser agnóstico)
6. Adicionar opção no `<select name="plataforma">` em `templates/sessao/form.html`
7. Bloco condicional na lista (`templates/sessao/lista.html`) e detalhes
8. **Sem precisar mexer em `MensagemService` ou `AgenteService`** se o adapter respeitar a interface

---

## Convenções de PR / commit

- Mensagens curtas, imperativo: `auth: adicionar reset de senha via env`
- Não commitar `.env`, `data/fluxi.db`, `sessoes/*.db`, `uploads/`
- Migrations: incluir bloco no `startup_event` se for aditiva; abrir issue se precisar destrutiva
- Atualizar este `AGENTS.md` se adicionar novo módulo ou mudar convenção

---

**Quando em dúvida sobre uma decisão, prefira a opção que mantém o sistema funcionando pra usuários atuais sobre a opção que é mais limpa em teoria.**
