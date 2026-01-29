<div align="center">

<img src="data/logo_fluxi.png" alt="Fluxi.IA" width="200">

### Sua IA privada no WhatsApp...

![Dashboard](data/screenshot01.png)

</div>

---

## 🤔 Por que Fluxi?

Você já quis ter um assistente de IA no WhatsApp, mas:

- Não quer pagar mensalidade de plataformas SaaS
- Não quer depender de servidores externos
- Não quer expor suas conversas para terceiros
- Quer controle total sobre o comportamento da IA

**Fluxi resolve tudo isso.**

Com Docker, um modelo de linguagem local (LM Studio, Ollama) e seu número de WhatsApp, você tem uma IA 100% privada funcionando em minutos.

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
| **Múltiplos Agentes** | Crie agentes especializados e alterne entre eles |
| **RAG (Documentos)** | Adicione bases de conhecimento e faça perguntas |
| **Ferramentas Customizadas** | Conecte APIs com wizard visual, sem código |
| **MCP Protocol** | Integre ferramentas externas (GitHub, databases, etc) |
| **LLMs Locais** | Use Ollama, LM Studio ou llama.cpp - 100% offline |
| **LLMs na Nuvem** | OpenRouter, OpenAI, Anthropic, Google - sua escolha |
| **Comandos** | `#ativar`, `#desativar`, `#limpar`, `#status`, `#ajuda` |
| **Transcrição** | Converta áudios em texto automaticamente |
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

- Docker instalado
- Um número de WhatsApp
- Um provedor LLM (local ou nuvem)

### 1. Clone e configure

```bash
git clone https://github.com/jjhoow/fluxi.git
cd fluxi
cp config.example.env .env
```

### 2. Inicie com Docker

```bash
docker-compose up -d --build
```

### 3. Acesse e conecte

1. Abra `http://localhost:8000`
2. Crie uma sessão WhatsApp
3. Escaneie o QR Code
4. Configure um provedor LLM
5. Crie seu primeiro agente

**Pronto.** Envie uma mensagem para o número conectado.

---

## 🔩 Stack Técnica

| Camada | Tecnologia |
|--------|------------|
| **Backend** | Python, FastAPI, SQLAlchemy, Pydantic |
| **Frontend** | Jinja2, Bulma, HTMX |
| **Banco de Dados** | SQLite (padrão), PostgreSQL (produção) |
| **Vetorial** | ChromaDB |
| **WhatsApp** | Neonize (whatsmeow) |
| **LLM** | OpenRouter, OpenAI, Ollama, LM Studio |

---

## 📂 Arquitetura

```
fluxi/
├── agente/          # Sistema de agentes inteligentes
├── config/          # Configurações do sistema
├── ferramenta/      # Ferramentas customizadas (function calling)
├── llm_providers/   # Provedores LLM (local e nuvem)
├── mcp_client/      # Model Context Protocol
├── mensagem/        # Mensagens e histórico
├── metrica/         # Analytics e monitoramento
├── rag/             # Bases de conhecimento
├── sessao/          # Sessões WhatsApp
└── templates/       # Interface web
```

Cada módulo tem sua própria documentação em `[modulo]/README.md`.

---

## 📋 Changelog

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
