"""
Serviço de lógica de negócio para skills.
"""
import json
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any

from skill.skill_model import Skill, agente_skill
from skill.skill_schema import SkillCriar, SkillAtualizar

logger = logging.getLogger(__name__)


class SkillService:
    """Serviço para gerenciar skills."""

    # ---------- CRUD ----------

    @staticmethod
    def listar_todas(db: Session) -> List[Skill]:
        """Lista todas as skills."""
        return db.query(Skill).order_by(Skill.categoria, Skill.nome).all()

    @staticmethod
    def listar_ativas(db: Session) -> List[Skill]:
        """Lista skills ativas."""
        return db.query(Skill).filter(Skill.ativa == True).order_by(Skill.categoria, Skill.nome).all()

    @staticmethod
    def obter_por_id(db: Session, skill_id: int) -> Optional[Skill]:
        """Obtém uma skill pelo ID."""
        return db.query(Skill).filter(Skill.id == skill_id).first()

    @staticmethod
    def obter_por_nome(db: Session, nome: str) -> Optional[Skill]:
        """Obtém uma skill pelo nome."""
        return db.query(Skill).filter(Skill.nome == nome).first()

    @staticmethod
    def criar(db: Session, skill: SkillCriar) -> Skill:
        """Cria uma nova skill."""
        db_skill = Skill(**skill.model_dump())
        db.add(db_skill)
        db.commit()
        db.refresh(db_skill)
        return db_skill

    @staticmethod
    def atualizar(db: Session, skill_id: int, skill: SkillAtualizar) -> Optional[Skill]:
        """Atualiza uma skill existente."""
        db_skill = SkillService.obter_por_id(db, skill_id)
        if not db_skill:
            return None
        for campo, valor in skill.model_dump(exclude_unset=True).items():
            setattr(db_skill, campo, valor)
        db.commit()
        db.refresh(db_skill)
        return db_skill

    @staticmethod
    def deletar(db: Session, skill_id: int) -> bool:
        """Deleta uma skill."""
        db_skill = SkillService.obter_por_id(db, skill_id)
        if not db_skill:
            return False
        db.delete(db_skill)
        db.commit()
        return True

    # ---------- ASSOCIAÇÃO AGENTE-SKILL ----------

    @staticmethod
    def listar_skills_agente(db: Session, agente_id: int) -> List[Skill]:
        """Retorna skills ativas do agente, ordenadas por posicao."""
        return (
            db.query(Skill)
            .join(agente_skill, Skill.id == agente_skill.c.skill_id)
            .filter(
                agente_skill.c.agente_id == agente_id,
                agente_skill.c.ativa == True,
                Skill.ativa == True
            )
            .order_by(agente_skill.c.posicao)
            .all()
        )

    @staticmethod
    def atualizar_skills_agente(db: Session, agente_id: int, skill_ids: List[int]):
        """Substitui completamente as skills do agente."""
        db.execute(agente_skill.delete().where(agente_skill.c.agente_id == agente_id))
        for posicao, skill_id in enumerate(skill_ids):
            skill = SkillService.obter_por_id(db, skill_id)
            if not skill:
                raise ValueError(f"Skill {skill_id} não encontrada")
            db.execute(agente_skill.insert().values(
                agente_id=agente_id,
                skill_id=skill_id,
                posicao=posicao,
                ativa=True
            ))
        db.commit()

    # ---------- EXECUÇÃO DO SCRIPT_CODIGO ----------

    @staticmethod
    def executar_script(skill: Skill, argumentos: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executa skill.script_codigo em namespace controlado.
        Retorna dict com dados de contexto para substituição na instrução.
        """
        if not skill.script_codigo:
            return {}
        namespace = {
            "argumentos": argumentos,
            "resultado": None,
            "json": json,
            "datetime": datetime,
        }
        try:
            exec(skill.script_codigo, namespace)
            raw = namespace.get("resultado")
            if raw is not None:
                return raw if isinstance(raw, dict) else {"output": raw}
            return {}
        except Exception as e:
            logger.warning("[SKILL] Erro no script da skill '%s': %s", skill.nome, e)
            return {"erro_script": str(e)}

    # ---------- FERRAMENTAS EXTRAS ----------

    @staticmethod
    def obter_ferramentas_extras_da_skill(db: Session, skill: Skill) -> list:
        """Retorna os objetos Ferramenta configurados em skill.ferramentas_ids."""
        if not skill.ferramentas_ids:
            return []
        try:
            from ferramenta.ferramenta_model import Ferramenta
            ids = json.loads(skill.ferramentas_ids)
            return db.query(Ferramenta).filter(
                Ferramenta.id.in_(ids),
                Ferramenta.ativa == True
            ).all()
        except Exception:
            return []

    # ---------- SKILLS PADRÃO ----------

    @staticmethod
    def criar_skills_padrao(db: Session):
        """Cria skills demonstrativas padrão se não existirem."""
        skills_padrao = [
            {
                "nome": "atendimento-educado",
                "descricao": "Comportamento formal e educado. Use quando o cliente precisar de suporte formal, reclamação, ou quando o tom exigir protocolo e formalidade.",
                "instrucao_completa": """# Skill: Atendimento Educado

## Diretrizes de Comunicação
- Sempre cumprimente o cliente pelo nome quando souber
- Use linguagem formal mas acessível
- Termine mensagens com uma oferta de ajuda adicional
- Jamais use gírias ou abreviações
- Em caso de problemas: reconheça, peça desculpas, ofereça solução

## Estrutura de Resposta
1. Saudação personalizada
2. Reconhecimento da solicitação
3. Resposta/solução
4. Oferta de suporte adicional""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "comportamento",
                "icone": "🤝",
                "versao": "1.0",
                "ativa": True
            },
            {
                "nome": "vendas",
                "descricao": "Fluxo completo de vendas consultivas com etapas. Use quando o usuário demonstrar interesse em comprar, pedir preços, ou iniciar uma negociação.",
                "instrucao_completa": """# Skill: Vendas Consultivas

Você conduz vendas consultivas em etapas. Identifique a etapa atual e invoque a sub-skill correspondente:

## Sub-skills disponíveis:
- `vendas-abertura`: Rapport inicial e qualificação do lead
- `vendas-proposta`: Apresentação da solução e proposta de valor
- `vendas-fechamento`: Confirmação e próximos passos

## Regra geral:
1. Identifique em qual etapa o cliente está
2. Invoque a sub-skill correspondente usando `invocar_skill`
3. Siga as instruções da sub-skill escolhida
4. Ao concluir cada etapa, avance quando apropriado""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "fluxo",
                "icone": "💼",
                "versao": "1.0",
                "ativa": True
            },
            {
                "nome": "vendas-abertura",
                "descricao": "Abertura de contato, rapport e qualificação do lead. Sub-skill de vendas para o início do contato.",
                "instrucao_completa": """# Skill: Abertura de Vendas

1. **Saudação calorosa** — apresente-se pelo nome da empresa
2. **Rapport** — comente algo positivo ou faça uma pergunta aberta
3. **Qualificação** — descubra:
   - Qual problema o cliente quer resolver?
   - Qual o prazo esperado?
   - Houve contato anterior com a empresa?
4. **Transição** — ao qualificar, invoque `vendas-proposta`

**Contexto:** Horário do contato: {hora_contato} ({periodo})""",
                "script_codigo": """from datetime import datetime
hora = datetime.now().hour
resultado = {
    "hora_contato": datetime.now().strftime("%H:%M"),
    "periodo": "manhã" if hora < 12 else "tarde" if hora < 18 else "noite"
}""",
                "ferramentas_ids": None,
                "categoria": "fluxo",
                "icone": "👋",
                "versao": "1.0",
                "ativa": True
            },
            {
                "nome": "vendas-proposta",
                "descricao": "Apresentação da solução e proposta de valor. Sub-skill de vendas para a fase de negociação.",
                "instrucao_completa": """# Skill: Proposta de Vendas

## Estrutura da apresentação:
1. **Resumo do problema** — confirme o que o cliente precisa
2. **Apresentação da solução** — descreva como seu produto/serviço resolve
3. **Diferencial** — apresente o que te distingue da concorrência
4. **Proposta de valor** — preço ou condições (se disponível)
5. **Call to action** — convide para o próximo passo

## Regras:
- Se o cliente apresentar objeções, aborde cada uma diretamente
- Se o cliente concordar, avance para `vendas-fechamento`
- Mantenha o foco nos benefícios, não nas características técnicas""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "fluxo",
                "icone": "📊",
                "versao": "1.0",
                "ativa": True
            },
            {
                "nome": "vendas-fechamento",
                "descricao": "Técnicas de fechamento e confirmação do pedido. Sub-skill de vendas para a fase final.",
                "instrucao_completa": """# Skill: Fechamento de Vendas

## Técnicas disponíveis:
- **Resumo de benefícios**: recapitule os pontos de valor acordados
- **Urgência legítima**: mencione disponibilidade ou condição especial real
- **Próximo passo claro**: proponha uma ação concreta (pagamento, assinatura, agendamento)

## Sequência:
1. Confirme que o cliente entende a proposta completa
2. Pergunte diretamente: "Podemos avançar?"
3. Se sim: forneça instruções de pagamento/próximos passos
4. Se objeção: retorne à skill `vendas-proposta` para reforçar""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "fluxo",
                "icone": "✅",
                "versao": "1.0",
                "ativa": True
            },
            {
                "nome": "especialista-tecnico",
                "descricao": "Modo especialista técnico com respostas precisas e terminologia técnica. Use quando o usuário fizer perguntas técnicas detalhadas, pedir código ou configurações específicas.",
                "instrucao_completa": """# Skill: Especialista Técnico

## Comportamento
- Use terminologia técnica precisa
- Cite versões, parâmetros e configurações específicas quando relevante
- Ofereça exemplos de código quando aplicável
- Mencione limitações e casos extremos
- Prefira precisão à simplicidade

## Formato de resposta
- Estruture com headers markdown
- Use blocos de código para exemplos técnicos
- Liste pré-requisitos quando houver""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "especialização",
                "icone": "⚙️",
                "versao": "1.0",
                "ativa": True
            },
            {
                "nome": "coleta-dados-cliente",
                "descricao": "Coleta estruturada de dados do cliente para cadastro ou qualificação. Use quando precisar coletar informações como nome, e-mail, telefone ou cidade do usuário.",
                "instrucao_completa": """# Skill: Coleta de Dados do Cliente

## Dados a coletar (em ordem):
1. Nome completo
2. E-mail
3. Telefone (se não tiver)
4. Cidade/Estado
5. Interesse principal

## Regras:
- Colete UM dado por mensagem (não bombarde o cliente)
- Confirme cada dado antes de avançar
- Ao coletar todos: faça um resumo e peça confirmação
- Após confirmação: informe que os dados foram registrados

**Contexto da coleta:** {contexto_coleta}""",
                "script_codigo": """resultado = {
    "contexto_coleta": argumentos.get("contexto", "atendimento geral"),
    "timestamp_inicio": __import__("datetime").datetime.now().isoformat()
}""",
                "ferramentas_ids": None,
                "categoria": "utilitário",
                "icone": "📋",
                "versao": "1.0",
                "ativa": True
            },
        ]

        # ── Meta — auto-modificação do sistema ──
        skills_padrao += [
            {
                "nome": "meta_ferramentas",
                "descricao": "Instruções para criar, editar e gerenciar ferramentas (tools) no Fluxi",
                "instrucao_completa": """# Como Criar e Gerenciar Ferramentas no Fluxi

Você tem acesso à ferramenta `fluxi_ferramentas` para criar, editar e gerenciar ferramentas do sistema.

---

## Campos de uma Ferramenta

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `nome` | string | Identificador único em snake_case |
| `descricao` | string | Descrição para o LLM entender quando usar esta ferramenta |
| `tool_type` | enum | `CODE` ou `WEB` |
| `tool_scope` | enum | `PRINCIPAL` (exposta ao LLM) ou `AUXILIAR` (interna) |
| `params` | JSON string | Schema dos parâmetros que o LLM deve passar |
| `codigo_python` | string | Código Python (somente `tool_type=CODE`) |
| `curl_command` | string | Comando CURL completo (somente `tool_type=WEB`) |
| `substituir` | bool | Habilita substituição de variáveis `{param}` e `{var.CHAVE}` (padrão: true) |
| `response_map` | JSON string | Filtra/renomeia campos da resposta da API |
| `output` | enum | `LLM` (padrão), `USER` ou `BOTH` |
| `channel` | enum | Canal quando `output=USER`: `TEXT`, `IMAGE`, `AUDIO`, `VIDEO`, `DOCUMENT` |
| `post_instruction` | string | Instrução oculta para o LLM sobre como apresentar o resultado |
| `next_tool` | string | Nome de outra ferramenta a executar automaticamente após esta |
| `ativa` | bool | Se a ferramenta está disponível (padrão: true) |

---

## Schema de Parâmetros (`params`)

```json
{
  "cidade": {
    "type": "string",
    "required": true,
    "description": "Nome da cidade"
  },
  "unidade": {
    "type": "enum",
    "required": false,
    "description": "Unidade de temperatura",
    "options": ["celsius", "fahrenheit"]
  },
  "limite": {
    "type": "integer",
    "required": false,
    "description": "Número máximo de resultados"
  }
}
```

Tipos disponíveis: `string`, `integer`, `float`, `boolean`, `array`, `enum`.

---

## Tipos de Ferramentas

### CODE — Executa Python

- O dict `argumentos` contém os parâmetros enviados pelo LLM
- Você DEVE definir a variável `resultado` (dict ou string) ao final
- Módulos disponíveis: `httpx`, `json`, `base64`, `datetime`, `re`, `math`
- Para segredos e tokens: use `{var.CHAVE}` no código (NÃO use `os.environ`)
- Para capturar outra variável como saída: use o campo `print_output_var`

**Exemplo — buscar e converter imagem para base64:**
```python
import httpx, base64
url = argumentos.get("url_imagem")
resp = httpx.get(url, timeout=30)
resp.raise_for_status()
b64 = base64.b64encode(resp.content).decode("utf-8")
resultado = {"base64": b64, "mime_type": resp.headers.get("content-type", "image/jpeg")}
```

### WEB — Faz chamada HTTP via CURL

- Informe o comando CURL completo no campo `curl_command`
- Use `{nome_param}` para injetar parâmetros do LLM
- Use `{var.CHAVE}` para injetar tokens/secrets cadastrados no banco
- A resposta da API é retornada como JSON

**Exemplo de curl_command:**
```
curl -s "https://api.exemplo.com/clima?cidade={cidade}&appid={var.API_KEY}"
```

---

## Variáveis Seguras com `{var.CHAVE}`

Para armazenar tokens, API keys e outros segredos, use o sistema de variáveis da ferramenta.
O valor é injetado em tempo de execução — nunca fica exposto no código.

**Fluxo:**
1. Crie a ferramenta referenciando `{var.MINHA_CHAVE}` no `curl_command` ou `codigo_python`
2. Após criar, use `acao="definir_variaveis"` para cadastrar o valor no banco
3. A ferramenta já estará funcional

**Exemplo — definir variável após criar:**
```
fluxi_ferramentas(acao="definir_variaveis", ferramenta_id=42, variaveis={"API_KEY": "sk-abc123"})
```

Para variáveis não-secretas:
```
fluxi_ferramentas(acao="definir_variaveis", ferramenta_id=42, variaveis={
  "API_KEY": {"valor": "sk-abc123", "tipo": "secret", "descricao": "Chave da API OpenWeather", "is_secret": true},
  "BASE_URL": {"valor": "https://api.openweathermap.org", "tipo": "string", "is_secret": false}
})
```

---

## Response Map — Filtrar Resposta da API

Quando a API retorna muitos campos e você quer passar apenas os relevantes ao LLM, use `response_map`.

**Exemplo:** API retorna `{"coord": {...}, "weather": [...], "main": {"temp": 22.5, "humidity": 60}, "name": "São Paulo"}`

```json
{"main.temp": "temperatura", "main.humidity": "umidade", "name": "cidade"}
```

O LLM receberá apenas: `{"temperatura": 22.5, "umidade": 60, "cidade": "São Paulo"}`

---

## Output e Canal

- `output="LLM"` — resultado vai para o contexto do LLM (padrão)
- `output="USER"` — enviado diretamente ao WhatsApp, LLM não vê o conteúdo
- `output="BOTH"` — enviado ao usuário E ao LLM

Quando `output="USER"` ou `"BOTH"`, defina `channel`:
- `TEXT` — mensagem de texto
- `IMAGE` — imagem (resultado deve conter URL ou base64)
- `AUDIO` — áudio
- `VIDEO` — vídeo
- `DOCUMENT` — documento/arquivo

---

## Post Instruction

Instrução oculta para o LLM sobre como apresentar ou processar o resultado.
O usuário não vê esta instrução — ela guia o comportamento do agente.

**Exemplo:** `"Apresente a temperatura em formato amigável. Se a cidade não for encontrada, peça ao usuário para verificar o nome."`

---

## Encadeamento com `next_tool`

Define o nome de outra ferramenta a ser executada automaticamente após esta.
Útil para pipelines: buscar dados → processar → enviar resultado.

**Exemplo:** ferramenta `buscar_produto` com `next_tool="formatar_orcamento"` executa as duas em sequência.

---

## Ações disponíveis no fluxi_ferramentas

| Ação | Parâmetros obrigatórios | Descrição |
|------|------------------------|-----------|
| `listar` | — | Lista todas as ferramentas com IDs |
| `criar` | `dados` | Cria nova ferramenta |
| `editar` | `ferramenta_id`, `dados` | Edita ferramenta existente |
| `deletar` | `ferramenta_id` | Remove ferramenta |
| `associar_agente` | `ferramenta_id`, `agente_id` | Vincula ferramenta a um agente |
| `desassociar_agente` | `ferramenta_id`, `agente_id` | Remove vínculo |
| `listar_agente` | `agente_id` | Lista ferramentas de um agente |
| `definir_variaveis` | `ferramenta_id`, `variaveis` | Cadastra/atualiza variáveis seguras (`{var.CHAVE}`) |
| `listar_variaveis` | `ferramenta_id` | Lista chaves cadastradas (valores secrets ficam ocultos) |

---

## Exemplo completo — Ferramenta WEB com autenticação

### 1. Criar a ferramenta
```json
{
  "nome": "buscar_clima",
  "descricao": "Busca temperatura e condições climáticas de uma cidade",
  "tool_type": "WEB",
  "tool_scope": "PRINCIPAL",
  "params": "{\"cidade\": {\"type\": \"string\", \"required\": true, \"description\": \"Nome da cidade\"}}",
  "curl_command": "curl -s 'https://api.openweathermap.org/data/2.5/weather?q={cidade}&appid={var.API_KEY}&units=metric&lang=pt'",
  "response_map": "{\"main.temp\": \"temperatura\", \"main.humidity\": \"umidade\", \"weather.0.description\": \"condicao\", \"name\": \"cidade\"}",
  "output": "LLM",
  "post_instruction": "Apresente o clima de forma amigável com emoji. Se a cidade não for encontrada, peça ao usuário para verificar o nome.",
  "ativa": true
}
```

### 2. Definir a API key
```
fluxi_ferramentas(acao="definir_variaveis", ferramenta_id=<id_retornado>, variaveis={"API_KEY": "sua_chave_aqui"})
```

### 3. Associar ao agente
```
fluxi_ferramentas(acao="associar_agente", ferramenta_id=<id>, agente_id=<agente_id>)
```
""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "meta",
                "icone": "🔧",
                "versao": "1.0",
                "ativa": True,
            },
            {
                "nome": "meta_skills",
                "descricao": "Instruções para criar e editar skills (pacotes de instruções especializadas)",
                "instrucao_completa": """# Como Criar e Gerenciar Skills no Fluxi

Skills são **pacotes de instruções especializadas** carregadas sob demanda via `invocar_skill`.
O agente só carrega a skill quando precisar daquelas instruções — sem ocupar contexto o tempo todo.

## Campos de uma Skill

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `nome` | string | Identificador único (snake_case) |
| `descricao` | string (max 250) | Resumo — aparece no sistema prompt |
| `instrucao_completa` | text | Instruções detalhadas em markdown |
| `script_codigo` | Python (opcional) | Executado antes das instruções para dados dinâmicos |
| `ferramentas_ids` | JSON array (opcional) | IDs de ferramentas extras injetadas ao invocar |
| `categoria` | string | Ex: "vendas", "suporte", "financeiro", "meta" |
| `icone` | emoji | Ícone visual |

## Como criar uma skill

```
fluxi_skills(acao="criar", dados={
  "nome": "atendimento_vip",
  "descricao": "Instruções para atendimento de clientes VIP",
  "instrucao_completa": "# Atendimento VIP\\n\\nTrate clientes VIP com prioridade máxima...",
  "categoria": "suporte",
  "icone": "⭐",
  "ativa": true
})
```

## Como editar instrução de uma skill existente

```
fluxi_skills(acao="editar", skill_id=3, dados={"instrucao_completa": "Nova instrução..."})
```

## Como adicionar skill a um agente

```
fluxi_skills(acao="associar_agente", agente_id=1, skill_id=3)
```

## Boas práticas para instrucao_completa

1. Use markdown com títulos, listas e exemplos de código
2. Seja específico — a skill substitui um humano descrevendo o processo
3. Inclua exemplos de inputs e outputs esperados
4. Mencione quais ferramentas usar naquele contexto
5. Defina o critério de sucesso
""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "meta",
                "icone": "📚",
                "versao": "1.0",
                "ativa": True,
            },
            {
                "nome": "meta_agentes",
                "descricao": "Instruções para criar e configurar agentes personalizados no Fluxi",
                "instrucao_completa": """# Como Criar e Configurar Agentes no Fluxi

Você tem acesso à ferramenta `fluxi_agentes` para criar, editar e gerenciar agentes.

---

## Campos de um Agente

### Identidade
| Campo | Obrigatório | Descrição |
|-------|-------------|-----------|
| `sessao_id` | Sim (criar) | ID da sessão WhatsApp onde o agente será criado |
| `codigo` | Sim | Prefixo único de roteamento (ex: "fin", "sup", "ven") — máx 10 chars |
| `nome` | Sim | Nome exibido do agente |
| `descricao` | Não | Descrição interna (não aparece no prompt) |
| `ativo` | Não | Se o agente está disponível (padrão: true) |

### System Prompt (7 campos — todos obrigatórios)
| Campo | O que define |
|-------|-------------|
| `agente_papel` | Quem o agente É — identidade e especialidade. Ex: "Você é um assistente financeiro pessoal..." |
| `agente_objetivo` | O que deve ALCANÇAR — meta geral. Ex: "Ajudar o usuário a registrar e consultar gastos..." |
| `agente_politicas` | Como deve SE COMPORTAR — tom, regras de interação. Ex: "Seja direto. Confirme valores antes de registrar." |
| `agente_tarefa` | O que faz TECNICAMENTE — fluxo de uso das ferramentas. Ex: "Use a ferramenta X para registrar, Y para consultar..." |
| `agente_objetivo_explicito` | Critério mensurável de sucesso. Ex: "Dado registrado com confirmação ao usuário" |
| `agente_publico` | Para quem é — perfil do usuário. Ex: "Usuário final via WhatsApp, sem conhecimento técnico" |
| `agente_restricoes` | O que NÃO fazer. Ex: "Não invente valores. Não acesse dados de outros usuários." |

### Configuração LLM (todos opcionais — null usa o padrão global)
| Campo | Descrição |
|-------|-----------|
| `modelo_llm` | Modelo específico. Ex: `gpt-4o`, `claude-3-5-sonnet`, `gemini-2.0-flash` |
| `temperatura` | Criatividade — 0.0 (determinístico) a 2.0 (criativo). Recomendado: 0.7 |
| `max_tokens` | Máximo de tokens na resposta. Ex: 1024, 2048 |
| `provedor_llm_id` | ID do provedor LLM — use `fluxi_agentes(acao="listar")` para ver IDs disponíveis |

### Integrações (opcionais)
| Campo | Descrição |
|-------|-----------|
| `rag_id` | ID de uma base de conhecimento RAG — injeta busca vetorial automaticamente |

---

## Ações disponíveis no fluxi_agentes

| Ação | Parâmetros obrigatórios | Descrição |
|------|------------------------|-----------|
| `listar` | — | Lista todos os agentes (filtra por `sessao_id` se informado) |
| `criar` | `dados` | Cria novo agente |
| `editar` | `agente_id`, `dados` | Edita campos do agente (parcial — só os campos informados) |
| `deletar` | `agente_id` | Remove agente permanentemente |
| `obter` | `agente_id` | Retorna todos os campos do agente — use antes de editar |
| `listar_skills` | `agente_id` | Lista skills associadas ao agente |
| `associar_skill` | `agente_id`, `skill_id` | Vincula uma skill ao agente |
| `desassociar_skill` | `agente_id`, `skill_id` | Remove vínculo de skill |
| `ativar_sandbox` | `agente_id`, `ativo` | Ativa (true) ou desativa (false) o modo sandbox |

---

## Roteamento por prefixo

O usuário ativa um agente específico enviando `#codigo mensagem`:
- `#fin compra mercado 50 reais` → agente com código "fin"
- `#sup meu pedido não chegou` → agente com código "sup"
- Sem prefixo → agente ativo padrão da sessão

---

## Modo Sandbox

Quando ativo, o agente ganha um ambiente de execução completo:
- Executar código Python
- Controlar navegador (screenshots, cliques, formulários)
- Enviar arquivos e screenshots via WhatsApp
- Máximo de iterações aumenta de 10 para 25

Ative com: `fluxi_agentes(acao="ativar_sandbox", agente_id=<id>, ativo=true)`

---

## Fluxo: criar um agente do zero

**Passo 1 — Obter o sessao_id:**
```
fluxi_agentes(acao="listar")
```

**Passo 2 — Criar o agente:**
```json
{
  "sessao_id": 1,
  "codigo": "fin",
  "nome": "Assistente Financeiro",
  "descricao": "Registra gastos e consulta extrato via WhatsApp",
  "agente_papel": "Você é um assistente financeiro pessoal especializado em controle de gastos.",
  "agente_objetivo": "Ajudar o usuário a manter controle financeiro sem abrir apps ou planilhas.",
  "agente_politicas": "Seja direto. Confirme valores antes de registrar. Use linguagem simples.",
  "agente_tarefa": "Use registrar_gasto para anotar despesas e consultar_extrato para listar o histórico.",
  "agente_objetivo_explicito": "Gasto registrado com confirmação: 'Anotei! R$50 em mercado hoje.'",
  "agente_publico": "Usuário final via WhatsApp, sem conhecimento técnico.",
  "agente_restricoes": "Não invente valores. Não registre sem confirmação. Não acesse dados de outros usuários."
}
```

**Passo 3 — Associar ferramentas:**
```
fluxi_ferramentas(acao="associar_agente", agente_id=<id>, ferramenta_id=<id>)
```

**Passo 4 (opcional) — Associar skills:**
```
fluxi_agentes(acao="associar_skill", agente_id=<id>, skill_id=<id>)
```

**Passo 5 (opcional) — Vincular base de conhecimento RAG:**
```
fluxi_agentes(acao="editar", agente_id=<id>, dados={"rag_id": <rag_id>})
```

---

## Fluxo: editar um agente existente

Sempre use `obter` antes para não sobrescrever campos que não quer mudar:
```
fluxi_agentes(acao="obter", agente_id=<id>)
```

Edite apenas os campos necessários:
```
fluxi_agentes(acao="editar", agente_id=<id>, dados={
  "agente_restricoes": "Não invente valores. Não registre sem confirmação. Responda sempre em menos de 3 linhas."
})
```

---

## Fluxo: configurar modelo LLM específico para o agente

```
fluxi_agentes(acao="editar", agente_id=<id>, dados={
  "modelo_llm": "gpt-4o",
  "temperatura": 0.3,
  "max_tokens": 1024
})
```
Para voltar ao padrão global, edite com os campos como `null`.
""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "meta",
                "icone": "🤖",
                "versao": "1.0",
                "ativa": True,
            },
            {
                "nome": "meta_rag",
                "descricao": "Instruções para criar e gerenciar bases de conhecimento (RAG) usando a ferramenta fluxi_rag",
                "instrucao_completa": """# Como Gerenciar Bases de Conhecimento (RAG)

Você tem acesso à ferramenta `fluxi_rag` para criar e gerenciar bases de conhecimento RAG diretamente.

## Quando usar RAG?

- FAQs, manuais, políticas da empresa
- Catálogos extensos (mais de 2.000 palavras)
- Informações que mudam frequentemente
- Documentos que o usuário enviou e quer consultar depois

## Fluxo completo: criar RAG do zero

**Passo 1 — Criar a base:**
```
fluxi_rag(acao="criar", nome="Manual do Produto", descricao="FAQ e políticas da empresa")
→ retorna {"sucesso": true, "id": 3, "nome": "Manual do Produto"}
```

**Passo 2 — Adicionar conteúdo:**

Via texto direto:
```
fluxi_rag(acao="adicionar_texto", rag_id=3, titulo="Política de devolução",
          texto="Devoluções são aceitas em até 30 dias...")
```

Via arquivo (quando o usuário enviou um arquivo):
```
fluxi_rag(acao="adicionar_arquivo", rag_id=3, titulo="Manual PDF",
          arquivo_path="/caminho/absoluto/para/arquivo.pdf")
```

**Passo 3 — Vincular ao agente:**
```
fluxi_rag(acao="vincular_agente", rag_id=3, agente_id=1)
```

Após vincular, o agente ganha automaticamente a tool `buscar_base_conhecimento`.

## Fluxo: quando o usuário envia um arquivo

1. Pergunte o que ele deseja:
   - "Deseja armazenar este documento como base de conhecimento?"
   - "Ou prefere que eu analise o conteúdo agora?"
2. Se quiser armazenar como RAG:
   - Crie um RAG com `fluxi_rag(acao="criar", nome=...)`
   - Adicione o arquivo com `fluxi_rag(acao="adicionar_arquivo", arquivo_path=<caminho>)`
   - Pergunte se deve vincular ao agente atual
3. Se quiser analisar o conteúdo: encaminhe ao Coding Agent com `#code`

## Formatos suportados

`.pdf`, `.txt`, `.md`, `.docx`, `.csv`

## Outras operações

```
fluxi_rag(acao="listar")                        # ver todas as bases
fluxi_rag(acao="obter", rag_id=3)               # detalhes de uma base
fluxi_rag(acao="resetar", rag_id=3)             # remover todos os chunks
fluxi_rag(acao="deletar", rag_id=3)             # remover a base inteira
```
""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "meta",
                "icone": "📖",
                "versao": "1.0",
                "ativa": True,
            },
            {
                "nome": "meta_mcp",
                "descricao": "Instruções para conectar servidores MCP e integrar ferramentas externas",
                "instrucao_completa": """# Como Conectar Servidores MCP ao Agente

Você tem acesso à ferramenta `fluxi_mcp` para gerenciar servidores MCP diretamente.

## O que é MCP?

Model Context Protocol conecta ferramentas externas ao agente como se fossem tools nativas.
Após conectar, as tools do servidor aparecem automaticamente no contexto do agente.

## Passo 1 — Ver presets disponíveis

```
fluxi_mcp(acao="listar_presets")
```

Retorna lista de servidores pré-configurados com seus `key` e `inputs` necessários.

## Passo 2a — Conectar via preset (forma mais simples)

```
fluxi_mcp(
  acao="conectar_preset",
  agente_id=1,
  preset_key="github",
  nome="GitHub",
  inputs='{"github_token": "ghp_..."}'
)
```

O preset cuida de tudo: transport, command, args. Só preencha os `inputs` pedidos.

## Passo 2b — Conectar via URL (SSE ou Streamable HTTP)

Para qualquer servidor MCP acessível por URL:

```
fluxi_mcp(
  acao="conectar_url",
  agente_id=1,
  nome="Meu Servidor",
  url="http://localhost:8080/mcp",
  transport_type="streamable-http",
  headers='{"Authorization": "Bearer TOKEN"}'
)
```

## Passo 2c — Conectar via STDIO (processo local)

Para servidores MCP que rodam como processo local:

```
fluxi_mcp(
  acao="conectar_stdio",
  agente_id=1,
  nome="Servidor Local",
  command="python",
  args='["workspaces/meu_servidor/server.py"]',
  env_vars='{"CHAVE": "valor"}'
)
```

## Passo 2d — Instalar via JSON one-click

Muitos servidores MCP fornecem um JSON de configuração pronto. Cole diretamente:

```
fluxi_mcp(
  acao="one_click",
  agente_id=1,
  json_config='{
    "mcpServers": {
      "meu-servidor": {
        "command": "npx",
        "args": ["-y", "@nome/servidor-mcp"],
        "env": {"TOKEN": "abc"}
      }
    }
  }'
)
```

## Verificar e sincronizar

Após conectar, verifique as tools disponíveis:

```
fluxi_mcp(acao="listar", agente_id=1)
```

Se precisar forçar re-sincronização:

```
fluxi_mcp(acao="sincronizar", mcp_client_id=<id>)
```

## Remover um servidor MCP

```
fluxi_mcp(acao="deletar", mcp_client_id=<id>)
```

## Observações importantes

- O agente pode ter no máximo 5 servidores MCP ativos
- Servidores STDIO precisam que o comando esteja instalado no servidor
- As tools MCP aparecem com prefixo `mcp_` no loop do agente
- Credenciais sensíveis ficam nas variáveis de ambiente do servidor
""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "meta",
                "icone": "🔌",
                "versao": "1.0",
                "ativa": True,
            },
            {
                "nome": "meta_agendamento",
                "descricao": "Instruções para agendar tarefas futuras (lembretes, verificações periódicas, callbacks do próprio agente)",
                "instrucao_completa": """# Como Agendar Tarefas Futuras

Você tem acesso à ferramenta `fluxi_agendamento` para criar tarefas que serão
executadas pelo sistema em um momento futuro — lembretes, mensagens automáticas,
verificações periódicas (heartbeat) ou callbacks que reativam você mesmo após
um intervalo.

## Quando usar?

- Usuário pede "me lembre", "me avise", "fala comigo daqui a X minutos/horas".
- Você precisa fazer follow-up depois de um tempo (ex: cliente disse que ia retornar).
- Verificação periódica de uma condição (ex: a cada 30min checar se algo mudou).
- Agendar uma mensagem para uma data/hora específica.

## Sempre que NÃO usar

- Para responder agora — só use se há claramente um delay envolvido.
- Para guardar fatos: isso vai para RAG ou memória do agente, não para agendamento.

## 3 tipos de ação possível

### 1. `enviar_mensagem` — mandar texto pronto
Use quando você já sabe o texto exato que será enviado.

```
fluxi_agendamento(
    acao="criar",
    titulo="Lembrete consulta",
    tipo="once",
    quando="2026-05-28T09:00:00",
    acao_tarefa="enviar_mensagem",
    sessao_id=<id da sessão>,
    telefone_destino="<telefone do cliente, só dígitos>",
    payload='{"texto": "Bom dia! Lembrete: sua consulta é hoje às 14h."}'
)
```

### 2. `callback_agente` — você mesmo voltar a pensar depois
Use quando precisar reavaliar uma situação no futuro. O sistema vai re-injetar
o `prompt` como se fosse uma mensagem do usuário, e você responde normalmente.

```
fluxi_agendamento(
    acao="criar",
    titulo="Follow-up proposta cliente",
    tipo="once",
    quando="2026-05-27T15:00:00",
    acao_tarefa="callback_agente",
    sessao_id=<id>,
    agente_id=<id>,
    telefone_destino="<telefone>",
    payload='{"prompt": "Verifique se o cliente já respondeu sobre a proposta de R$5.000 enviada ontem. Se sim, agradeça e siga o fluxo. Se não, mande um lembrete amigável."}'
)
```

### 3. `rodar_ferramenta` — executar uma tool já cadastrada
Use quando o disparo precisa rodar uma ferramenta específica (ex: buscar status numa API).

```
fluxi_agendamento(
    acao="criar",
    titulo="Checar status pedido",
    tipo="interval",
    quando="600",
    acao_tarefa="rodar_ferramenta",
    sessao_id=<id>,
    telefone_destino="<telefone>",
    payload='{"nome_ferramenta": "consultar_pedido", "argumentos": {"pedido_id": 123}}',
    max_execucoes=12
)
```

## Tipos de schedule (`tipo`)

| tipo | `quando` | Exemplo |
|------|----------|---------|
| `once` | ISO timestamp | `"2026-05-27T09:00:00"` |
| `interval` | segundos | `"300"` (a cada 5 min) — mínimo 10s |
| `cron` | expressão cron | `"0 9 * * *"` (todo dia 9h) |

Para `interval` e `cron`, use `max_execucoes` se quiser limitar quantas vezes roda.

## Como calcular horários

A ferramenta `obter_data_hora_atual` te dá o agora. Faça a soma manualmente:
- "Daqui a 10 minutos" → pegue agora, some 10min, formate ISO.
- "Amanhã 9h" → use a data de amanhã com hora 09:00:00.

## Operações de gerenciamento

```
fluxi_agendamento(acao="listar")                              # ver todas
fluxi_agendamento(acao="listar", telefone_destino="551199...") # filtra por cliente
fluxi_agendamento(acao="obter", tarefa_id=3)                   # detalhes
fluxi_agendamento(acao="cancelar", tarefa_id=3)                # marca como cancelada
fluxi_agendamento(acao="deletar", tarefa_id=3)                 # remove de vez
```

## Checklist antes de criar

1. ✅ Tenho `sessao_id` e `telefone_destino`?
2. ✅ A data/hora faz sentido (não está no passado)?
3. ✅ O `payload` está em JSON válido como STRING?
4. ✅ Para `callback_agente`, o `prompt` é claro o bastante para você mesmo entender depois?

## Confirme com o usuário

Antes de criar uma tarefa relevante, **resuma o que vai agendar**:
> "Vou te avisar amanhã às 9h sobre a consulta. Pode confirmar?"

Só crie a tarefa após o "sim" — agendamentos perdidos ou indesejados quebram confiança.
""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "meta",
                "icone": "⏰",
                "versao": "1.0",
                "ativa": True,
            },
            {
                "nome": "meta_sistema_completo",
                "descricao": "Processo completo para criar sistemas personalizados do zero via Coding Agent",
                "instrucao_completa": """# Como Criar Sistemas Completos do Zero

## Visão Geral

```
1. PLANEJAR  → Entender o que o sistema precisa fazer
2. CONSTRUIR → Coding Agent cria arquivos e scripts
3. REGISTRAR → Coding Agent registra ferramentas no Fluxi
4. CONFIGURAR → Coding Agent cria o agente personalizado
5. USAR      → Usuário acessa com #prefixo
```

## Passo 1: PLANEJAR com o usuário

Confirme antes de construir:
- **O que armazenar?** (gastos, contatos, tarefas...)
- **Quais operações?** (adicionar, consultar, resumir...)
- **Qual o prefixo?** (código do agente: "fin", "task"...)
- **Formato de entrada?** (texto livre ou estruturado?)

## Passo 2: CONSTRUIR com o Coding Agent

Encaminhe ao Coding Agent com este template:

```
#code Crie um sistema completo de [NOME]:

ARQUIVO DE DADOS: workspaces/[nome]/dados.jsonl
SCRIPT: workspaces/[nome]/gerenciador.py

Funções necessárias:
- [funcao_1(parametros)] → retorno esperado
- [funcao_2(parametros)] → retorno esperado

Após criar e TESTAR os arquivos, use fluxi_criar_ferramenta para
registrar cada função como uma tool CODE, e fluxi_criar_agente
para criar o agente com codigo="[prefixo]".
Informe os IDs criados ao final.
```

## Passo 3: O Coding Agent registra no Fluxi

O Coding Agent usa suas tools fluxi_* para registrar:

- `fluxi_listar_recursos` — obtém sessao_id de agente existente
- `fluxi_criar_ferramenta` — registra cada função como tool
- `fluxi_criar_agente` — cria o agente com as ferramentas

## Resultado esperado

```
✅ Sistema [nome] criado!
- Ferramenta 'funcao_1' (ID: 12)
- Ferramenta 'funcao_2' (ID: 13)
- Agente '[nome]' com código #[prefixo] (ID: 5)

Use: #[prefixo] <mensagem>
```

## Exemplo: Sistema Financeiro

```
#code Crie um sistema de controle de gastos:

ARQUIVO: workspaces/financeiro/gastos.jsonl
SCRIPT: workspaces/financeiro/gerenciador.py

Funções:
- anotar(item, valor, categoria="geral") → {"sucesso": True, "mensagem": "..."}
- listar(data=None) → lista de gastos
- resumo() → total por categoria

Teste cada função via shell_exec antes de registrar.
Após testar, registre como ferramentas e crie agente
com codigo="fin", nome="Financeiro".
```
""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "meta",
                "icone": "⚡",
                "versao": "1.0",
                "ativa": True,
            },
        ]

        # ── Skills comportamentais do Coding Agent ──
        skills_padrao += [
            {
                "nome": "coding-planejamento",
                "descricao": "Planejamento antes de executar. Invoque SEMPRE que receber uma tarefa com 3+ passos.",
                "instrucao_completa": """# Planejamento

Antes de escrever código, entenda o que está construindo. Leia o pedido, identifique o que será entregue, e planeje a ordem de execução.

## Convenções
- Primeiro entenda, depois construa. Nunca comece a codar sem saber para onde está indo.
- Identifique o que o usuário espera receber — nem sempre é literal. Interprete a intenção.
- Determine a sequência: o que depende do quê. Construa a fundação antes do acabamento.
- A cada arquivo criado, pergunte-se: isso é consistente com o resto?
- Antes de entregar, releia o que construiu como se fosse o usuário recebendo pela primeira vez.

## Escopo
- Prefira entregar menos funcionalidades bem acabadas do que muitas superficiais.
- Código completo e funcional. Nunca placeholders, nunca "TODO", nunca funcionalidade cortada.
- Dados devem ser verossímeis e coerentes, nunca genéricos ou sequenciais sem sentido.

## Auto-revisão
Você é o desenvolvedor E o revisor. Antes da entrega: o resultado é algo que você teria orgulho de mostrar?""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "coding",
                "icone": "📋",
                "versao": "2.0",
                "ativa": True,
            },
            {
                "nome": "coding-delegacao",
                "descricao": "Quando usar agent_run e task_create. Invoque quando considerar delegação.",
                "instrucao_completa": """# Delegação

O sub-agente não tem acesso ao seu contexto — ele parte do zero.

## Quando delegar
Delegue tarefas auto-contidas: input claro, output claro, sem dependência do estado atual. Pesquisas e tarefas de infraestrutura são naturalmente auto-contidas.

## Quando NÃO delegar
Se o resultado precisa ser coerente com artefatos que você criou, faça você mesmo. Só você tem a visão do todo.

## Como delegar bem
Escreva o goal como um briefing para alguém que acabou de chegar: o que fazer, o contexto relevante, e que informação retornar. Quanto mais preciso, melhor.

## Background
Use `task_create` para trabalho independente que pode rodar enquanto você continua.""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "coding",
                "icone": "🤖",
                "versao": "2.0",
                "ativa": True,
            },
            {
                "nome": "coding-qualidade",
                "descricao": "Auto-revisão de qualidade antes de entregar código. Invoque antes de finalizar qualquer entrega.",
                "instrucao_completa": """# Qualidade

Antes de entregar, revise como um desenvolvedor sênior revisaria o código de um junior.

## Padrão
- O código funciona se aberto agora? Teste mentalmente ou com shell.
- Segue as convenções do projeto e da linguagem? Olhe os vizinhos.
- Nomes de variáveis, funções e arquivos comunicam intenção?
- Está tratando erros e edge cases razoáveis?
- Sem segredos, tokens ou credenciais no código.

## Completude
- Todos os requisitos do pedido foram atendidos?
- Dados são realistas e coerentes — nunca genéricos ou placeholder.
- A experiência de uso é profissional, não um protótipo.
- Se é frontend: funciona, é visualmente coerente, responsivo no mínimo razoável.
- Se é backend: trata erros, retorna respostas claras, valida inputs.

## Regra
Se algum aspecto não está bom, corrija antes de entregar. Nunca entregue sabendo que tem problema.""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "coding",
                "icone": "✅",
                "versao": "2.0",
                "ativa": True,
            },
            {
                "nome": "coding-projeto",
                "descricao": "Organização de workspace e estrutura de projetos. Invoque ao iniciar projeto novo.",
                "instrucao_completa": """# Organização de Projetos

## Convenções
- Nunca trabalhe na raiz do workspace. Cada projeto tem seu diretório.
- Use `project_init` para criar projetos novos com estrutura adequada ao template.
- Use `workspace_info` para ver o que já existe antes de criar algo novo.
- Registre o contexto do projeto em `memory_write` para persistir entre tarefas.

## Fluxo
1. Verifique o workspace atual
2. Crie o projeto com `project_init` escolhendo o template adequado (python, node, web, empty)
3. Salve o contexto na memória: nome, path, stack, comandos úteis

## Princípio
1 projeto = 1 diretório = 1 entry na memória.""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "coding",
                "icone": "📁",
                "versao": "2.0",
                "ativa": True,
            },
            {
                "nome": "coding-web-research",
                "descricao": "Pesquisa web eficiente. Invoque quando precisar pesquisar documentação, APIs ou soluções.",
                "instrucao_completa": """# Pesquisa Web

## Princípio
Pesquisa é um meio, não um fim. Busque o que precisa e volte ao trabalho.

## Convenções
- Para pesquisas simples (1-2 buscas), faça direto com `web_search` / `web_fetch`.
- Para pesquisas que exigiriam 3+ buscas, delegue com `agent_run` — uma iteração sua vale mais que várias buscas sequenciais.
- Use queries específicas e diretas. Quanto mais preciso o termo, melhor o resultado.
- Prefira `shell_exec` quando a informação pode vir de package managers ou docs locais.
- Não releia a mesma página. Extraia o que precisa e siga em frente.""",
                "script_codigo": None,
                "ferramentas_ids": None,
                "categoria": "coding",
                "icone": "🔍",
                "versao": "2.0",
                "ativa": True,
            },
        ]

        # Skills que são auto-atualizadas por versão (meta + coding)
        _AUTO_UPDATE_SKILLS = {"meta_ferramentas", "meta_skills", "meta_agentes", "meta_rag", "meta_mcp", "meta_agendamento", "meta_sistema_completo",
                               "coding-planejamento", "coding-delegacao", "coding-qualidade", "coding-projeto", "coding-web-research"}

        for skill_data in skills_padrao:
            nome = skill_data["nome"]
            existe = SkillService.obter_por_nome(db, nome)
            if not existe:
                skill = SkillCriar(**skill_data)
                SkillService.criar(db, skill)
                logger.info("Skill padrão criada: %s", nome)
            elif nome in _AUTO_UPDATE_SKILLS:
                # Auto-update: atualiza instrução e descrição se a versão mudou ou conteúdo difere
                changed = False
                nova_versao = skill_data.get("versao", "1.0")
                if nova_versao != existe.versao:
                    existe.versao = nova_versao
                    changed = True
                nova_instrucao = skill_data.get("instrucao_completa")
                if nova_instrucao and existe.instrucao_completa != nova_instrucao:
                    existe.instrucao_completa = nova_instrucao
                    changed = True
                nova_descricao = skill_data.get("descricao")
                if nova_descricao and existe.descricao != nova_descricao:
                    existe.descricao = nova_descricao
                    changed = True
                if changed:
                    db.commit()
                    logger.info("Skill '%s' atualizada", nome)

        # ── Auto-wiring: injeta ferramentas_ids nas meta skills ──
        # Cada meta skill carrega sua(s) ferramenta(s) apenas quando invocada.
        # Resolve IDs em tempo de execução para evitar problema de chicken-and-egg.
        from ferramenta.ferramenta_service import FerramentaService

        _meta_tool_map = {
            "meta_ferramentas": ["fluxi_ferramentas"],
            "meta_skills":      ["fluxi_skills"],
            "meta_agentes":     ["fluxi_agentes", "fluxi_ferramentas"],
            "meta_rag":         ["fluxi_rag"],
            "meta_mcp":         ["fluxi_mcp"],
            "meta_agendamento": ["fluxi_agendamento", "obter_data_hora_atual"],
            # meta_sistema_completo usa tools do Coding Agent diretamente — sem injeção
        }

        for skill_nome, tool_nomes in _meta_tool_map.items():
            skill = SkillService.obter_por_nome(db, skill_nome)
            if not skill:
                continue
            tool_ids = []
            for tool_nome in tool_nomes:
                tool = FerramentaService.obter_por_nome(db, tool_nome)
                if tool:
                    tool_ids.append(tool.id)
            if not tool_ids:
                continue
            ids_json = json.dumps(tool_ids)
            if skill.ferramentas_ids != ids_json:
                skill.ferramentas_ids = ids_json
                db.commit()
                logger.info("Meta skill '%s' wired com ferramentas_ids=%s", skill_nome, tool_ids)

        # ── Auto-wiring: associar skills coding-* ao agente de coding ──
        try:
            from coding_agent.coding_model import CodingSession
            coding_sessions = db.query(CodingSession).filter(CodingSession.ativa == True).all()
            coding_skill_names = [
                "coding-planejamento", "coding-delegacao", "coding-qualidade",
                "coding-projeto", "coding-web-research",
            ]
            coding_skills = [SkillService.obter_por_nome(db, n) for n in coding_skill_names]
            coding_skills = [s for s in coding_skills if s is not None]

            if coding_skills and coding_sessions:
                for cs in coding_sessions:
                    agente_id = cs.agente_id
                    # Verifica quais skills já estão associadas
                    existing = SkillService.listar_skills_agente(db, agente_id)
                    existing_names = {s.nome for s in existing}
                    for sk in coding_skills:
                        if sk.nome not in existing_names:
                            db.execute(
                                agente_skill.insert().values(
                                    agente_id=agente_id,
                                    skill_id=sk.id,
                                    posicao=0,
                                    ativa=True,
                                )
                            )
                            logger.info("Coding skill '%s' associada ao agente %d", sk.nome, agente_id)
                    db.commit()
        except Exception as _e:
            logger.warning("Erro ao auto-wiring coding skills: %s", _e)
