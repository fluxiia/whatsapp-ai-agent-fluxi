"""
Modelos de dados para o Coding Agent.

CodingSession  — sessão de trabalho vinculada a um Agente de coding.
                 Guarda workspace, memória persistente (equiv. CLAUDE.md) e
                 configurações de acesso a diretórios.

CodingTask     — tarefa isolada dentro de uma sessão.
                 Cada tarefa tem seu próprio histórico de mensagens,
                 processos shell em background e artefatos produzidos.
"""
from __future__ import annotations

import json
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from database import Base


class CodingSession(Base):
    """
    Sessão de trabalho do Coding Agent.

    Uma CodingSession está sempre ligada a um Agente com is_coding_agent=True.
    Ela persiste o estado entre conversas (memória, workspace, histórico de tarefas).
    """
    __tablename__ = "coding_sessions"

    id = Column(Integer, primary_key=True, index=True)

    # Vínculo com o Agente
    agente_id = Column(
        Integer,
        ForeignKey("agentes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # 1:1 com o Agente
        index=True,
    )

    # Workspace — diretório base de trabalho do agente
    workspace_path = Column(
        String(500),
        nullable=False,
        default="",   # preenchido em _ensure_workspace()
    )
    # "sandbox"   → pasta isolada criada automaticamente em fluxi_sandbox/
    # "host_path" → caminho real no servidor (configurado pelo admin)
    workspace_mode = Column(String(20), nullable=False, default="sandbox")

    # Caminhos extras (read-only) que o agente pode ler mas não escrever
    # Armazenados como JSON list de strings
    extra_read_paths = Column(JSON, nullable=True, default=list)

    # Memória persistente (equivalente ao CLAUDE.md do Claude Code)
    # Injetada no system prompt no início de cada tarefa
    memory_content = Column(Text, nullable=True, default="")

    # Prefixo de roteamento no WhatsApp (ex: "#code", "#tarefa", "#dev")
    routing_prefix = Column(String(20), nullable=False, default="#code")

    # Modelo LLM preferido para tarefas de coding (override do agente)
    modelo_coding = Column(String(100), nullable=True)

    # Thinking mode — ativa reasoning tokens nativo do modelo (OpenRouter)
    # e mantém a tool think como fallback para modelos sem suporte
    thinking_mode = Column(Boolean, nullable=False, default=True)

    # Configurações de comportamento
    max_iteracoes = Column(Integer, nullable=False, default=200)
    timeout_shell_rapido = Column(Integer, nullable=False, default=30)   # segundos
    timeout_shell_background = Column(Integer, nullable=False, default=3600)  # 1h

    # Status
    ativa = Column(Boolean, nullable=False, default=True)

    # Timestamps
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())

    # Relacionamentos
    agente = relationship("Agente", back_populates="coding_session", foreign_keys=[agente_id])
    tarefas = relationship(
        "CodingTask",
        back_populates="coding_session",
        cascade="all, delete-orphan",
        order_by="CodingTask.id",
    )

    def __repr__(self) -> str:
        return f"<CodingSession(id={self.id}, agente_id={self.agente_id}, workspace='{self.workspace_path}')>"


class CodingTask(Base):
    """
    Tarefa isolada do Coding Agent.

    Cada tarefa é uma conversa independente com seu próprio histórico,
    processos shell em background e artefatos gerados.
    Isso garante isolamento entre tarefas e permite retomar trabalhos anteriores.
    """
    __tablename__ = "coding_tasks"

    id = Column(Integer, primary_key=True, index=True)
    coding_session_id = Column(
        Integer,
        ForeignKey("coding_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Contexto da tarefa
    titulo = Column(String(200), nullable=False, default="Tarefa sem título")
    objetivo = Column(Text, nullable=True)  # Descrição inicial do usuário

    # Telefone do cliente que originou a tarefa (para envio de respostas)
    telefone_cliente = Column(String(30), nullable=True, index=True)

    # Status da tarefa
    # pending → running → waiting_input | completed | failed | cancelled
    status = Column(String(30), nullable=False, default="pending", index=True)

    # Histórico de mensagens desta tarefa (formato OpenAI messages)
    # Lista de {"role": "user"|"assistant"|"tool", "content": ..., ...}
    messages = Column(JSON, nullable=False, default=list)

    # Processos shell em background ativos nesta tarefa
    # Dict[session_id → {"command", "started_at", "status"}]
    shell_sessions = Column(JSON, nullable=False, default=dict)

    # Artefatos gerados (arquivos criados/modificados)
    # Lista de {"path", "type": "created"|"modified"|"deleted", "timestamp"}
    artifacts = Column(JSON, nullable=False, default=list)

    # Skills ativas nesta tarefa específica (carregamento dinâmico de ferramentas)
    # Lista de strings, ex: ["fluxi_meta", "browser"]
    active_skills = Column(JSON, nullable=False, default=list)

    # Estatísticas de uso do LLM
    tokens_input_total = Column(Integer, nullable=False, default=0)
    tokens_output_total = Column(Integer, nullable=False, default=0)
    iteracoes = Column(Integer, nullable=False, default=0)

    # Erro (se status == "failed")
    error = Column(Text, nullable=True)

    # Timestamps
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())
    completado_em = Column(DateTime(timezone=True), nullable=True)

    # Relacionamentos
    coding_session = relationship("CodingSession", back_populates="tarefas")

    # ── Helpers de conveniência ──────────────────────────────────

    def get_messages(self) -> list:
        return self.messages if self.messages else []

    def add_message(self, role: str, content, **kwargs) -> None:
        msgs = self.get_messages()
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        msgs.append(msg)
        self.messages = msgs

    def add_artifact(self, path: str, artifact_type: str = "created") -> None:
        import time
        arts = self.artifacts if self.artifacts else []
        arts.append({"path": path, "type": artifact_type, "timestamp": time.time()})
        self.artifacts = arts

    def register_shell_session(self, session_id: str, command: str) -> None:
        import time
        shells = self.shell_sessions if self.shell_sessions else {}
        shells[session_id] = {"command": command, "started_at": time.time(), "status": "running"}
        self.shell_sessions = shells

    def update_shell_session_status(self, session_id: str, status: str) -> None:
        shells = self.shell_sessions if self.shell_sessions else {}
        if session_id in shells:
            shells[session_id]["status"] = status
            self.shell_sessions = shells

    def __repr__(self) -> str:
        return f"<CodingTask(id={self.id}, titulo='{self.titulo}', status='{self.status}')>"
