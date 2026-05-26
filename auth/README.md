# `auth/` — Login, signup, proteção de rotas

Sistema de autenticação **single-tenant**: todos os usuários logados veem os mesmos dados (sessões, agentes, conversas, RAGs, MCPs). O campo `role` já existe pra evoluir pra multi-tenant sem migration nova.

## Componentes

| Arquivo | Responsabilidade |
|---------|------------------|
| [`auth_model.py`](auth_model.py) | Tabela `users` (id, email, nome, senha_hash, ativo, role, criado_em, ultimo_login) |
| [`auth_schema.py`](auth_schema.py) | `UserSignup`, `UserLogin`, `UserPublico` (Pydantic v2) |
| [`auth_service.py`](auth_service.py) | Hash bcrypt, autenticação, criação, reset via env |
| [`auth_dependencies.py`](auth_dependencies.py) | `obter_usuario_atual`, `exigir_usuario`, `AuthMiddleware` |
| [`auth_frontend_router.py`](auth_frontend_router.py) | Rotas `/login`, `/signup`, `/logout` |

Templates: [`../templates/auth/`](../templates/auth/) — base, login, signup, signup_fechado.

## Fluxo

```
Browser anônimo                  AuthMiddleware                  Handler
─────────────                    ──────────────                  ───────
GET /sessoes  ────────────────►  user_id no cookie? não  ─────►  redirect 303 /login?next=/sessoes
POST /sessoes ────────────────►  user_id no cookie? não  ─────►  401 JSON
GET /chat/9   ────────────────►  rota pública (em ROTAS_PUBLICAS) ─► handler
GET /login    ────────────────►  rota pública             ─────►  handler
                                                                  ↓
                                                              renderiza tela ou
                                                              redireciona /signup
                                                              se DB vazio
```

## Bootstrap do primeiro user

- Se a tabela `users` está vazia, `GET /login` redireciona pra `GET /signup?bootstrap=1`
- O signup mostra banner avisando que "você será admin"
- Após criar, `role='admin'` é setado automaticamente e auto-login é feito
- A partir daí, **novos signups dependem de `FLUXI_ALLOW_SIGNUP=true`** no `.env` (default: bloqueado)

Implementação: `auth_service.signup_permitido(db)` — retorna `True` se DB vazio OU se env var liga.

## Reset de senha via `.env`

Single-tenant + sem SMTP → o caminho mais simples e seguro é reset disparado por variável de ambiente no startup. Quem tem acesso ao servidor pode resetar.

No `.env`:

```env
FLUXI_ADMIN_RESET_EMAIL=jhona@example.com
FLUXI_ADMIN_RESET_PASSWORD=NovaSenhaForte123
```

No startup, [`main.py`](../main.py) chama `auth_service.resetar_senha_via_env(db)`:

1. Lê as 2 vars
2. Se ambas existem e a senha tem ≥ 8 chars, procura o user pelo email
3. Troca o hash
4. Loga `WARNING` lembrando de remover as 2 linhas do `.env`

Se você esquecer de remover, a senha é sobrescrita a cada restart — não é destrutivo, mas perde qualquer mudança feita pelo painel.

## Segurança

- **Senhas:** bcrypt com salt automático (`bcrypt.gensalt()`). Mínimo 8 chars, validado tanto no Pydantic quanto no template (`minlength`)
- **Cookies:** `same_site=lax`, `max_age=7 dias`. Em produção: setar `https_only=True` (hoje é `False` pra dev local)
- **Email enumeration:** o handler de login não diferencia "email inexistente" de "senha errada" — sempre retorna a mesma mensagem
- **Open redirect:** `?next=` validado por `_destino_seguro()` — só aceita paths começando com `/` e não com `//`
- **CSRF:** sessão via cookie `same_site=lax` protege parcialmente. Pra hardening, adicionar token CSRF nas forms — não feito ainda

## Rotas públicas (sem autenticação)

Listadas em `ROTAS_PUBLICAS` em [`auth_dependencies.py`](auth_dependencies.py):

- `/login`, `/signup`, `/logout`
- `/health` (k8s/docker probe)
- `/static/`, `/favicon`
- `/chat/` (**Web Chat público — clientes finais do bot não têm conta no Fluxi**)
- `/docs`, `/openapi.json`, `/redoc` (FastAPI)

Adicionar novas rotas públicas com cuidado: revisar se não vaza dados ou ações privilegiadas.

## Como exigir admin numa rota

```python
from auth.auth_dependencies import obter_usuario_atual
from fastapi import Depends, HTTPException, Request

@router.get("/usuarios")
def listar_usuarios(request: Request, db: Session = Depends(get_db)):
    user = obter_usuario_atual(request, db)
    if user is None or user.role != "admin":
        raise HTTPException(403, "apenas admin")
    ...
```

## Multi-tenant futuro

Pra evoluir pra multi-tenant:

1. Adicionar coluna `user_id` (FK) nas tabelas `sessoes`, `agentes`, `mensagens`, etc.
2. Filtrar todas as queries por `user_id` do `obter_usuario_atual()`
3. Manter `role='admin'` com acesso global
4. UI: tela de gestão de usuários (admin)

Não é trabalho pequeno (~10 tabelas, ~50 queries) — guardar pra um sprint dedicado.
