"""
CodingMemory — Sistema de memória persistente do Coding Agent.

Equivalente ao CLAUDE.md do Claude Code: persiste entre tarefas,
é injetado no system prompt e pode ser atualizado pelo LLM via memory_write.

Estrutura sugerida da memória (Markdown):
  ## Stack
  Python 3.11, FastAPI, SQLite, React

  ## Comandos
  - Rodar: uvicorn main:app --reload
  - Testes: pytest tests/

  ## Convenções
  - Indentação: 4 espaços
  - Nomes de variáveis: snake_case

  ## Estrutura do Projeto
  src/
    main.py        — ponto de entrada
    models/        — modelos SQLAlchemy
    routes/        — routers FastAPI
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from coding_agent.coding_model import CodingSession


# Tamanho máximo da memória para injeção no system prompt
MAX_MEMORY_CHARS = 8000

# Prefixo no system prompt
MEMORY_HEADER = "=== MEMÓRIA DO PROJETO (persiste entre tarefas) ==="
MEMORY_FOOTER = "=== FIM DA MEMÓRIA ==="


# Template de memória estruturada (sugerido pelo system prompt)
MEMORY_TEMPLATE = """## Projeto Atual
nome:
path:
descrição:

## Stack
linguagens:
frameworks:
dependências principais:

## Comandos Úteis
- Rodar:
- Testes:
- Build:

## Convenções
- Indentação:
- Nomes:
- Padrões:

## Notas
-
"""

# Seções esperadas na memória estruturada
MEMORY_SECTIONS = [
    "Projeto Atual",
    "Stack",
    "Comandos Úteis",
    "Convenções",
    "Notas",
]


class CodingMemoryService:
    """Gerencia a memória persistente da CodingSession."""

    @staticmethod
    def ler(db: Session, coding_session_id: int) -> str:
        """Lê a memória da sessão. Retorna string vazia se não há nada."""
        session = db.query(CodingSession).filter(
            CodingSession.id == coding_session_id
        ).first()
        if not session:
            return ""
        return session.memory_content or ""

    @staticmethod
    def escrever(db: Session, coding_session_id: int, content: str) -> bool:
        """Substitui a memória completa da sessão.

        Valida se a memória segue o formato estruturado sugerido.
        Se não tiver nenhuma seção ##, adiciona uma dica no final.
        """
        session = db.query(CodingSession).filter(
            CodingSession.id == coding_session_id
        ).first()
        if not session:
            return False

        # Sugere estrutura se a memória não tem seções
        if content.strip() and "## " not in content:
            content = content.rstrip() + (
                "\n\n---\n💡 Dica: organize a memória com seções: "
                "## Projeto Atual, ## Stack, ## Comandos Úteis, ## Convenções, ## Notas"
            )

        # Trunca para evitar crescimento ilimitado
        if len(content) > MAX_MEMORY_CHARS:
            content = content[:MAX_MEMORY_CHARS] + "\n\n[... truncado — memória muito longa ...]"
        session.memory_content = content
        db.commit()
        return True

    @staticmethod
    def injetar_no_prompt(memory_content: str) -> str:
        """
        Formata a memória para injeção no system prompt.
        Retorna string vazia se não há memória.
        """
        if not memory_content or not memory_content.strip():
            return ""
        return f"\n\n{MEMORY_HEADER}\n{memory_content.strip()}\n{MEMORY_FOOTER}\n"

    @staticmethod
    def atualizar_parcial(
        db: Session,
        coding_session_id: int,
        secao: str,
        conteudo: str,
    ) -> bool:
        """
        Atualiza ou cria uma seção específica da memória.
        Útil para atualizações incrementais sem reescrever tudo.
        """
        mem = CodingMemoryService.ler(db, coding_session_id)
        header = f"## {secao}"

        if header in mem:
            # Localiza a seção e substitui até o próximo ## ou fim
            lines = mem.split("\n")
            novo_lines = []
            dentro_secao = False
            secao_escrita = False
            for line in lines:
                if line.strip() == header:
                    dentro_secao = True
                    novo_lines.append(line)
                    novo_lines.append(conteudo)
                    secao_escrita = True
                    continue
                if dentro_secao and line.startswith("## "):
                    dentro_secao = False
                if not dentro_secao:
                    novo_lines.append(line)
            if not secao_escrita:
                novo_lines.append(f"{header}\n{conteudo}")
            novo_mem = "\n".join(novo_lines)
        else:
            # Adiciona nova seção ao final
            novo_mem = f"{mem.rstrip()}\n\n{header}\n{conteudo}"

        return CodingMemoryService.escrever(db, coding_session_id, novo_mem)
