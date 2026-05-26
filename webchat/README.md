# `webchat/` — Página pública de chat (`/chat/<sessao_id>`)

Web Chat embutido no Fluxi. Cada `Sessao` com `plataforma='webchat'` ganha uma URL pública (sem login) que qualquer pessoa pode abrir e conversar com o agente.

## Como funciona

```
Visitante (browser anônimo)            FastAPI                       Pipeline
─────────────────────────             ───────                        ────────
GET /chat/<id>                  ────► renderiza chat.html
                                      EventSource(/stream)   ◄──── inicia SSE
POST /chat/<id>/enviar
  multipart: texto / audio / imagem
                                ────► EventoMensagem
                                      MensagemService.processar_evento_canal
                                                                 ────► agente
                                                                       ↓
                                ◄──── canal.enviar_texto(chat_id, ...)
                                      SSE push
              ◄────── data: {"tipo":"texto","texto":"..."}
```

## Identidade do visitante

Browser gera **UUID v4 no `localStorage`** na primeira visita, salva em `fluxi_webchat_client_id`. Esse UUID é o `chat_id` enviado em todo POST/GET. Persistente entre reloads → histórico aparece quando volta.

Sem login. Sem cookie do servidor. Sem tracking além do necessário pro chat funcionar.

## Endpoints

| Método | Rota | Função |
|--------|------|--------|
| GET    | `/chat/{sessao_id}` | Renderiza `templates/webchat/chat.html` |
| GET    | `/chat/{sessao_id}/historico?client_id=…` | Últimas N mensagens em JSON |
| GET    | `/chat/{sessao_id}/stream?client_id=…` | SSE — empurra eventos da fila do client_id |
| GET    | `/chat/{sessao_id}/imagem/{mensagem_id}` | Serve imagem persistida (Mensagem.conteudo_imagem_path) |
| POST   | `/chat/{sessao_id}/enviar` | Recebe texto / áudio / imagem (multipart) |

Todas em **rota pública** (lista em [`../auth/auth_dependencies.py`](../auth/auth_dependencies.py) `ROTAS_PUBLICAS`).

## Eventos SSE (server → browser)

JSON serializado em `data:`:

```json
{ "tipo": "digitando", "ativo": true }
{ "tipo": "texto",     "texto": "Olá!" }
{ "tipo": "imagem",    "base64": "...", "mime": "image/jpeg", "legenda": "" }
{ "tipo": "audio",     "base64": "...", "mime": "audio/ogg", "ptt": true }
{ "tipo": "video",     "base64": "...", "mime": "video/mp4", "legenda": "" }
{ "tipo": "documento", "base64": "...", "nome": "arquivo.pdf" }
```

Keep-alive (`: keep-alive`) a cada 20s pra Nginx/proxy não derrubar.

## UI (`templates/webchat/chat.html`)

Página única, vanilla JS. Princípios aplicados:

- **Padrão WhatsApp/Telegram** — bolhas alinhadas, avatares, "digitando..."
- **Input multimodal** — textarea autoresize + botão anexo + botão mic + enviar
- **Gravação de áudio** com timer e ondas pulsantes; cancelar/enviar grandes e claros
- **Drag-and-drop** de imagem em qualquer ponto da janela (overlay roxo)
- **Dark mode** automático via `prefers-color-scheme`
- **Sem dependências externas** (só Font Awesome via CDN)

## Mídia

- **Áudio**: browser usa `MediaRecorder` com `audio/webm;codecs=opus` (fallback `audio/webm`). Upload via multipart. O `TranscriptionService` (já agnóstico) converte e transcreve
- **Imagem**: input file ou drag-drop. JPEG/PNG/GIF/WebP. Salvas em `uploads/sessao_<id>/<chat_id>/img_*.jpg` com EXIF removido
- **Resposta com mídia**: o servidor empurra base64 inline via SSE. Ok pra imagens pequenas; pra grandes, considerar URL futura

## Cenários adversariais

| Problema | Mitigação atual |
|----------|----------------|
| Custo descontrolado (URL público + LLM caro) | Sessão pode ser desativada (`ativa=false`). Sem rate limit ainda. |
| XSS na resposta do agente | Texto é setado via `textContent` (não `innerHTML`). Markdown não é renderizado |
| Cliente fecha browser → fila acumula | `coletar_filas_zumbis(timeout=600s)` + `limpar_fila_inativa()`. Chamado quando? Hoje só ao fechar SSE — pode evoluir pra task periódica |
| Mesma sessão atendendo 1000 visitantes | Filas em dicionário in-memory. Funciona pra dezenas; pra centenas+ trocar por Redis pub/sub |
| Cliente envia bytes maliciosos | `validate_upload_file` no `salvar_imagem`; áudio passa pelo `TranscriptionService` que valida tipo |

## Habilitar / desabilitar

Apenas criando ou desativando uma `Sessao` com `plataforma='webchat'` em `/sessoes`. A URL pública só responde se `sessao.ativa=true`.

## Quando NÃO usar webchat

- Conversa precisa atravessar reload do servidor → use Telegram (mensagens persistem no servidor deles)
- Múltiplos dispositivos do mesmo usuário → cada um vira `chat_id` diferente (UUID por browser)
- App nativo móvel → use Telegram (push notifications nativas) ou WhatsApp
