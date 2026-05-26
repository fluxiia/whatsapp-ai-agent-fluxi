"""
Definição das tools do Coding Agent — filosofia shell-first.

Inspiração: Claude Code usa Bash + Read + Edit + Write + Glob/Grep como
ferramentas primitivas. O LLM faz tudo via shell (npm install, python, git...).

Aqui seguimos o mesmo princípio:
  - shell_exec / shell_start / shell_status / shell_write / shell_kill
  - file_read / file_write / file_edit / file_list / file_find / file_grep / file_zip
  - workspace_info / memory_read / memory_write
  - task_list / task_status
  - send_file_whatsapp / send_screenshot_whatsapp

Removidas por redundância (o shell já cobre):
  sandbox_code_execute, sandbox_nodejs_execute, sandbox_jupyter_execute,
  sandbox_python_packages, sandbox_nodejs_packages, sandbox_nodejs_info
"""
from __future__ import annotations

from typing import Any, Dict, List


def obter_coding_tools(active_skills: List[str] = None) -> List[Dict[str, Any]]:
    """Retorna a lista de tools baseada nas skills ativas."""
    active_skills = active_skills or []
    
    todas_tools = [
        # ══════════════════════════════════════════════════════════
        # SKILLS — Carregamento dinâmico
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "activate_skill",
                "description": (
                    "Ativa um pacote adicional de ferramentas para a tarefa atual. "
                    "Use se precisar de ferramentas específicas não listadas no momento. "
                    "Skills disponíveis: 'fluxi_meta' (criar/editar agentes, ferramentas e skills), "
                    "'browser' (navegação avançada na web)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "enum": ["fluxi_meta", "browser"],
                            "description": "Nome da skill a ativar",
                        },
                    },
                    "required": ["skill_name"],
                },
            },
        },
        # ══════════════════════════════════════════════════════════
        # SHELL — o coração do agente (shell-first)
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "shell_exec",
                "description": (
                    "Executa um comando shell e aguarda o resultado (síncrono). "
                    "Use para comandos rápidos (< 30s): ls, cat, git status, python --version, "
                    "pip install, npm install, node script.js, python script.py, etc. "
                    "Para comandos que podem demorar mais, use shell_start. "
                    "IMPORTANTE: Este é o modo principal de trabalho — use shell para "
                    "instalar dependências, rodar scripts, compilar, testar, criar arquivos "
                    "via echo/heredoc, mover/copiar arquivos (mv, cp), etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": (
                                "Comando shell a executar. Exemplos: "
                                "'npm install', 'python main.py', 'git init', "
                                "'pip install flask', 'ls -la', 'cat arquivo.py'"
                            ),
                        },
                        "cwd": {
                            "type": "string",
                            "description": (
                                "Diretório de trabalho (caminho absoluto). "
                                "Se omitido, usa o workspace da sessão."
                            ),
                        },
                        "timeout": {
                            "type": "number",
                            "description": (
                                "Timeout em segundos (default: 30). "
                                "Se o processo não terminar no tempo, retorna o output parcial "
                                "com um session_id para continuar monitorando via shell_status."
                            ),
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shell_start",
                "description": (
                    "Inicia um processo longo em background e retorna imediatamente com um session_id. "
                    "Use para: servidores (npm start, uvicorn), builds longos (webpack, gradle), "
                    "downloads grandes, instalações demoradas. "
                    "Após iniciar, use shell_status para verificar progresso e shell_write para "
                    "enviar input interativo. Quando terminar, shell_status retornará status='done'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Comando a executar em background",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Diretório de trabalho (absoluto)",
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shell_status",
                "description": (
                    "Consulta o output atual e status de um processo em background. "
                    "Use após shell_start ou quando shell_exec retornou status='running'. "
                    "Retorna: output acumulado, status ('running'|'done'|'error'), exit_code."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "ID da sessão shell retornado por shell_start ou shell_exec",
                        },
                        "tail_lines": {
                            "type": "integer",
                            "description": "Se informado, retorna apenas as últimas N linhas do output (útil para saídas grandes)",
                        },
                    },
                    "required": ["session_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shell_write",
                "description": (
                    "Envia input para um processo shell interativo em execução. "
                    "Use para responder a prompts (ex: 'y' para confirmações), "
                    "enviar comandos a um REPL, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "ID da sessão shell",
                        },
                        "input": {
                            "type": "string",
                            "description": "Texto a enviar ao processo",
                        },
                        "press_enter": {
                            "type": "boolean",
                            "description": "Se deve pressionar Enter após o input (default: true)",
                        },
                    },
                    "required": ["session_id", "input"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shell_kill",
                "description": "Termina um processo shell em execução.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "ID da sessão shell a terminar",
                        }
                    },
                    "required": ["session_id"],
                },
            },
        },

        # ══════════════════════════════════════════════════════════
        # ARQUIVO — leitura e edição precisa
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "file_read",
                "description": (
                    "Lê o conteúdo de um arquivo com números de linha. "
                    "Suporta leitura parcial por intervalo de linhas. "
                    "Use antes de editar para entender o contexto exato."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo",
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "Linha inicial (0-based, opcional)",
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Linha final (não inclusiva, opcional)",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "file_write",
                "description": (
                    "Cria ou sobrescreve um arquivo com o conteúdo informado. "
                    "Para modificações cirúrgicas em arquivos existentes, prefira file_edit. "
                    "Use file_write para criar arquivos novos ou reescrever completamente."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo",
                        },
                        "content": {
                            "type": "string",
                            "description": "Conteúdo a escrever",
                        },
                        "append": {
                            "type": "boolean",
                            "description": "Se true, adiciona ao final do arquivo (default: false)",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "file_edit",
                "description": (
                    "Faz uma substituição cirúrgica em um arquivo existente — substitui "
                    "exatamente uma ocorrência de old_str por new_str. "
                    "CRÍTICO: old_str deve ser único no arquivo. Inclua pelo menos 3-5 linhas "
                    "de contexto antes e depois do ponto de mudança para garantir unicidade. "
                    "Preserve a indentação exata. Use file_read antes para ver o conteúdo real. "
                    "Para múltiplas substituições iguais, informe expected_replacements."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo",
                        },
                        "old_str": {
                            "type": "string",
                            "description": (
                                "Texto exato a substituir (com indentação e quebras de linha). "
                                "Deve ser único no arquivo ou usar expected_replacements."
                            ),
                        },
                        "new_str": {
                            "type": "string",
                            "description": "Novo texto (substitui old_str)",
                        },
                        "expected_replacements": {
                            "type": "integer",
                            "description": "Número de ocorrências a substituir (default: 1)",
                        },
                    },
                    "required": ["path", "old_str", "new_str"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "file_list",
                "description": "Lista arquivos e diretórios em um caminho.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Caminho do diretório",
                        },
                        "recursive": {
                            "type": "boolean",
                            "description": "Listar recursivamente (default: false)",
                        },
                        "show_hidden": {
                            "type": "boolean",
                            "description": "Incluir arquivos ocultos (default: false)",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "file_find",
                "description": "Busca arquivos por padrão de nome (glob) em um diretório.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Diretório base",
                        },
                        "glob": {
                            "type": "string",
                            "description": "Padrão glob (ex: '*.py', '**/*.json', 'src/**/*.ts')",
                        },
                    },
                    "required": ["path", "glob"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "file_grep",
                "description": (
                    "Busca conteúdo em múltiplos arquivos por regex ou string. "
                    "Retorna linhas correspondentes com número de linha e arquivo. "
                    "Use para encontrar onde uma função é definida, onde uma variável é usada, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Diretório base para busca",
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Padrão de busca (regex ou string literal)",
                        },
                        "include": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filtros de extensão (ex: ['*.py', '*.js'])",
                        },
                        "case_insensitive": {
                            "type": "boolean",
                            "description": "Busca sem diferenciar maiúsculas (default: true)",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Máximo de resultados (default: 50)",
                        },
                    },
                    "required": ["path", "pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "file_zip",
                "description": (
                    "Cria um arquivo .zip de um arquivo ou diretório inteiro. "
                    "Use para empacotar projetos para entrega ao usuário. "
                    "Após criar, use send_file_whatsapp para enviar o .zip."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_path": {
                            "type": "string",
                            "description": "Caminho do arquivo ou diretório a zipar",
                        },
                        "output_path": {
                            "type": "string",
                            "description": (
                                "Caminho do .zip a criar (opcional). "
                                "Se omitido, cria {source_path}.zip"
                            ),
                        },
                    },
                    "required": ["source_path"],
                },
            },
        },

        # ══════════════════════════════════════════════════════════
        # CONTEXTO — workspace e memória
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "workspace_info",
                "description": (
                    "Retorna informações do workspace: estrutura de diretórios, "
                    "git status e branch. Use no início de uma tarefa para entender "
                    "o estado atual do projeto antes de trabalhar."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_read",
                "description": (
                    "Lê a memória persistente desta sessão (equivalente ao CLAUDE.md). "
                    "Contém convenções do projeto, stack tecnológica, comandos úteis e "
                    "contexto de negócio que persiste entre tarefas."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_write",
                "description": (
                    "Atualiza a memória persistente desta sessão. "
                    "Use para registrar: stack do projeto, comandos para rodar, "
                    "convenções de código, estrutura de pastas importantes, etc. "
                    "O conteúdo SUBSTITUI a memória anterior — inclua tudo que deve persistir. "
                    "Formato sugerido: seções em Markdown (## Stack, ## Comandos, ## Convenções)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Novo conteúdo completo da memória em Markdown",
                        }
                    },
                    "required": ["content"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "change_workspace",
                "description": (
                    "Muda o diretório de trabalho atual (workspace). "
                    "Use quando o usuário pedir para trabalhar em um projeto específico "
                    "ou em uma pasta diferente no computador."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "new_path": {
                            "type": "string",
                            "description": "Caminho absoluto do novo workspace",
                        }
                    },
                    "required": ["new_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "project_init",
                "description": (
                    "Cria um novo projeto no workspace com estrutura organizada. "
                    "Use SEMPRE ao iniciar um projeto novo — nunca crie arquivos soltos na raiz do workspace. "
                    "Cria o subdiretório, muda o workspace automaticamente e atualiza a memória. "
                    "Templates disponíveis: empty (pasta vazia com README), python (src/, tests/, requirements.txt), "
                    "node (src/, package.json), web (index.html, css/, js/)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "Nome do projeto em kebab-case (ex: 'meu-site', 'api-vendas')",
                        },
                        "description": {
                            "type": "string",
                            "description": "Descrição curta do projeto (1-2 frases)",
                        },
                        "template": {
                            "type": "string",
                            "enum": ["empty", "python", "node", "web"],
                            "description": "Template de estrutura inicial (default: empty)",
                        },
                    },
                    "required": ["project_name"],
                },
            },
        },
        # ══════════════════════════════════════════════════════════
        # TAREFAS — controle e status
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "task_list",
                "description": (
                    "Lista todas as tarefas desta sessão de coding com seus status. "
                    "Use para ver o histórico de trabalho e tarefas em andamento."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status_filter": {
                            "type": "string",
                            "enum": ["all", "running", "completed", "failed"],
                            "description": "Filtrar por status (default: 'all')",
                        }
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_status",
                "description": (
                    "Retorna detalhes de uma tarefa específica: status, artefatos gerados, "
                    "processos shell ativos e última mensagem do assistente."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "integer",
                            "description": "ID da tarefa",
                        }
                    },
                    "required": ["task_id"],
                },
            },
        },

        # ══════════════════════════════════════════════════════════
        # ENTREGA — envio ao usuário via WhatsApp
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "send_file_whatsapp",
                "description": (
                    "Envia um arquivo do workspace para o usuário via WhatsApp. "
                    "Use SEMPRE que gerar um arquivo que o usuário precisa receber "
                    "(ZIP, PDF, imagem, planilha, script, etc.)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo no workspace",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Nome de exibição para o usuário (ex: 'meu_site.zip')",
                        },
                        "caption": {
                            "type": "string",
                            "description": "Legenda ou descrição do arquivo",
                        },
                    },
                    "required": ["file_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_screenshot_whatsapp",
                "description": (
                    "Tira screenshot do browser e envia ao usuário via WhatsApp. "
                    "Use para mostrar resultados visuais (página renderizada, preview, etc.)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "caption": {
                            "type": "string",
                            "description": "Legenda opcional da imagem",
                        },
                        "full_page": {
                            "type": "boolean",
                            "description": "Se true, captura a página inteira com scroll",
                        },
                    },
                    "required": [],
                },
            },
        },

        # ══════════════════════════════════════════════════════════
        # WEB — busca e fetch sem browser (mais leve que browser_*)
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "web_fetch",
                "description": (
                    "Faz requisição HTTP para uma URL e retorna o conteúdo como texto. "
                    "Converte HTML em texto legível. Útil para ler documentação, APIs REST, "
                    "páginas simples. Para páginas que exigem JavaScript, use browser_navigate. "
                    "Retorna: status_code, content (texto da página), url_final."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL para buscar"},
                        "method": {"type": "string", "enum": ["GET", "POST"], "description": "Método HTTP (default: GET)"},
                        "headers": {"type": "object", "description": "Headers adicionais (ex: Authorization)"},
                        "body": {"type": "string", "description": "Body para POST requests"},
                        "max_chars": {"type": "integer", "description": "Máximo de caracteres no retorno (default: 8000)"},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Busca informações na web e retorna lista de resultados com título, URL e trecho. "
                    "Use para pesquisar documentação, encontrar soluções de erros, buscar pacotes, etc. "
                    "Após receber os resultados, use web_fetch para acessar uma URL específica."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Termos de busca"},
                        "num_results": {"type": "integer", "description": "Número de resultados (default: 8, max: 20)"},
                    },
                    "required": ["query"],
                },
            },
        },

        # ══════════════════════════════════════════════════════════
        # SKILLS — instruções especializadas sob demanda
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "invocar_skill",
                "description": (
                    "Carrega instruções especializadas de uma skill disponível. "
                    "Skills contêm conhecimento profundo sobre como executar tipos específicos de tarefas. "
                    "SEMPRE invoque a skill relevante ANTES de começar a trabalhar — "
                    "as instruções melhoram significativamente a qualidade do resultado. "
                    "Após receber as instruções, SIGA-AS à risca."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_nome": {
                            "type": "string",
                            "description": "Nome exato da skill (conforme listado no system prompt)",
                        },
                        "argumentos": {
                            "type": "object",
                            "description": "Parâmetros opcionais aceitos pela skill",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["skill_nome"],
                },
            },
        },

        # ══════════════════════════════════════════════════════════
        # COGNIÇÃO — raciocínio e gerenciamento de contexto
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "think",
                "description": (
                    "Ferramenta de raciocínio estruturado — use para pensar em voz alta antes de agir. "
                    "Analise o problema, considere abordagens alternativas, identifique riscos. "
                    "O conteúdo não é executado — é apenas para organizar o pensamento antes de chamar outra tool. "
                    "Equivalente ao 'thinking mode' do Claude Code."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "thought": {
                            "type": "string",
                            "description": "Seu raciocínio detalhado sobre o problema e próximos passos",
                        }
                    },
                    "required": ["thought"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "context_compact",
                "description": (
                    "Comprime o histórico da conversa quando está muito longo. "
                    "Sumariza mensagens antigas e mantém apenas as mais recentes. "
                    "Use quando perceber que o contexto está crescendo demais (muitas iterações). "
                    "Equivalente ao /clear do Claude Code com preservação de contexto."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keep_last": {
                            "type": "integer",
                            "description": "Quantas mensagens recentes manter intactas (default: 15)",
                        }
                    },
                    "required": [],
                },
            },
        },

        # ══════════════════════════════════════════════════════════
        # SUB-AGENTES — delegar trabalho focado
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "task_create",
                "description": (
                    "Cria e inicia uma sub-tarefa em background. "
                    "Use para paralelizar trabalho: enquanto a tarefa principal continua, "
                    "a sub-tarefa executa de forma independente. "
                    "Retorna um task_id para verificar o progresso com task_status. "
                    "Equivalente ao TaskCreateTool do Claude Code."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Título da sub-tarefa"},
                        "objective": {"type": "string", "description": "Descrição detalhada do que a sub-tarefa deve fazer"},
                    },
                    "required": ["title", "objective"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "agent_run",
                "description": (
                    "Delega um objetivo específico para um sub-agente focado. "
                    "O sub-agente tem acesso a todas as ferramentas shell e arquivo. "
                    "Ideal para tarefas bem definidas que precisam de raciocínio independente: "
                    "ex: 'escreva um módulo de autenticação', 'refatore este arquivo', etc. "
                    "Bloqueante: aguarda o sub-agente terminar antes de continuar. "
                    "Equivalente ao AgentTool do Claude Code."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "Objetivo claro e específico para o sub-agente",
                        },
                        "context": {
                            "type": "string",
                            "description": "Contexto adicional (arquivos relevantes, restrições, etc.)",
                        },
                        "max_iterations": {
                            "type": "integer",
                            "description": "Máximo de iterações do sub-agente (default: 15)",
                        },
                    },
                    "required": ["goal"],
                },
            },
        },

        # ══════════════════════════════════════════════════════════
        # FLUXI META — registrar sistemas criados no próprio Fluxi
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "fluxi_listar_recursos",
                "description": (
                    "Lista recursos existentes no Fluxi: ferramentas, agentes ou skills. "
                    "Use ANTES de criar algo para verificar se já existe e obter IDs necessários. "
                    "Especialmente útil para obter o sessao_id de um agente existente."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tipo": {
                            "type": "string",
                            "enum": ["ferramentas", "agentes", "skills"],
                            "description": "Tipo de recurso a listar",
                        },
                        "sessao_id": {
                            "type": "integer",
                            "description": "Filtrar agentes por sessao_id (opcional, só para tipo=agentes)",
                        },
                    },
                    "required": ["tipo"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fluxi_criar_ferramenta",
                "description": (
                    "Cria uma nova ferramenta CODE no Fluxi. "
                    "Use para registrar scripts Python que o agente pode chamar como tools. "
                    "O codigo_python recebe 'argumentos' (dict) e deve definir 'resultado'. "
                    "Retorna o ID da ferramenta criada."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "nome": {
                            "type": "string",
                            "description": "Nome único da ferramenta (snake_case, sem espaços)",
                        },
                        "descricao": {
                            "type": "string",
                            "description": "Descrição clara para o LLM entender quando usar esta ferramenta",
                        },
                        "params_json": {
                            "type": "string",
                            "description": (
                                'Schema JSON dos parâmetros. Ex: {"item": {"type": "string", "required": true, "description": "Nome do item"}}'
                            ),
                        },
                        "codigo_python": {
                            "type": "string",
                            "description": (
                                "Código Python que implementa a ferramenta. "
                                "Recebe o dict 'argumentos' e DEVE definir a variável 'resultado'. "
                                "Use \\n para quebras de linha."
                            ),
                        },
                        "output": {
                            "type": "string",
                            "enum": ["LLM", "USER", "BOTH"],
                            "description": "Destino da saída: LLM (padrão), USER (envia ao WhatsApp), BOTH",
                        },
                    },
                    "required": ["nome", "descricao", "params_json", "codigo_python"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fluxi_atualizar_ferramenta",
                "description": (
                    "Atualiza o código Python ou descrição de uma ferramenta existente no Fluxi. "
                    "Use para corrigir bugs ou melhorar ferramentas já criadas."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ferramenta_id": {
                            "type": "integer",
                            "description": "ID da ferramenta a atualizar",
                        },
                        "codigo_python": {
                            "type": "string",
                            "description": "Novo código Python (opcional)",
                        },
                        "descricao": {
                            "type": "string",
                            "description": "Nova descrição (opcional)",
                        },
                        "params_json": {
                            "type": "string",
                            "description": "Novo schema de parâmetros em JSON (opcional)",
                        },
                    },
                    "required": ["ferramenta_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fluxi_criar_agente",
                "description": (
                    "Cria um novo agente personalizado no Fluxi e opcionalmente associa ferramentas. "
                    "Use após criar as ferramentas para montar o agente completo. "
                    "Retorna o ID e código do agente criado."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sessao_id": {
                            "type": "integer",
                            "description": "ID da sessão WhatsApp (use fluxi_listar_recursos para obter)",
                        },
                        "codigo": {
                            "type": "string",
                            "description": "Prefixo curto do agente (ex: 'fin', 'task', 'ven') — usuário digita #codigo para ativar",
                        },
                        "nome": {
                            "type": "string",
                            "description": "Nome exibido do agente (ex: 'Financeiro', 'Tarefas')",
                        },
                        "papel": {
                            "type": "string",
                            "description": "Quem o agente é: 'Você é um assistente financeiro...'",
                        },
                        "objetivo": {
                            "type": "string",
                            "description": "O que o agente deve alcançar",
                        },
                        "politicas": {
                            "type": "string",
                            "description": "Como o agente deve se comportar",
                        },
                        "tarefa": {
                            "type": "string",
                            "description": "O que o agente faz tecnicamente",
                        },
                        "restricoes": {
                            "type": "string",
                            "description": "O que o agente NÃO deve fazer",
                        },
                        "ferramentas_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Lista de IDs de ferramentas a associar ao agente",
                        },
                    },
                    "required": ["sessao_id", "codigo", "nome", "papel", "objetivo", "politicas", "tarefa", "restricoes"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fluxi_conectar_mcp",
                "description": (
                    "Conecta um servidor MCP a um agente no Fluxi. "
                    "Suporta presets prontos, URL (SSE/HTTP), STDIO local e JSON one-click. "
                    "Use fluxi_listar_recursos para obter o agente_id antes de conectar."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agente_id": {
                            "type": "integer",
                            "description": "ID do agente ao qual conectar o servidor MCP",
                        },
                        "modo": {
                            "type": "string",
                            "enum": ["preset", "url", "stdio", "one_click"],
                            "description": "Como conectar: via preset pronto, URL, processo local ou JSON one-click",
                        },
                        "nome": {
                            "type": "string",
                            "description": "Nome do servidor MCP",
                        },
                        "preset_key": {
                            "type": "string",
                            "description": "Chave do preset (somente modo=preset). Use fluxi_listar_recursos com tipo='mcp_presets' para ver.",
                        },
                        "preset_inputs": {
                            "type": "object",
                            "description": "Dict com os inputs do preset (tokens, URLs, etc.)",
                        },
                        "url": {
                            "type": "string",
                            "description": "URL do servidor MCP (modo=url). Ex: http://localhost:8080/mcp",
                        },
                        "transport_type": {
                            "type": "string",
                            "enum": ["sse", "streamable-http"],
                            "description": "Tipo de transporte para modo=url (padrão: streamable-http)",
                        },
                        "command": {
                            "type": "string",
                            "description": "Comando para iniciar o servidor (modo=stdio). Ex: python, npx, uv",
                        },
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Argumentos do comando (modo=stdio)",
                        },
                        "env_vars": {
                            "type": "object",
                            "description": "Variáveis de ambiente para o processo (modo=stdio)",
                        },
                        "headers": {
                            "type": "object",
                            "description": "Headers HTTP (modo=url)",
                        },
                        "json_config": {
                            "type": "string",
                            "description": "JSON de configuração no formato mcpServers (modo=one_click)",
                        },
                    },
                    "required": ["agente_id", "modo"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fluxi_criar_skill",
                "description": (
                    "Cria uma nova skill no Fluxi com instruções especializadas. "
                    "Skills são carregadas sob demanda pelo agente, sem ocupar contexto o tempo todo. "
                    "Use para encapsular conhecimento específico de domínio."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "nome": {
                            "type": "string",
                            "description": "Nome único da skill (snake_case)",
                        },
                        "descricao": {
                            "type": "string",
                            "description": "Resumo de uma linha do que a skill ensina (max 250 chars)",
                        },
                        "instrucao_completa": {
                            "type": "string",
                            "description": "Instruções detalhadas em markdown. Carregadas quando o agente invoca a skill.",
                        },
                        "categoria": {
                            "type": "string",
                            "description": "Categoria da skill (ex: financeiro, suporte, vendas, meta)",
                        },
                        "icone": {
                            "type": "string",
                            "description": "Emoji representativo da skill",
                        },
                        "agente_id": {
                            "type": "integer",
                            "description": "Se fornecido, associa a skill ao agente automaticamente",
                        },
                    },
                    "required": ["nome", "descricao", "instrucao_completa"],
                },
            },
        },

        # ══════════════════════════════════════════════════════════
        # BROWSER — para tarefas que precisam de navegação web
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "browser_navigate",
                "description": "Navega o browser para uma URL. Use para visualizar resultado, pesquisar documentação, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL para navegar"},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_get_page",
                "description": (
                    "Retorna o conteúdo da página atual como texto legível (Markdown). "
                    "Use para extrair informações de sites, documentações, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_screenshot",
                "description": "Tira screenshot da página atual para visualização.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "full_page": {"type": "boolean", "description": "Capturar página inteira"},
                    },
                    "required": [],
                },
            },
        },
    ]

    tools_filtradas = []
    for t in todas_tools:
        nome = t["function"]["name"]
        
        # Filtrar skill fluxi_meta
        if nome.startswith("fluxi_") and "fluxi_meta" not in active_skills:
            continue
            
        # Filtrar skill browser
        if nome.startswith("browser_") and "browser" not in active_skills:
            continue
            
        tools_filtradas.append(t)
        
    return tools_filtradas


def obter_nomes_coding_tools() -> set:
    """Retorna o set de nomes de todas as tools do coding agent."""
    return {t["function"]["name"] for t in obter_coding_tools(active_skills=["fluxi_meta", "browser"])}
