# Exemplo MCP - Dieta

Servidor MCP de exemplo para controle de dieta e refeições, demonstrando como criar MCPs customizados para integrar com o Fluxi.

## O que é este exemplo?

Este é um servidor MCP funcional que permite:

- Registrar refeições (café da manhã, almoço, lanche, jantar, etc)
- Consultar refeições do dia
- Ver histórico de dias anteriores
- Calcular totais de calorias
- Definir e verificar metas calóricas

## Instalação

```bash
pip install fastmcp
```

## Como usar

### 1. Inicie o servidor MCP

```bash
cd exemplo_mcp
python dieta_mcp.py
```

O servidor vai iniciar em `http://localhost:8002/sse`

### 2. Configure no Fluxi

Acesse `http://localhost:8000/mcp/agente/{id-do-agente}/json-config`

Preencha:
- **Nome do Servidor MCP**: `DIETA`
- **Configuração JSON**:

```json
{
  "mcpServers": {
    "dieta": {
      "serverUrl": "http://localhost:8002/sse"
    }
  }
}
```

### 3. Sincronize as ferramentas

Após salvar, clique em "Sincronizar Ferramentas" para carregar as tools do MCP

## Ferramentas Disponíveis

| Ferramenta | Descrição |
|------------|-----------|
| `registrar_refeicao` | Registra uma refeição com tipo, alimentos e calorias |
| `listar_refeicoes_hoje` | Lista todas as refeições de hoje |
| `listar_refeicoes_data` | Lista refeições de uma data específica |
| `resumo_semanal` | Resumo dos últimos 7 dias |
| `deletar_refeicao` | Remove uma refeição pelo ID |
| `definir_meta_calorica` | Define meta diária de calorias |
| `verificar_meta_hoje` | Verifica progresso vs meta |

## Exemplos de uso via WhatsApp

Após conectar o MCP a um agente no Fluxi:

```
Usuário: Registra meu café da manhã: 2 ovos mexidos com pão integral, 350 calorias
Agente: Refeição registrada! Café da manhã: 2 ovos mexidos com pão integral (350 kcal)

Usuário: Quanto já comi hoje?
Agente: [Lista todas as refeições e total de calorias]

Usuário: Como estou na meta?
Agente: Consumido: 1200 kcal (60% da meta de 2000 kcal). Restante: 800 kcal.

Usuário: Me mostra a semana
Agente: [Resumo dos últimos 7 dias com média diária]
```

## Estrutura

```
exemplo_mcp/
├── __init__.py
├── dieta_mcp.py      # Servidor MCP principal
├── dieta_data.json   # Dados persistidos (criado automaticamente)
└── README.md
```

## Como criar seu próprio MCP

Este exemplo mostra o padrão básico:

```python
from fastmcp import FastMCP

# 1. Criar servidor
mcp = FastMCP("Nome do Servidor")

# 2. Adicionar ferramentas com @mcp.tool
@mcp.tool
def minha_ferramenta(param1: str, param2: int) -> str:
    """Descrição da ferramenta."""
    # Sua lógica aqui
    return "Resultado"

# 3. Rodar
if __name__ == "__main__":
    mcp.run()
```

## Dicas

- Use type hints nos parâmetros (o LLM usa isso para entender os tipos)
- Docstrings são importantes (o LLM usa para entender o que a ferramenta faz)
- Retorne strings formatadas para melhor leitura
- Use JSON ou banco simples para persistência

---

**Módulo:** exemplo_mcp  
**Framework:** FastMCP  
**Integração:** Fluxi MCP Client
