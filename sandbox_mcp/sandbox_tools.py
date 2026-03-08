"""
Definição das tools OpenAI (function calling) do AIO Sandbox via SDK.
Cada tool mapeia para uma chamada direta no AsyncSandbox.
"""
from __future__ import annotations

from typing import Any, Dict, List


def obter_sandbox_tools() -> List[Dict[str, Any]]:
    """Retorna a lista completa de tools do sandbox no formato OpenAI function calling."""
    return [
        # ══════════════════════════════════════════════════════════
        # SHELL
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "sandbox_shell_exec",
                "description": (
                    "Executa um comando shell (bash) no sandbox. "
                    "Use para rodar comandos Linux, scripts Python, pip install, "
                    "curl, wget, git, e qualquer operação de terminal. "
                    "Retorna output, exit_code e status."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Comando shell a executar (ex: 'ls -la', 'pip install pandas', 'python script.py')"
                        },
                        "exec_dir": {
                            "type": "string",
                            "description": "Diretório de trabalho (caminho absoluto). Default: /home/gem"
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Timeout em segundos para o comando (default: sem limite)"
                        }
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_shell_view",
                "description": "Visualiza o output atual de uma sessão shell em execução.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID da sessão shell"
                        }
                    },
                    "required": ["id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_shell_write",
                "description": "Escreve input em um processo shell em execução (interativo).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID da sessão shell"
                        },
                        "input": {
                            "type": "string",
                            "description": "Texto a enviar para o processo"
                        },
                        "press_enter": {
                            "type": "boolean",
                            "description": "Se deve pressionar Enter após o input (default: true)"
                        }
                    },
                    "required": ["id", "input"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_shell_kill",
                "description": "Termina um processo em execução em uma sessão shell.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID da sessão shell a terminar"
                        }
                    },
                    "required": ["id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_shell_list_sessions",
                "description": "Lista todas as sessões shell ativas no sandbox.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_shell_wait",
                "description": "Aguarda um processo shell terminar e retorna o output final.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID da sessão shell"
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Timeout em segundos para aguardar"
                        }
                    },
                    "required": ["id"]
                }
            }
        },
        # ══════════════════════════════════════════════════════════
        # FILE SYSTEM
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "sandbox_file_read",
                "description": (
                    "Lê o conteúdo de um arquivo no sandbox. "
                    "Suporta leitura parcial por linhas."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo (ex: /home/gem/script.py)"
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "Linha inicial (0-based, opcional)"
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Linha final (não inclusiva, opcional)"
                        }
                    },
                    "required": ["file"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_file_write",
                "description": (
                    "Escreve conteúdo em um arquivo no sandbox. "
                    "Cria o arquivo se não existir. Suporta modo append."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo"
                        },
                        "content": {
                            "type": "string",
                            "description": "Conteúdo a escrever"
                        },
                        "append": {
                            "type": "boolean",
                            "description": "Se true, adiciona ao final do arquivo ao invés de sobrescrever"
                        },
                        "encoding": {
                            "type": "string",
                            "description": "Encoding: 'utf-8' (texto) ou 'base64' (binário)"
                        }
                    },
                    "required": ["file", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_file_list",
                "description": "Lista arquivos e diretórios em um caminho do sandbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Caminho do diretório (ex: /home/gem)"
                        },
                        "recursive": {
                            "type": "boolean",
                            "description": "Listar recursivamente (default: false)"
                        },
                        "show_hidden": {
                            "type": "boolean",
                            "description": "Mostrar arquivos ocultos (default: false)"
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_file_find",
                "description": "Busca arquivos por padrão de nome (glob) em um diretório.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Diretório base para busca"
                        },
                        "glob": {
                            "type": "string",
                            "description": "Padrão glob (ex: '*.py', '**/*.json')"
                        }
                    },
                    "required": ["path", "glob"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_file_grep",
                "description": (
                    "Busca conteúdo em múltiplos arquivos (grep). "
                    "Suporta regex e busca recursiva."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Diretório base para busca"
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Padrão de busca (regex ou string)"
                        },
                        "include": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filtros de arquivo (ex: ['*.py', '*.js'])"
                        },
                        "case_insensitive": {
                            "type": "boolean",
                            "description": "Busca case-insensitive (default: true)"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Máximo de resultados (default: 50)"
                        }
                    },
                    "required": ["path", "pattern"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_file_replace",
                "description": "Substitui uma string por outra em um arquivo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo"
                        },
                        "old_str": {
                            "type": "string",
                            "description": "String original a substituir"
                        },
                        "new_str": {
                            "type": "string",
                            "description": "Nova string para substituição"
                        }
                    },
                    "required": ["file", "old_str", "new_str"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_file_search",
                "description": (
                    "Busca conteúdo dentro de um único arquivo usando regex. "
                    "Retorna linhas correspondentes com número da linha."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo"
                        },
                        "regex": {
                            "type": "string",
                            "description": "Padrão regex para buscar"
                        },
                        "sudo": {
                            "type": "boolean",
                            "description": "Usar sudo para ler arquivo protegido (default: false)"
                        }
                    },
                    "required": ["file", "regex"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_file_download",
                "description": (
                    "Baixa um arquivo do sandbox (retorna base64). "
                    "Use para obter arquivos gerados no sandbox."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo a baixar"
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_file_editor",
                "description": (
                    "Editor de arquivos avançado (estilo Anthropic). "
                    "Suporta: view, create, str_replace, insert, undo_edit. "
                    "Também lê PDFs, Excel, PPTX."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
                            "description": "Comando a executar"
                        },
                        "path": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo"
                        },
                        "file_text": {
                            "type": "string",
                            "description": "Conteúdo do arquivo (para 'create')"
                        },
                        "old_str": {
                            "type": "string",
                            "description": "String a substituir (para 'str_replace')"
                        },
                        "new_str": {
                            "type": "string",
                            "description": "Nova string (para 'str_replace' e 'insert')"
                        },
                        "insert_line": {
                            "type": "integer",
                            "description": "Linha após a qual inserir (para 'insert')"
                        },
                        "view_range": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Range de linhas para view [inicio, fim] (1-indexed)"
                        }
                    },
                    "required": ["command", "path"]
                }
            }
        },
        # ══════════════════════════════════════════════════════════
        # BROWSER - GUI/VNC (ações visuais por pixel)
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_execute_action",
                "description": (
                    "Executa uma ação GUI/VNC no desktop do sandbox (nível pixel). "
                    "Use para interações visuais quando seletores CSS não funcionam. "
                    "Tipos: move_to, click, double_click, right_click, typing, press, "
                    "hotkey, scroll, drag_to, mouse_down, mouse_up, key_down, key_up."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action_type": {
                            "type": "string",
                            "enum": ["move_to", "click", "double_click", "right_click",
                                     "typing", "press", "hotkey", "scroll", "drag_to",
                                     "mouse_down", "mouse_up", "key_down", "key_up"],
                            "description": "Tipo da ação GUI a executar"
                        },
                        "x": {"type": "number", "description": "Coordenada X (pixels)"},
                        "y": {"type": "number", "description": "Coordenada Y (pixels)"},
                        "text": {"type": "string", "description": "Texto para typing"},
                        "key": {"type": "string", "description": "Tecla para press/key_down/key_up"},
                        "keys": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Teclas para hotkey (ex: ['ctrl', 'c'])"
                        },
                        "button": {"type": "string", "description": "Botão do mouse: 'left', 'right', 'middle'"},
                        "num_clicks": {"type": "integer", "description": "Número de cliques"},
                        "dx": {"type": "number", "description": "Delta X para scroll"},
                        "dy": {"type": "number", "description": "Delta Y para scroll"},
                        "use_clipboard": {"type": "boolean", "description": "Usar clipboard para typing (mais rápido)"}
                    },
                    "required": ["action_type"]
                }
            }
        },
        # ══════════════════════════════════════════════════════════
        # BROWSER - Navegação e interação (Playwright/seletores CSS)
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_navigate",
                "description": (
                    "Navega o browser para uma URL. "
                    "Use para acessar sites, APIs, fazer pesquisas na web."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL para navegar (ex: https://google.com)"
                        },
                        "wait_until": {
                            "type": "string",
                            "description": "Quando considerar carregado: 'load', 'domcontentloaded', 'networkidle'"
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Timeout em segundos"
                        }
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_screenshot",
                "description": (
                    "Tira screenshot da tela inteira do sandbox (display/VNC). "
                    "Útil para ver o estado visual completo do desktop."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_page_screenshot",
                "description": (
                    "Tira screenshot da página web atual no browser (via Playwright). "
                    "Mais preciso que screenshot de tela. Suporta full_page."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "full_page": {
                            "type": "boolean",
                            "description": "Se true, captura a página inteira (scroll completo)"
                        }
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_click",
                "description": "Clica em um elemento da página por seletor CSS ou coordenadas.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "Seletor CSS do elemento (ex: '#btn-submit', '.link-class')"
                        },
                        "index": {
                            "type": "integer",
                            "description": "Índice se houver múltiplos elementos com o mesmo seletor"
                        },
                        "x": {
                            "type": "number",
                            "description": "Coordenada X para clicar"
                        },
                        "y": {
                            "type": "number",
                            "description": "Coordenada Y para clicar"
                        }
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_fill",
                "description": "Preenche um campo de input com texto (limpa o campo antes).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Texto a preencher"
                        },
                        "selector": {
                            "type": "string",
                            "description": "Seletor CSS do input"
                        },
                        "index": {
                            "type": "integer",
                            "description": "Índice se houver múltiplos inputs"
                        }
                    },
                    "required": ["text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_type",
                "description": "Digita texto tecla por tecla (simula digitação humana).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Texto a digitar"
                        },
                        "delay": {
                            "type": "number",
                            "description": "Atraso entre teclas em ms"
                        }
                    },
                    "required": ["text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_press_key",
                "description": "Pressiona uma tecla específica (Enter, Tab, Escape, etc.).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Nome da tecla (ex: 'Enter', 'Tab', 'Escape', 'ArrowDown')"
                        }
                    },
                    "required": ["key"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_hot_key",
                "description": "Pressiona uma combinação de teclas (atalho).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Lista de teclas (ex: ['Control', 'a'] para Ctrl+A)"
                        }
                    },
                    "required": ["keys"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_scroll",
                "description": "Rola a página em uma direção.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down", "left", "right"],
                            "description": "Direção do scroll"
                        },
                        "amount": {
                            "type": "integer",
                            "description": "Quantidade de scroll (default: 3)"
                        }
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_scroll_to_element",
                "description": "Rola até um elemento específico ficar visível.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "Seletor CSS do elemento"
                        }
                    },
                    "required": ["selector"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_hover",
                "description": "Passa o mouse sobre um elemento (hover).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "Seletor CSS do elemento"
                        },
                        "x": {"type": "number", "description": "Coordenada X"},
                        "y": {"type": "number", "description": "Coordenada Y"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_select_option",
                "description": "Seleciona uma opção em um dropdown/select.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "Seletor CSS do select"
                        },
                        "value": {"type": "string", "description": "Valor da opção"},
                        "label": {"type": "string", "description": "Texto da opção"},
                        "index": {"type": "integer", "description": "Índice da opção"}
                    },
                    "required": ["selector"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_fill_form",
                "description": "Preenche múltiplos campos de formulário de uma vez.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Lista de {selector, text} para preencher"
                        }
                    },
                    "required": ["items"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_check",
                "description": "Marca um checkbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "Seletor CSS do checkbox"}
                    },
                    "required": ["selector"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_uncheck",
                "description": "Desmarca um checkbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "Seletor CSS do checkbox"}
                    },
                    "required": ["selector"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_upload_file",
                "description": "Faz upload de arquivos em um input file da página.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "Seletor CSS do input file"},
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Caminhos dos arquivos no sandbox"
                        }
                    },
                    "required": ["selector", "files"]
                }
            }
        },
        # ── Browser - Extração de conteúdo ────────────────────────
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_get_text",
                "description": "Extrai todo o texto visível da página web atual.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_get_html",
                "description": "Obtém o HTML da página atual.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "outer": {
                            "type": "boolean",
                            "description": "Se true, retorna outerHTML"
                        }
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_get_markdown",
                "description": (
                    "Converte o conteúdo da página para Markdown usando Readability+Turndown. "
                    "Ideal para extrair artigos, documentação, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_get_elements",
                "description": "Obtém todos os elementos interativos da página (botões, links, inputs, etc.).",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_get_info",
                "description": "Obtém informações do browser (CDP URL, viewport, etc.).",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        # ── Browser - Navegação ──────────────────────────────────
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_back",
                "description": "Volta à página anterior no histórico do browser.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_forward",
                "description": "Avança para a próxima página no histórico do browser.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_reload",
                "description": "Recarrega a página atual.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        # ── Browser - Abas ───────────────────────────────────────
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_tabs_list",
                "description": "Lista todas as abas abertas no browser.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_tabs_new",
                "description": "Abre uma nova aba no browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL para abrir na nova aba"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_tabs_close",
                "description": "Fecha uma aba do browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "Índice da aba (default: 0)"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_tabs_switch",
                "description": "Alterna para uma aba específica do browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "Índice da aba"}
                    },
                    "required": ["index"]
                }
            }
        },
        # ── Browser - Cookies ────────────────────────────────────
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_cookies_get",
                "description": "Obtém cookies do browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL para filtrar cookies (opcional)"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_cookies_set",
                "description": "Define cookies no browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cookies": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Lista de cookies {name, value, domain, path, ...}"
                        }
                    },
                    "required": ["cookies"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_cookies_clear",
                "description": "Limpa todos os cookies do browser.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        # ── Browser - Record ─────────────────────────────────────
        {
            "type": "function",
            "function": {
                "name": "sandbox_browser_record",
                "description": (
                    "Grava screencast da página (vídeo). "
                    "Actions: 'once' (captura única), 'start', 'pause', 'resume', 'stop', 'status'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["once", "start", "pause", "resume", "stop", "status"],
                            "description": "Ação da gravação"
                        },
                        "save_path": {"type": "string", "description": "Caminho para salvar o vídeo"},
                        "duration": {"type": "number", "description": "Duração em segundos"},
                        "fps": {"type": "integer", "description": "Frames por segundo"},
                        "quality": {"type": "integer", "description": "Qualidade (0-100)"}
                    },
                    "required": []
                }
            }
        },
        # ══════════════════════════════════════════════════════════
        # JUPYTER (Python)
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "sandbox_jupyter_execute",
                "description": (
                    "Executa código Python no Jupyter com persistência de sessão. "
                    "Variáveis são mantidas entre execuções. "
                    "Ideal para data science, gráficos, análises complexas."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Código Python a executar"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout em segundos (default: 120)"
                        },
                        "session_id": {
                            "type": "string",
                            "description": "ID da sessão para manter estado entre execuções"
                        },
                        "kernel_name": {
                            "type": "string",
                            "description": "Nome do kernel: 'python3', 'python3.10', etc."
                        }
                    },
                    "required": ["code"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_jupyter_info",
                "description": "Obtém informações sobre kernels Jupyter disponíveis (versões, limites, etc.).",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_jupyter_list_sessions",
                "description": "Lista todas as sessões Jupyter ativas.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_jupyter_cleanup_session",
                "description": "Remove/limpa uma sessão Jupyter específica para liberar recursos.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "ID da sessão Jupyter a remover"
                        }
                    },
                    "required": ["session_id"]
                }
            }
        },
        # ══════════════════════════════════════════════════════════
        # NODE.JS
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "sandbox_nodejs_execute",
                "description": (
                    "Executa código JavaScript/Node.js no sandbox. "
                    "Suporta arquivos auxiliares e stdin. "
                    "Útil para manipular JSON, APIs, scraping com JS, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Código JavaScript a executar"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout em segundos (default: 60)"
                        },
                        "session_id": {
                            "type": "string",
                            "description": "ID da sessão para persistência"
                        },
                        "files": {
                            "type": "object",
                            "description": "Arquivos auxiliares: {'filename.json': 'conteúdo', ...}"
                        },
                        "stdin": {
                            "type": "string",
                            "description": "Input stdin para o processo Node.js"
                        }
                    },
                    "required": ["code"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_nodejs_info",
                "description": "Obtém informações do runtime Node.js (versão, npm, diretório).",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        # ══════════════════════════════════════════════════════════
        # CODE (genérico)
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "sandbox_code_execute",
                "description": "Executa código em uma linguagem específica.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Código a executar"},
                        "language": {
                            "type": "string",
                            "description": "Linguagem: 'python', 'javascript', etc."
                        },
                        "timeout": {"type": "integer", "description": "Timeout em segundos"}
                    },
                    "required": ["code"]
                }
            }
        },
        # ══════════════════════════════════════════════════════════
        # SANDBOX
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "sandbox_get_context",
                "description": "Obtém informações do ambiente sandbox (home dir, sistema, ferramentas disponíveis).",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_python_packages",
                "description": "Lista todos os pacotes Python instalados no sandbox (nome e versão).",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sandbox_nodejs_packages",
                "description": "Lista todos os pacotes Node.js/npm instalados no sandbox.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        # ══════════════════════════════════════════════════════════
        # WHATSAPP (tools virtuais executadas pelo Fluxi)
        # ══════════════════════════════════════════════════════════
        {
            "type": "function",
            "function": {
                "name": "enviar_arquivo_whatsapp",
                "description": (
                    "Envia um arquivo do sandbox diretamente para o usuário via WhatsApp. "
                    "Use SEMPRE que criar, baixar ou gerar um arquivo que o usuário precisa receber. "
                    "Suporta documentos (PDF, DOCX, XLSX, CSV, TXT, ZIP), imagens (JPG, PNG, GIF, WEBP), "
                    "áudios (MP3, OGG) e vídeos (MP4). O arquivo deve existir no sandbox."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Caminho completo do arquivo no sandbox (ex: /home/gem/relatorio.pdf)"
                        },
                        "filename": {
                            "type": "string",
                            "description": "Nome do arquivo para exibição (ex: relatorio.pdf)"
                        },
                        "caption": {
                            "type": "string",
                            "description": "Legenda ou descrição opcional do arquivo"
                        }
                    },
                    "required": ["file_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "enviar_screenshot_whatsapp",
                "description": (
                    "Tira um screenshot do sandbox e envia diretamente ao usuário via WhatsApp. "
                    "Use para mostrar resultados visuais, páginas web, gráficos renderizados, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tipo": {
                            "type": "string",
                            "enum": ["tela", "pagina"],
                            "description": "Tipo: 'tela' (display/VNC inteiro) ou 'pagina' (apenas a página do browser)"
                        },
                        "full_page": {
                            "type": "boolean",
                            "description": "Se true e tipo='pagina', captura a página inteira com scroll"
                        },
                        "caption": {
                            "type": "string",
                            "description": "Legenda opcional para a imagem"
                        }
                    },
                    "required": []
                }
            }
        },
    ]


def obter_nomes_tools_sandbox() -> set:
    """Retorna o set de nomes de todas as tools do sandbox."""
    return {t["function"]["name"] for t in obter_sandbox_tools()}
