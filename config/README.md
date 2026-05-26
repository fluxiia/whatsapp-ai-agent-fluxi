# Módulo Config ⚙️

## 📖 Visão Geral

O módulo `config` é o **centro de configurações** do Fluxi. Ele gerencia todas as configurações globais do sistema, incluindo chaves de API, parâmetros de LLM, configurações de agentes padrão, e preferências gerais. Funciona como um sistema de chave-valor tipado, onde cada configuração tem um tipo (string, int, float, bool, json) e uma categoria organizacional.

## 🎯 Objetivo

Centralizar e gerenciar todas as configurações do sistema de forma:
- **Tipada** - Cada configuração tem um tipo específico (string, int, float, bool, json)
- **Categorizad**a - Organizadas por categoria (geral, openrouter, agente, llm, rag)
- **Editável** - Controle fino sobre quais configurações podem ser editadas
- **Persistente** - Armazenadas em banco de dados SQLite
- **Acessível** - API e interface web para gerenciamento
- **Validada** - Validação de tipos e valores

## 📂 Estrutura de Arquivos

```
config/
├── __init__.py                    # Inicialização do módulo
├── config_model.py                # Modelo SQLAlchemy (tabela configuracoes)
├── config_schema.py               # Schemas Pydantic (validação)
├── config_service.py              # Lógica de negócio e CRUD
├── config_router.py               # Endpoints REST API
├── config_frontend_router.py      # Rotas de interface web
├── rag_config.py                  # Configurações específicas de RAG
└── README.md                      # Esta documentação
```

## 🔧 Componentes Principais

### 1. Models (config_model.py)

Define a estrutura da tabela de configurações:

#### **Tabela: `configuracoes`**
| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | Integer | ID único da configuração |
| `chave` | String(100) | Chave única (ex: "openrouter_api_key") |
| `valor` | Text | Valor armazenado como string |
| `tipo` | String(50) | Tipo do valor: string, int, float, bool, json |
| `descricao` | Text | Descrição da configuração |
| `categoria` | String(50) | Categoria: geral, openrouter, whatsapp, agente, llm, rag |
| `editavel` | Boolean | Se pode ser editada via interface |
| `criado_em` | DateTime | Data de criação |
| `atualizado_em` | DateTime | Data de atualização |

### 2. Schemas (config_schema.py)

Validação de dados usando Pydantic:

- **`ConfiguracaoBase`**: Schema base com campos comuns
- **`ConfiguracaoCriar`**: Para criar nova configuração
- **`ConfiguracaoAtualizar`**: Para atualizar (valor e descrição)
- **`ConfiguracaoResposta`**: Resposta da API
- **`ModeloLLM`**: Schema para modelos LLM disponíveis
- **`TestarConexaoResposta`**: Resposta ao testar conexão com OpenRouter

### 3. Service (config_service.py)

Lógica de negócio completa para gerenciamento de configurações.

#### **Funções Principais:**

**Leitura:**
- `obter_por_chave(chave)` - Busca configuração por chave
- `obter_valor(chave, padrao)` - **MAIS USADA**: Obtém valor convertido para tipo correto
- `listar_por_categoria(categoria)` - Lista configurações de uma categoria
- `listar_todas()` - Lista todas as configurações

**Escrita:**
- `criar(config)` - Cria nova configuração
- `atualizar(chave, config)` - Atualiza configuração existente
- `definir_valor(chave, valor)` - Define valor (cria se não existir)
- `deletar(chave)` - Remove configuração

**Especializadas:**
- `testar_conexao_openrouter(api_key)` - Testa conexão e busca modelos disponíveis
- `inicializar_configuracoes_padrao()` - Cria configurações padrão na inicialização

#### **Conversão Automática de Tipos:**

O método `obter_valor()` converte automaticamente:

```python
# int
config.tipo == "int" → int(config.valor)

# float  
config.tipo == "float" → float(config.valor)

# bool
config.tipo == "bool" → valor.lower() in ("true", "1", "sim", "yes")

# json
config.tipo == "json" → json.loads(config.valor)

# string
config.tipo == "string" → config.valor (sem conversão)
```

### 4. Router API (config_router.py)

Endpoints REST para gerenciamento:

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/configuracoes/` | Lista todas as configurações |
| GET | `/api/configuracoes/categoria/{cat}` | Lista por categoria |
| GET | `/api/configuracoes/{chave}` | Obtém configuração específica |
| POST | `/api/configuracoes/` | Cria nova configuração |
| PUT | `/api/configuracoes/{chave}` | Atualiza configuração |
| DELETE | `/api/configuracoes/{chave}` | Deleta configuração |
| POST | `/api/configuracoes/openrouter/testar` | Testa conexão OpenRouter |

### 5. Frontend Router (config_frontend_router.py)

Interface web para gerenciar configurações:

| Rota | Descrição | Template |
|------|-----------|----------|
| GET `/configuracoes/` | Página de configurações | `config/settings.html` |
| POST `/configuracoes/salvar-openrouter` | Salva config OpenRouter | Redirect |
| POST `/configuracoes/salvar-parametros-llm` | Salva parâmetros LLM | Redirect |
| POST `/configuracoes/salvar-agente` | Salva config agente padrão | Redirect |
| POST `/configuracoes/salvar-geral` | Salva config gerais | Redirect |
| POST `/configuracoes/salvar-provedores-llm` | Salva provedores LLM | Redirect |

### 6. RAG Config (rag_config.py)

Configurações específicas para o sistema RAG (Retrieval-Augmented Generation).

#### **Providers Suportados:**
- **OpenAI** - text-embedding-3-small, text-embedding-3-large
- **Cohere** - embed-english-v3.0, embed-multilingual-v3.0
- **HuggingFace** - sentence-transformers (vários modelos)
- **Google** - models/embedding-001, text-embedding-004

#### **Configurações por Provider:**
```python
{
    "model": "text-embedding-3-small",     # Modelo de embedding
    "chunk_size": 1000,                     # Tamanho do chunk (100-5000)
    "chunk_overlap": 200,                   # Sobreposição (0-1000)
    "top_k": 3                             # Resultados retornados (1-20)
}
```

#### **Funções:**
- `get_config(provider)` - Obtém configurações de um provider
- `get_default_provider()` - Retorna provider padrão
- `get_available_providers()` - Lista providers disponíveis
- `get_provider_models(provider)` - Lista modelos do provider
- `validate_config(config)` - Valida configurações

## 🔄 Fluxo de Funcionamento

### 1️⃣ **Inicialização do Sistema**

```python
# Em main.py, evento startup
ConfiguracaoService.inicializar_configuracoes_padrao(db)
```

Cria configurações padrão se não existirem:
1. Provedores LLM (openrouter, local, fallback)
2. OpenRouter (api_key, modelo, temperatura, max_tokens, top_p)
3. Agente (papel, objetivo, políticas, tarefa, público, restrições)
4. Sistema (diretório uploads, tamanho máx. imagem)

### 2️⃣ **Leitura de Configuração (Uso Comum)**

```python
# Exemplo: Obter modelo LLM padrão
from config.config_service import ConfiguracaoService

modelo = ConfiguracaoService.obter_valor(
    db, 
    "openrouter_modelo_padrao", 
    "google/gemini-3.1-flash-lite-preview"  # Valor padrão se não encontrar
)
# Retorna: "google/gemini-3.1-flash-lite-preview" (string)

# Exemplo: Obter temperatura (float)
temperatura = ConfiguracaoService.obter_valor(
    db,
    "openrouter_temperatura",
    0.7
)
# Retorna: 0.7 (float, já convertido)

# Exemplo: Obter max_tokens (int)
max_tokens = ConfiguracaoService.obter_valor(
    db,
    "openrouter_max_tokens", 
    2000
)
# Retorna: 2000 (int, já convertido)
```

### 3️⃣ **Escrita de Configuração**

```python
# Método 1: Atualizar existente
ConfiguracaoService.atualizar(
    db,
    "openrouter_api_key",
    ConfiguracaoAtualizar(valor="sk-or-v1-abc123...")
)

# Método 2: Definir valor (cria se não existe)
ConfiguracaoService.definir_valor(
    db,
    "openrouter_temperatura",
    0.9  # Tipo detectado automaticamente
)
```

### 4️⃣ **Testar Conexão OpenRouter**

```python
# Via service
resultado = await ConfiguracaoService.testar_conexao_openrouter(
    db,
    api_key="sk-or-v1-abc123..."
)

if resultado.sucesso:
    print(f"Conectado! {len(resultado.modelos)} modelos disponíveis")
    for modelo in resultado.modelos:
        print(f"- {modelo.nome} (contexto: {modelo.contexto} tokens)")
else:
    print(f"Erro: {resultado.mensagem}")
```

## 📊 Categorias de Configurações

### 🔵 **Categoria: llm**
Configurações de provedores LLM:
- `llm_provedor_padrao` - Provedor padrão (openrouter, local, custom)
- `llm_provedor_local_id` - ID do provedor local
- `llm_fallback_openrouter` - Usar OpenRouter como fallback

### 🟢 **Categoria: openrouter**
Configurações do OpenRouter:
- `openrouter_api_key` - Chave de API
- `openrouter_modelo_padrao` - Modelo padrão (ex: google/gemini-3.1-flash-lite-preview)
- `openrouter_temperatura` - Temperatura (0.0 a 2.0)
- `openrouter_max_tokens` - Máximo de tokens (ex: 2000)
- `openrouter_top_p` - Top P (0.0 a 1.0)

### 🟡 **Categoria: agente**
Configurações padrão para novos agentes:
- `agente_papel_padrao` - Papel padrão
- `agente_objetivo_padrao` - Objetivo padrão
- `agente_politicas_padrao` - Políticas padrão
- `agente_tarefa_padrao` - Tarefa padrão
- `agente_objetivo_explicito_padrao` - Objetivo explícito padrão
- `agente_publico_padrao` - Público-alvo padrão
- `agente_restricoes_padrao` - Restrições padrão

### 🟠 **Categoria: geral**
Configurações gerais do sistema:
- `sistema_diretorio_uploads` - Diretório de uploads (./uploads)
- `sistema_max_tamanho_imagem_mb` - Tamanho máx. de imagem em MB (10)

### 🟣 **Categoria: rag** (via rag_config.py)
Configurações RAG por provider:
- `rag_openai_model` - Modelo OpenAI
- `rag_openai_chunk_size` - Tamanho do chunk
- `rag_openai_chunk_overlap` - Sobreposição
- `rag_openai_top_k` - Número de resultados
- *(similar para cohere, huggingface, google)*

## 🔗 Dependências

### Módulos Internos:
- **`database`** - Base do SQLAlchemy
- Usado por TODOS os outros módulos para obter configurações

### Bibliotecas Externas:
- **SQLAlchemy** - ORM para persistência
- **Pydantic** - Validação de schemas
- **httpx** - Cliente HTTP async (testar OpenRouter)
- **FastAPI** - Framework web

## 💡 Exemplos de Uso

### Exemplo 1: Criar Nova Categoria de Configurações

```python
# Adicionar novas configurações programaticamente
from config.config_schema import ConfiguracaoCriar

ConfiguracaoService.criar(db, ConfiguracaoCriar(
    chave="telegram_bot_token",
    valor="123456:ABC-DEF...",
    tipo="string",
    descricao="Token do bot Telegram",
    categoria="telegram",
    editavel=True
))
```

### Exemplo 2: Obter Configurações de uma Categoria

```python
# Listar todas as configs da categoria 'agente'
configs_agente = ConfiguracaoService.listar_por_categoria(db, "agente")

for config in configs_agente:
    print(f"{config.chave}: {config.valor}")
```

### Exemplo 3: Configurações RAG

```python
from config.rag_config import RAGConfig

# Obter provider padrão
provider = RAGConfig.get_default_provider(db)  # "openai"

# Obter config do provider
config = RAGConfig.get_provider_config(db, "openai")
# {
#     "model": "text-embedding-3-small",
#     "chunk_size": 1000,
#     "chunk_overlap": 200,
#     "top_k": 3
# }

# Listar modelos disponíveis
modelos = RAGConfig.get_provider_models("openai")
# ["text-embedding-3-small", "text-embedding-3-large", ...]

# Validar configuração
errors = RAGConfig.validate_config({
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "top_k": 3
})
if not errors:
    print("Configuração válida!")
```

### Exemplo 4: Interface Web

O usuário acessa `/configuracoes` e vê formulários organizados por categoria:

```html
<!-- Seção OpenRouter -->
<form action="/configuracoes/salvar-openrouter" method="post">
    <input name="api_key" value="{{ config.openrouter_api_key }}">
    <input name="modelo_padrao" value="{{ config.openrouter_modelo_padrao }}">
    <button name="acao" value="testar">Testar Conexão</button>
    <button name="acao" value="salvar">Salvar</button>
</form>
```

## 🔌 Integrações

### 1. **Usado por TODOS os módulos**

Praticamente todos os módulos consultam configurações:

```python
# agente/agente_service.py
modelo = ConfiguracaoService.obter_valor(db, "openrouter_modelo_padrao")

# llm_providers/llm_integration_service.py
provedor_padrao = ConfiguracaoService.obter_valor(db, "llm_provedor_padrao")

# rag/rag_service.py
from config.rag_config import RAGConfig
config = RAGConfig.get_provider_config(db, "openai")

# sessao/sessao_service.py
max_tamanho = ConfiguracaoService.obter_valor(db, "sistema_max_tamanho_imagem_mb")
```

### 2. **LLM Providers**

O módulo `config` armazena:
- Chaves de API de provedores
- Provedor padrão a ser usado
- Configuração de fallback

### 3. **OpenRouter**

Testa conexão e busca modelos disponíveis:
- Valida API key
- Lista 200+ modelos LLM
- Detecta suporte a imagens e ferramentas

### 4. **RAG**

Configurações específicas via `RAGConfig`:
- Provider de embeddings (OpenAI, Cohere, HuggingFace, Google)
- Parâmetros de chunking
- Número de resultados

## 📝 Notas Técnicas

### Sistema Chave-Valor Tipado

Diferente de um simples dicionário, cada configuração tem:
- **Tipo explícito** - Garante conversão correta
- **Validação** - Pydantic valida schemas
- **Descrição** - Documentação inline
- **Categoria** - Organização lógica
- **Editabilidade** - Controle de acesso

### Segurança

- ✅ Configurações podem ser marcadas como **não editáveis**
- ✅ Valores sensíveis (API keys) armazenados em banco
- ⚠️ **Importante**: Use variáveis de ambiente em produção
- ⚠️ **Importante**: Não versione `fluxi.db` com API keys

### Performance

- Consultas otimizadas com índice em `chave`
- Cache poderia ser adicionado para configurações frequentes
- Inicialização rápida (apenas cria se não existir)

### Extensibilidade

Para adicionar nova categoria:

1. Adicionar em `inicializar_configuracoes_padrao()`
2. Criar formulário em `templates/config/settings.html`
3. Adicionar rota POST em `config_frontend_router.py`
4. (Opcional) Criar classe helper como `RAGConfig`

### Valores Padrão

Sempre forneça valor padrão ao usar `obter_valor()`:

```python
# ✅ BOM - fornece padrão
modelo = ConfiguracaoService.obter_valor(db, "modelo", "gpt-4")

# ❌ EVITE - pode retornar None
modelo = ConfiguracaoService.obter_valor(db, "modelo")
```

### Tipos JSON

Para estruturas complexas:

```python
# Salvar JSON
ConfiguracaoService.definir_valor(
    db,
    "webhooks",
    {
        "url": "https://api.example.com/webhook",
        "eventos": ["mensagem_recebida", "mensagem_enviada"]
    }
)

# Recuperar JSON (já deserializado)
webhooks = ConfiguracaoService.obter_valor(db, "webhooks", {})
print(webhooks["url"])  # "https://api.example.com/webhook"
```

### Categorias Customizadas

Você pode criar categorias personalizadas:

```python
ConfiguracaoService.criar(db, ConfiguracaoCriar(
    chave="discord_webhook_url",
    valor="https://discord.com/api/webhooks/...",
    tipo="string",
    categoria="discord",  # Nova categoria!
    descricao="Webhook para notificações Discord"
))
```

## 🚀 Inicialização

No startup da aplicação (`main.py`):

```python
@app.on_event("startup")
def startup_event():
    criar_tabelas()
    db = SessionLocal()
    
    # Inicializar configurações padrão
    ConfiguracaoService.inicializar_configuracoes_padrao(db)
    
    db.close()
```

Isso garante que todas as configurações essenciais existam.

---

## 📚 Referência Rápida

### Ler Configuração
```python
valor = ConfiguracaoService.obter_valor(db, "chave", "padrão")
```

### Escrever Configuração
```python
ConfiguracaoService.definir_valor(db, "chave", valor)
```

### Listar Categoria
```python
configs = ConfiguracaoService.listar_por_categoria(db, "categoria")
```

### Testar OpenRouter
```python
resultado = await ConfiguracaoService.testar_conexao_openrouter(db, api_key)
```

### RAG Config
```python
from config.rag_config import RAGConfig
config = RAGConfig.get_provider_config(db, "openai")
```

---

**Módulo criado por:** Fluxi Team  
**Versão:** 1.0.0  
**Última atualização:** 2025

