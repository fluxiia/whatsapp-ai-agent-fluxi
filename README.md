<div align="center">

<img src="data/logo_fluxi.png" alt="Fluxi.IA" width="200">

### Plataforma open-source para criar agentes de IA — self-hosted, multi-canal, com ferramentas, skills, RAG e MCP.

![Dashboard](data/screenshot01.png)

</div>

---

## 🤔 O que é o Fluxi?

Fluxi é uma **plataforma de agentes de IA** que você roda na sua própria máquina. Cada agente é configurável: papel, objetivo, modelo de LLM, ferramentas que ele pode chamar, bases de conhecimento que ele consulta, servidores MCP que estende as capacidades, skills empacotadas, e por qual canal ele conversa.

Você usa pra **o que precisar**:

- **Assistente pessoal** — agenda, finanças, segunda memória, pesquisa
- **Automação interna** — DevOps, queries em banco, IoT, integração com APIs internas
- **Atendimento** — suporte, qualificação de leads, vendas conversacionais
- **Estudo, escrita, criação** — tutor personalizado, escritor assistente, curadoria
- **Agentes de código** — o agente coding (`#code`) tem sandbox próprio e **se auto-melhora**: cria novas ferramentas, novas skills, edita o próprio projeto

E tudo isso sem mensalidade de SaaS, sem expor dados a terceiros e com controle total do comportamento.

---

## 🧩 Como o agente é montado

Cada agente combina o que você liga nele:

| Peça | O que é | Onde configurar |
|------|---------|----------------|
| **Persona** | Papel, objetivo, políticas, público, restrições | `/agentes/{id}` |
| **Modelo** | LLM que pensa (local ou nuvem) | `/provedores-llm/` |
| **Ferramentas** | Função-calling: chama APIs, executa Python, busca CEP, etc. | `/ferramentas` ou wizard |
| **Skills** | Pacotes reutilizáveis de instrução + ferramentas | `/skills` |
| **RAG** | Bases de conhecimento (PDFs, docs, sites) consultadas no contexto | `/rags` |
| **MCP** | Servidores externos que adicionam capacidades novas em runtime | `/mcp` |
| **Canal** | Como o agente conversa: WhatsApp, Telegram ou Web | `/sessoes` |

Você combina como quiser. Um agente pode ter 0 ou N de cada coisa.

---

## 🤖 Agente Coding — auto-melhoramento

Prefixo `#code` em qualquer canal aciona um **agente especializado** com sandbox próprio (workspace isolado, shell, edição de arquivos). Ele entende a base de código do próprio Fluxi e é capaz de:

- Criar **novas ferramentas** (function-calling) para você
- Empacotar comportamento em **novas skills**
- Configurar **servidores MCP** e RAG
- Editar próprio código do projeto sob supervisão

Na prática você pede em linguagem natural — _"crie uma ferramenta que consulta meu Postgres na tabela `pedidos`"_ — e ele implementa, testa e disponibiliza. É o caminho mais rápido pra estender o sistema sem sair do chat.

---

## 🔌 Canais suportados

| Canal | Como conecta | Quando usar |
|-------|-------------|-------------|
| **WhatsApp** | QR Code (via neonize / whatsmeow) | Conversa onde a maioria das pessoas já está |
| **Telegram** | Bot Token do BotFather | Mais estável, sem risco de banimento, API oficial |
| **Web Chat** | URL pública embutida (`/chat/<id>`) | Embed no seu site, sem instalar nada |

Os três compartilham a **mesma engine** — agente, ferramentas, skills, RAG, MCP. Você configura uma vez e o canal vira só um detalhe de transporte.

---

## 🚀 O que você pode construir

O Fluxi combina **WhatsApp + RAG + Tools + MCP + IA** (local ou na nuvem). Isso abre possibilidades que vão muito além de um chatbot simples.

### 👤 Assistentes Pessoais

| Caso de Uso | Como Funciona |
|-------------|---------------|
| **Controle Financeiro** | Conecte seu sistema financeiro via API. Lance gastos, consulte saldos, gere relatórios - tudo pelo WhatsApp. |
| **Agenda Inteligente** | Integre com Google Calendar. Marque reuniões, receba lembretes, reorganize compromissos por voz. |
| **Segunda Memória** | Adicione documentos, anotações, PDFs. Pergunte "o que combinei com o João?" e a IA busca no seu RAG. |
| **Pesquisador Pessoal** | Conecte Serper.dev, Brave Search ou Jina AI. Peça pesquisas e receba resumos no WhatsApp. |

### 🏢 Automação de Negócios

| Caso de Uso | Como Funciona |
|-------------|---------------|
| **Suporte 24/7** | RAG com manuais + ferramentas de consulta. Responde dúvidas técnicas mesmo fora do horário. |
| **Qualificação de Leads** | Agente coleta informações, consulta CRM via API, agenda reuniões automaticamente. |
| **Pedidos por WhatsApp** | Integre com seu ERP/sistema de pedidos. Cliente faz pedido conversando naturalmente. |
| **Consulta de Estoque** | Ferramenta consulta banco de dados. "Tem o produto X?" → resposta em tempo real. |

### 🔧 Integrações Técnicas

| Caso de Uso | Como Funciona |
|-------------|---------------|
| **DevOps no Bolso** | MCP com GitHub + servidor. Crie issues, veja PRs, faça deploy - pelo WhatsApp. |
| **Consultas SQL** | Conecte PostgreSQL/MySQL via MCP. Pergunte em linguagem natural, receba dados. |
| **Monitoramento** | Ferramenta consulta métricas. "Como está o servidor?" → status em tempo real. |
| **IoT e Automação** | APIs REST para controlar dispositivos. "Acenda a luz da sala" via WhatsApp. |

### 🎨 Uso Criativo

| Caso de Uso | Como Funciona |
|-------------|---------------|
| **Tutor Personalizado** | RAG com material de estudo + modelo potente (GPT-4, Claude). Tire dúvidas 24h. |
| **Escritor Assistente** | Envie ideias por áudio, IA transcreve e desenvolve. Revise documentos pelo WhatsApp. |
| **Tradutor Contextual** | RAG com glossários específicos. Tradução que entende o contexto do seu negócio. |
| **Curador de Conteúdo** | Busca na web + RAG. "Novidades sobre X" → resumo personalizado. |

---

## 🛠️ Crie suas próprias integrações

Você não está limitado às ferramentas prontas. O Fluxi foi feito para desenvolvedores conectarem qualquer coisa.

### Via MCP (Model Context Protocol)

```
Crie um servidor MCP em qualquer linguagem e conecte ao Fluxi.
O agente terá acesso às suas ferramentas automaticamente.
```

Exemplos de MCPs que você pode criar:
- Consulta ao seu banco de dados interno
- Integração com seu ERP/CRM
- Controle de dispositivos IoT
- Acesso a APIs internas da empresa

#### Exemplo: MCP de Dieta

O projeto inclui um exemplo funcional em `exemplo_mcp/dieta_mcp.py`:

**1. Inicie o servidor MCP:**
```bash
cd exemplo_mcp
python dieta_mcp.py
```

**2. Configure no Fluxi:**

Acesse `http://localhost:8000/mcp/agente/{id}/json-config` e adicione:

```json
{
  "mcpServers": {
    "dieta": {
      "serverUrl": "http://localhost:8002/sse"
    }
  }
}
```

**3. Use pelo WhatsApp:**
```
Você: Registra meu almoço: arroz, feijão e frango, 650 calorias
IA: Refeição registrada! Almoço: arroz, feijão e frango (650 kcal)

Você: Quanto já comi hoje?
IA: TOTAL DO DIA: 1200 kcal

Você: Como estou na meta?
IA: Consumido: 60% da meta. Restante: 800 kcal
```

Veja mais detalhes em [`exemplo_mcp/README.md`](exemplo_mcp/README.md)

### Via API REST (Ferramentas)

```
Use o Wizard visual para criar ferramentas que chamam suas APIs.
Sem código - configure método, headers, body e mapeie a resposta.
```

O Wizard suporta:
- Qualquer método HTTP (GET, POST, PUT, DELETE)
- Autenticação (Bearer, API Key, Basic)
- Variáveis dinâmicas do contexto da conversa
- Transformação de resposta (JsonPath)

### Via Código Python

```
Para lógicas complexas, crie ferramentas CODE que executam Python.
Ideal para cálculos, validações ou transformações de dados.
```

---

## 🧠 Escolha sua IA

| Opção | Privacidade | Custo | Performance |
|-------|-------------|-------|-------------|
| **Ollama / LM Studio** | Total - roda local | Grátis | Depende do hardware |
| **llama.cpp** | Total - roda local | Grátis | Otimizado para CPU |
| **OpenRouter** | Dados passam pela API | Pay-per-use | Acesso a 200+ modelos |
| **OpenAI (GPT-4)** | Dados passam pela API | Pay-per-use | Estado da arte |
| **Anthropic (Claude)** | Dados passam pela API | Pay-per-use | Excelente para tarefas longas |
| **Google (Gemini)** | Dados passam pela API | Pay-per-use | Bom custo-benefício |

**Dica**: Use modelo local para conversas sensíveis e modelos na nuvem para tarefas complexas. O Fluxi suporta fallback automático.

---

## ⚡ Funcionalidades

| Recurso | Descrição |
|---------|-----------|
| **Multi-canal** | WhatsApp, Telegram e Web Chat — mesma engine de agente |
| **Autenticação** | Login obrigatório no painel; primeiro usuário vira admin |
| **Múltiplos Agentes** | Crie agentes especializados e alterne entre eles |
| **RAG (Documentos)** | Adicione bases de conhecimento e faça perguntas |
| **Ferramentas Customizadas** | Conecte APIs com wizard visual, sem código |
| **MCP Protocol** | Integre ferramentas externas (GitHub, databases, etc) |
| **LLMs Locais** | Use Ollama, LM Studio ou llama.cpp - 100% offline |
| **LLMs na Nuvem** | OpenRouter, OpenAI, Anthropic, Google - sua escolha |
| **Comandos** | `#ativar`, `#desativar`, `#limpar`, `#status`, `#ajuda` |
| **Transcrição** | Áudios virem texto (WhatsApp, Telegram voice, gravação web) |
| **Coding Agent** | Prefixo `#code` aciona agente com sandbox dedicado |
| **Métricas** | Acompanhe mensagens, tokens, tempo de resposta |
| **Dark Mode** | Interface clara ou escura |

---

## 📸 Screenshots

<div align="center">

| Dashboard | Sessão WhatsApp |
|-----------|-----------------|
| ![Dashboard](data/screenshot01.png) | ![Sessão](data/screenshot05.png) |

| Wizard de Ferramentas | Provedores LLM |
|-----------------------|----------------|
| ![Ferramentas](data/screenshot02.png) | ![LLM](data/screenshot03.png) |

| MCP Clients |
|-------------|
| ![MCP](data/screenshot04.png) |

</div>

---

## 🏁 Como Começar

### Requisitos

- **Docker** + Docker Compose
- **Um canal** pra atender: WhatsApp (número), Telegram (bot do BotFather) ou só Web Chat público
- **Um provedor LLM** (local com Ollama/LM Studio, ou nuvem)

### 1. Clone e configure

```bash
git clone https://github.com/jjhoow/fluxi.git
cd fluxi
cp config.example.env .env
```

Gere uma chave Fernet pro `.env` (cifra credenciais de canais):

```bash
python -c "from cryptography.fernet import Fernet; print('FLUXI_SECRET_KEY=' + Fernet.generate_key().decode())" >> .env
```

### 2. Inicie com Docker

```bash
docker compose up -d --build
```

Por padrão escuta em **http://localhost:10000** (o host port é `HOST_PORT`, default `10000`; container interno em 8000).

### 3. Crie sua conta admin

1. Abra `http://localhost:10000`
2. Você é redirecionado pra `/signup?bootstrap=1` — o primeiro usuário vira **admin**
3. Cadastre nome, e-mail e senha (mín. 8 caracteres)

### 4. Configure um provedor LLM

Em `/provedores-llm/` cadastre OpenRouter, OpenAI, Ollama, LM Studio ou outro.

### 5. Crie uma sessão (canal) e um agente

- Em `/sessoes/nova` escolha o canal (WhatsApp, Telegram ou Web Chat)
- Para WhatsApp: clique **"Ligar WhatsApp"** e escaneie o QR
- Para Telegram: cole o bot_token do **@BotFather** e clique **"Ligar Bot Telegram"**
- Para Web Chat: pronto — abre `/chat/<id>` no navegador
- Em `/agentes/{id}` defina persona (papel, objetivo, políticas), modelo LLM e ligue as ferramentas/skills/RAGs/MCPs que quiser

**Pronto.** Mande mensagem pelo canal que escolheu. Use `#code <pedido>` se quiser que o agente coding crie novas ferramentas/skills pra você.

### Esqueci a senha do admin

Edite o `.env`, descomente as 2 linhas:

```env
FLUXI_ADMIN_RESET_EMAIL=seu@email.com
FLUXI_ADMIN_RESET_PASSWORD=NovaSenhaForte123
```

Reinicie o container (`docker compose restart`), faça login com a nova senha e **remova essas 2 linhas do `.env`** (senão a senha é sobrescrita a cada restart).

---

## 🔩 Stack Técnica

| Camada | Tecnologia |
|--------|------------|
| **Backend** | Python 3.11+, FastAPI, SQLAlchemy, Pydantic v2 |
| **Frontend** | Jinja2 SSR (zero JS framework), CSS variáveis, drag-drop nativo |
| **Banco de Dados** | SQLite (padrão); PostgreSQL via `DATABASE_URL` |
| **Vetorial** | ChromaDB |
| **WhatsApp** | Neonize (binding Python pro whatsmeow / Go) |
| **Telegram** | python-telegram-bot v21+ (long polling) |
| **Web Chat** | Server-Sent Events (SSE) + MediaRecorder API |
| **Auth** | Session cookie (itsdangerous) + bcrypt; middleware de proteção |
| **Cripto credenciais** | Fernet (`cryptography`) — bot_tokens cifrados em repouso |
| **LLM** | OpenRouter, OpenAI, Ollama, LM Studio, Anthropic, Google |

---

## 📂 Arquitetura

```
fluxi/
├── auth/            # Login, signup, middleware de proteção (bcrypt)
├── canal/           # Camada de abstração de canais
│   ├── canal_base.py      # Interface CanalClient + EventoMensagem
│   ├── canal_whatsapp.py  # Adapter neonize
│   ├── canal_telegram.py  # Adapter python-telegram-bot
│   ├── canal_webchat.py   # Adapter SSE
│   └── canal_factory.py   # Cria adapter pela sessao.plataforma
├── webchat/         # Página pública /chat/<id> + endpoints SSE
├── agente/          # Sistema de agentes inteligentes
├── coding_agent/    # Agente coder com sandbox (prefixo #code)
├── config/          # Configurações do sistema
├── ferramenta/      # Ferramentas customizadas (function calling)
├── llm_providers/   # Provedores LLM (local e nuvem)
├── mcp_client/      # Model Context Protocol
├── mensagem/        # Pipeline central; processar_evento_canal roteia por plataforma
├── metrica/         # Analytics e monitoramento
├── rag/             # Bases de conhecimento (ChromaDB)
├── sessao/          # Sessões = canais conectados (multi-plataforma)
└── templates/       # Interface web (Jinja2 SSR)
```

Cada módulo tem `README.md` próprio. Para uma visão dirigida a agentes de IA contribuindo no código, ver [`AGENTS.md`](AGENTS.md).

---

## 📋 Changelog

### v0.3.0 - Maio 2026

**Novos Recursos**
- 🔌 **Camada multi-canal** (`canal/`): WhatsApp, Telegram e Web Chat compartilham a mesma engine
- 💬 **Telegram** via python-telegram-bot v21+ (long polling, bot_token cifrado com Fernet)
- 🌐 **Web Chat público**: página `/chat/<sessao_id>` com texto, áudio (MediaRecorder) e imagem; entrega via SSE
- 🔐 **Sistema de autenticação**: login/signup, primeiro usuário vira admin, middleware de proteção
- 🆘 **Reset de senha via `.env`** (`FLUXI_ADMIN_RESET_EMAIL` + `FLUXI_ADMIN_RESET_PASSWORD`)
- 🔑 **Credenciais cifradas em repouso** (`FLUXI_SECRET_KEY` controla a chave Fernet)

**Migrations aditivas**
- `Sessao.plataforma`, `identificador`, `credenciais`
- `Mensagem.plataforma`, `chat_id`, `mensagem_id_externo`
- Nova tabela `users`

### v0.2.0 - Novembro 2025

**Novos Recursos**
- Dark mode na interface
- Comandos personalizáveis por sessão (`#ativar`, `#desativar`)
- Tipos de mensagem configuráveis (ignorar, resposta fixa, etc)
- Suporte a mensagens multimodais (texto + imagem)

**Melhorias**
- Histórico de mensagens inclui respostas do assistente
- Sincronização automática de novos comandos
- Documentação atualizada de todos os módulos

**Correções**
- Comando `#desativar` não era reconhecido corretamente
- Histórico multimodal não era enviado ao LLM

### v0.1.0 - Outubro 2025

- Lançamento inicial
- Sistema de agentes com system prompts
- Ferramentas customizadas com wizard
- RAG com ChromaDB
- Integração MCP
- Múltiplos provedores LLM
- Interface web completa

---

## 🤝 Contribuindo

Contribuições são bem-vindas!

1. Fork o projeto
2. Crie uma branch (`git checkout -b feature/nova-feature`)
3. Commit suas mudanças (`git commit -m 'Adiciona nova feature'`)
4. Push (`git push origin feature/nova-feature`)
5. Abra um Pull Request

---

## 💬 Comunidade

- [GitHub Issues](https://github.com/jjhoow/fluxi/issues) - Bugs e sugestões
- [GitHub Discussions](https://github.com/jjhoow/fluxi/discussions) - Dúvidas e ideias

---

## 📦 Dependências de Terceiros

Este projeto utiliza:

- **[neonize](https://github.com/krypton-byte/neonize)** - Cliente Python para WhatsApp Web
- **[whatsmeow](https://github.com/tulir/whatsmeow)** - Biblioteca Go para WhatsApp Web (via neonize)
- **[FastAPI](https://fastapi.tiangolo.com/)** - Framework web
- **[ChromaDB](https://www.trychroma.com/)** - Banco vetorial
- **[SQLAlchemy](https://www.sqlalchemy.org/)** - ORM

---

## 🙏 Agradecimentos

- [FastAPI](https://fastapi.tiangolo.com/) pelo framework incrível
- [Neonize](https://github.com/krypton-byte/neonize) por tornar WhatsApp acessível em Python
- [ChromaDB](https://www.trychroma.com/) pelo banco vetorial simples e poderoso
- Comunidade open source por todas as bibliotecas que tornam isso possível

---

## 📄 Licença

Apache 2.0 - Veja [LICENSE](LICENSE) para detalhes.

---

<div align="center">

**Feito para quem quer controle total sobre sua IA.**

Se esse projeto te ajudou, deixa uma estrela!

</div>
