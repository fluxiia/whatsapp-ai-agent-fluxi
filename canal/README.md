# `canal/` — Abstração multi-canal

Esta camada é o que permite o Fluxi atender em WhatsApp, Telegram e Web Chat com o **mesmo pipeline de agente**. Nada acima desta camada (`mensagem/`, `agente/`, `coding_agent/`) sabe qual canal está em uso — eles falam com `CanalClient`.

## Componentes

| Arquivo | Responsabilidade |
|---------|------------------|
| [`canal_base.py`](canal_base.py) | `CanalClient` (Protocol) + `EventoMensagem` (dataclass normalizado) + enums `Plataforma`, `StatusConexao`, `TipoMidia` |
| [`canal_whatsapp.py`](canal_whatsapp.py) | Adapter neonize. Inclui shims (`send_message`, `send_image`, ...) pra compat com código antigo |
| [`canal_telegram.py`](canal_telegram.py) | Adapter python-telegram-bot v21+. Long polling em thread+loop dedicados por sessão |
| [`canal_webchat.py`](canal_webchat.py) | Sem rede externa. Mantém `Dict[chat_id, asyncio.Queue]` consumido por SSE no `webchat/` |
| [`canal_factory.py`](canal_factory.py) | Decide qual adapter instanciar a partir de `sessao.plataforma` |
| [`canal_credenciais.py`](canal_credenciais.py) | Fernet (cryptography) — cifra/decifra `Sessao.credenciais` |

## Modelo mental

```
Sessao (DB)            CanalClient (memória)         Pipeline
─────────              ──────────────────────         ───────
plataforma='whatsapp'  CanalWhatsAppClient            on_mensagem(EventoMensagem)
plataforma='telegram'  CanalTelegramClient    ────►   ─────────────────────────►
plataforma='webchat'   CanalWebChatClient
```

Toda mensagem que entra é normalizada em `EventoMensagem`:

```python
@dataclass
class EventoMensagem:
    plataforma: Plataforma
    sessao_id: int
    mensagem_id_externo: str   # msg_id da plataforma
    chat_id: str               # telefone (WA), chat.id (TG), UUID (web)
    remetente_id: str
    remetente_nome: str | None
    tipo: TipoMidia            # TEXTO | AUDIO | IMAGEM | VIDEO | DOCUMENTO | ...
    texto: str
    midia_bytes: bytes | None
    midia_mime: str | None
    midia_nome: str | None
    raw: Any                   # payload original — use com cuidado (acopla)
    extras: dict
```

E toda saída passa por:

```python
canal.enviar_texto(chat_id, texto)
canal.enviar_imagem(chat_id, bytes, legenda="")
canal.enviar_audio(chat_id, bytes, ptt=True)
canal.enviar_video(chat_id, bytes, legenda="")
canal.enviar_documento(chat_id, bytes, nome_arquivo="x.pdf")
```

## Criando um novo canal

Veja o passo-a-passo em [`../AGENTS.md`](../AGENTS.md) ("Quando criar novo canal"). TL;DR:

1. Cria `canal/canal_xyz.py` implementando o Protocol `CanalClient`
2. Adiciona `Plataforma.XYZ` em `canal_base.py`
3. Adiciona branch em `canal_factory.criar_canal()`
4. UI: opção no `<select>` do form de sessão + bloco condicional na lista/detalhes

Quando o adapter respeita a interface, **nenhuma mudança em `mensagem/` ou `agente/` é necessária**.

## Cuidados específicos

### WhatsApp (neonize)
- Neonize dispara `MessageEv` 2× pra algumas mensagens — o adapter tem dedup local por `msg_id` (deque + set, maxlen 1000)
- A primeira janela após conectar é ignorada (history sync) — `history_sync_delay` configurável
- Logout → o adapter remove `sessoes/sessao_X.db` automaticamente

### Telegram (PTB v21)
- `message_id` é incremental **por chat**, não global → chave de dedup é `(sessao, chat_id, mensagem_id_externo)`
- Polling duplo no mesmo bot_token retorna **409 Conflict** — `sessao_service.criar` bloqueia bot_token já em uso
- O loop async vive em thread dedicada (`asyncio.new_event_loop()`); envio de fora usa `run_coroutine_threadsafe`

### Web Chat
- Sem credenciais externas → "conectado" assim que o adapter é criado
- Filas com chat_ids zumbis (browser fechou) acumulam se ninguém chamar `coletar_filas_zumbis` / `limpar_fila_inativa`
- Mensagens só são entregues a quem está com a SSE aberta — não há retry/replay; histórico vem de `/chat/<id>/historico`

### Credenciais
- `Sessao.credenciais` é texto cifrado com Fernet
- Chave: `FLUXI_SECRET_KEY` em env. Se não definida, derivação fallback do hostname — **muda quando o container é recriado**, invalidando todos os tokens
- **Sempre defina `FLUXI_SECRET_KEY` em produção**

## Status do refactor

A camada foi introduzida em maio/2026 sem quebrar o WhatsApp atual. Hoje:

- ✅ Pipeline WA usa `EventoMensagem.raw` pra manter código legado funcionando
- ✅ Pipeline TG já usa só campos genéricos
- ⏳ Pipeline WA pode ser migrado pra usar só campos genéricos (refactor maior, ~600 linhas)
- ⏳ Tools de mídia outbound do agente (`_enviar_arquivo_whatsapp`) ainda têm o nome WA — funcionam pelos shims
