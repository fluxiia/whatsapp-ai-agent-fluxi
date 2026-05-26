"""
CodingService — Núcleo do Coding Agent independente.

Responsabilidades:
  - Criar e gerenciar CodingSessions e CodingTasks
  - Processar mensagens no contexto de tarefas isoladas
  - Executar tools (shell, arquivo, memória, browser, entrega)
  - Manter isolamento total do agente de conversa normal

Diferenças do agente normal (AgenteService):
  - Histórico por TAREFA (não por telefone/cliente)
  - Memory injetada no system prompt (persistente entre tarefas)
  - Shell-first: tools primitivas, sem wrappers de linguagem
  - Background tasks: shell_start + shell_status (sem travar o loop LLM)
  - Tarefas podem ser continuadas em mensagens posteriores
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from agente.agente_model import Agente
from coding_agent.coding_memory import CodingMemoryService
from coding_agent.coding_model import CodingSession, CodingTask
from coding_agent.coding_schema import CodingSessionCriar
from coding_agent.coding_tools import obter_coding_tools, obter_nomes_coding_tools
from config.config_service import ConfiguracaoService
from internal_sandbox.browser_service import InternalBrowserService
from internal_sandbox.file_service import FileService
from internal_sandbox.shell_service import ShellService
from llm_providers.llm_integration_service import LLMIntegrationService
from mcp_client.mcp_service import MCPService
from log.log_service import fluxi_log

logger = __import__('logging').getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# System prompt do coding agent
# ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_BASE = """Você é um agente de coding autônomo integrado ao Fluxi. Você executa tarefas de programação, devops e automação de forma completa e autônoma.

# Convenções de trabalho

## Planejamento
Antes de codar, entenda o que está construindo. Invoque `invocar_skill(skill_nome="coding-planejamento")` no início de tarefas com 3+ passos. Nunca comece sem saber para onde está indo.

## Seguindo padrões
Quando criar ou editar código, primeiro entenda as convenções existentes. Olhe arquivos vizinhos, observe o estilo, use as mesmas bibliotecas e padrões. Nunca assuma que uma biblioteca está disponível — verifique antes.

## Ferramentas
- **Shell-first**: Use `shell_exec` para instalar, compilar, testar, mover, git. É sua ferramenta principal.
- **Edição**: Use `file_read` antes de `file_edit`. Para arquivos novos, use `file_write`.
- **Background**: Para operações longas (builds, servidores), use `shell_start` + `shell_status`.
- **Batch**: Quando múltiplas tools são independentes, execute em paralelo.

## Workspace
Nunca trabalhe na raiz. Cada projeto tem seu diretório via `project_init`. Use `workspace_info` para ver o estado atual.

## Delegação
Use `agent_run` apenas para tarefas auto-contidas que não dependem do seu contexto atual. Se o resultado precisa ser coerente com o que você criou, faça você mesmo.

## Browser
Para navegação web: `activate_skill("browser")` primeiro, depois `browser_navigate`, sempre `browser_screenshot` após navegação para visualizar.

## Entrega
Ao concluir, invoque `invocar_skill(skill_nome="coding-qualidade")` para auto-revisão. Depois empacote com `file_zip` e envie com `send_file_whatsapp`.

## Memória
Use `memory_write` para registrar contexto do projeto entre tarefas.

## Contexto
Use `context_compact` proativamente quando a conversa ficar longa (50+ mensagens).

# Comunicação
Responda em português, direto e técnico. Informe progresso em etapas longas. Sem preâmbulo ou explicação desnecessária.
"""


# ──────────────────────────────────────────────────────────────
# CodingService
# ──────────────────────────────────────────────────────────────

class CodingService:
    """Serviço principal do Coding Agent."""

    # ── Gerenciamento de sessões ────────────────────────────────

    @staticmethod
    def criar_sessao(db: Session, dados: CodingSessionCriar) -> CodingSession:
        """Cria uma nova CodingSession para um agente de coding."""
        agente = db.query(Agente).filter(Agente.id == dados.agente_id).first()
        if not agente:
            raise ValueError(f"Agente {dados.agente_id} não encontrado")

        # Define workspace_path automaticamente no modo sandbox
        workspace_path = dados.workspace_path or ""
        if dados.workspace_mode == "sandbox" or not workspace_path:
            base = os.environ.get(
                "INTERNAL_SANDBOX_ROOT",
                os.path.join(os.path.expanduser("~"), "fluxi_sandbox"),
            )
            workspace_path = os.path.join(base, f"coding_{dados.agente_id}")

        os.makedirs(workspace_path, exist_ok=True)

        session = CodingSession(
            agente_id=dados.agente_id,
            workspace_path=workspace_path,
            workspace_mode=dados.workspace_mode,
            extra_read_paths=dados.extra_read_paths or [],
            routing_prefix=dados.routing_prefix,
            modelo_coding=dados.modelo_coding,
            max_iteracoes=dados.max_iteracoes,
            timeout_shell_rapido=dados.timeout_shell_rapido,
            timeout_shell_background=dados.timeout_shell_background,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def obter_sessao_por_agente(db: Session, agente_id: int) -> Optional[CodingSession]:
        return db.query(CodingSession).filter(
            CodingSession.agente_id == agente_id,
            CodingSession.ativa == True,
        ).first()

    @staticmethod
    def obter_sessao(db: Session, coding_session_id: int) -> Optional[CodingSession]:
        return db.query(CodingSession).filter(
            CodingSession.id == coding_session_id
        ).first()

    @staticmethod
    def listar_sessoes(db: Session) -> List[CodingSession]:
        return db.query(CodingSession).filter(CodingSession.ativa == True).all()

    # ── Gerenciamento de tarefas ────────────────────────────────

    @staticmethod
    def criar_tarefa(
        db: Session,
        coding_session_id: int,
        titulo: str,
        objetivo: Optional[str] = None,
        telefone_cliente: Optional[str] = None,
    ) -> CodingTask:
        task = CodingTask(
            coding_session_id=coding_session_id,
            titulo=titulo,
            objetivo=objetivo,
            telefone_cliente=telefone_cliente,
            status="pending",
            messages=[],
            shell_sessions={},
            artifacts=[],
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def obter_tarefa(db: Session, task_id: int) -> Optional[CodingTask]:
        return db.query(CodingTask).filter(CodingTask.id == task_id).first()

    @staticmethod
    def listar_tarefas(
        db: Session,
        coding_session_id: int,
        status_filter: Optional[str] = None,
        limit: int = 20,
    ) -> List[CodingTask]:
        q = db.query(CodingTask).filter(
            CodingTask.coding_session_id == coding_session_id
        )
        if status_filter and status_filter != "all":
            q = q.filter(CodingTask.status == status_filter)
        return q.order_by(CodingTask.id.desc()).limit(limit).all()

    @staticmethod
    def obter_tarefa_ativa(
        db: Session, coding_session_id: int, telefone_cliente: str
    ) -> Optional[CodingTask]:
        """Retorna a tarefa mais recente em execução para este cliente."""
        return (
            db.query(CodingTask)
            .filter(
                CodingTask.coding_session_id == coding_session_id,
                CodingTask.telefone_cliente == telefone_cliente,
                CodingTask.status.in_(["running", "waiting_input"]),
            )
            .order_by(CodingTask.id.desc())
            .first()
        )

    # ── Processamento de mensagens ──────────────────────────────

    @staticmethod
    async def processar_mensagem(
        db: Session,
        coding_session_id: int,
        mensagem: str,
        telefone_cliente: Optional[str] = None,
        task_id: Optional[int] = None,
        imagem_base64: Optional[str] = None,
        jid_destino_user: Optional[str] = None,
        jid_destino_server: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ponto de entrada principal para processar uma mensagem no coding agent.

        Fluxo:
          1. Obtém (ou cria) a tarefa
          2. Constrói o contexto (system prompt + memória + histórico da tarefa)
          3. Executa o loop LLM com as coding tools
          4. Retorna resposta e artefatos
        """
        inicio = time.time()

        # Obter sessão
        coding_session = CodingService.obter_sessao(db, coding_session_id)
        if not coding_session:
            return {"erro": f"CodingSession {coding_session_id} não encontrada"}

        agente = db.query(Agente).filter(Agente.id == coding_session.agente_id).first()
        if not agente:
            return {"erro": "Agente de coding não encontrado"}

        # --- COMANDO ESPECIAL: LIMPAR HISTÓRICO ---
        if mensagem.strip().lower() in ["limpar", "clear", "reset"]:
            if telefone_cliente:
                # Deleta fisicamente todas as tarefas anteriores deste cliente para esta sessão
                # Isso 'zera' as tarefas e solicitações.
                db.query(CodingTask).filter(
                    CodingTask.coding_session_id == coding_session_id,
                    CodingTask.telefone_cliente == telefone_cliente
                ).delete(synchronize_session=False)

                # Em vez de apagar do banco do WhatsApp (o que quebra a transação atual),
                # vamos apenas renomear o texto para não ser pego mais no ilike('#code')
                prefixo_v = (coding_session.routing_prefix or "#code").lower()
                from mensagem.mensagem_model import Mensagem as MensagemModel
                mensagens_antigas = db.query(MensagemModel).filter(
                    MensagemModel.sessao_id == agente.sessao_id,
                    MensagemModel.telefone_cliente == telefone_cliente,
                    MensagemModel.conteudo_texto.ilike(f"{prefixo_v}%")
                ).all()
                for m in mensagens_antigas:
                    if m.conteudo_texto and m.conteudo_texto.lower().startswith(prefixo_v):
                        m.conteudo_texto = "[LIMPO] " + m.conteudo_texto

                db.commit()
                return {"resposta": "✅ *Coding Agent:* Histórico de tarefas, mensagens e contexto foram COMPLETAMENTE apagados para o seu número. A lousa está limpa!"}
        # Obter ou criar tarefa
        task: CodingTask
        if task_id:
            task = CodingService.obter_tarefa(db, task_id)
            if not task:
                return {"erro": f"Tarefa {task_id} não encontrada"}
            # Se task retomada está "running" — pode estar stuck de uma execução anterior.
            # Marca como failed e cria nova para evitar conflito de sessões DB.
            if task.status == "running":
                fluxi_log.warning("coding", "tarefa", f"Task {task.id} estava running (stuck?) — marcando failed e criando nova", extra={
                    "task_id": task.id, "iteracoes": task.iteracoes,
                })
                task.status = "failed"
                task.error = "Detectada como stuck — nova tarefa criada automaticamente"
                db.commit()
                # Cria nova tarefa para continuar
                titulo = mensagem[:80].strip() if mensagem else "Continuação"
                task = CodingService.criar_tarefa(
                    db,
                    coding_session_id=coding_session_id,
                    titulo=titulo,
                    objetivo=mensagem,
                    telefone_cliente=telefone_cliente,
                )
        else:
            # Verifica se há tarefa ativa para este cliente
            if telefone_cliente:
                task = CodingService.obter_tarefa_ativa(
                    db, coding_session_id, telefone_cliente
                )
                # Se a tarefa ativa está "running", provavelmente está stuck
                if task and task.status == "running":
                    fluxi_log.warning("coding", "tarefa", f"Task ativa {task.id} estava running (stuck?) — marcando failed", extra={
                        "task_id": task.id, "iteracoes": task.iteracoes,
                    })
                    task.status = "failed"
                    task.error = "Detectada como stuck — nova tarefa criada automaticamente"
                    db.commit()
                    task = None  # Forçar criação de nova tarefa
            else:
                task = None

            if not task:
                # Cria nova tarefa — título derivado da mensagem
                titulo = mensagem[:80].strip() if mensagem else "Nova tarefa"
                task = CodingService.criar_tarefa(
                    db,
                    coding_session_id=coding_session_id,
                    titulo=titulo,
                    objetivo=mensagem,
                    telefone_cliente=telefone_cliente,
                )
                
                # --- CONTEXTO MÍNIMO entre tarefas (apenas última tarefa completa) ---
                # NÃO injeta histórico de mensagens WhatsApp — cada task é isolada.
                # Injeta apenas um resumo curto da última tarefa completa para continuidade.
                if telefone_cliente:
                    ultima_tarefa = db.query(CodingTask).filter(
                        CodingTask.coding_session_id == coding_session_id,
                        CodingTask.telefone_cliente == telefone_cliente,
                        CodingTask.id != task.id,
                        CodingTask.status == "completed",
                    ).order_by(CodingTask.id.desc()).first()

                    if ultima_tarefa:
                        # Extrai apenas o pedido original e o resultado final
                        msgs_t = ultima_tarefa.get_messages()
                        pedido_original = ""
                        for m in msgs_t:
                            if m.get("role") == "user" and not pedido_original:
                                c = m.get("content", "")
                                pedido_original = (c[:200] if isinstance(c, str) else str(c)[:200])
                                break
                        artifacts_t = ultima_tarefa.artifacts or []
                        arts_str = ", ".join(a.get("path", "?") for a in artifacts_t[-5:]) if artifacts_t else "nenhum"

                        contexto_previo = (
                            f"[Contexto da tarefa anterior — apenas referência]\n"
                            f"Pedido: {pedido_original}\n"
                            f"Status: {ultima_tarefa.status} | Artefatos: {arts_str}\n"
                            f"---\n"
                            f"Esta é uma NOVA tarefa. Não repita trabalho anterior.\n"
                        )
                        task.add_message("system", contexto_previo)
                        db.commit()

        # Atualiza status
        task.status = "running"
        db.commit()

        # Cachear JID de destino resolvido na task para _enviar_status_whatsapp
        # O JID já vem resolvido corretamente do mensagem_service (com Server correto: lid ou s.whatsapp.net)
        if jid_destino_user and jid_destino_server:
            from neonize.utils import build_jid
            task._jid_destino_cache = build_jid(jid_destino_user, jid_destino_server)
            fluxi_log.debug("coding", "tarefa", f"JID destino cacheado: {jid_destino_user}@{jid_destino_server}", extra={
                "task_id": task.id, "jid_user": jid_destino_user, "jid_server": jid_destino_server,
            })

        fluxi_log.info("coding", "tarefa", f"Tarefa {task.id} iniciando loop", extra={
            "task_id": task.id, "titulo": task.titulo[:80],
            "telefone": telefone_cliente,
            "coding_session_id": coding_session_id,
        })

        try:
            resposta = await CodingService._executar_loop(
                db=db,
                coding_session=coding_session,
                task=task,
                agente=agente,
                mensagem_usuario=mensagem,
                imagem_base64=imagem_base64,
            )

            task.status = "completed"
            task.completado_em = datetime.utcnow()
            db.commit()

            tempo_ms = int((time.time() - inicio) * 1000)
            fluxi_log.info("coding", "tarefa", f"Tarefa {task.id} concluida em {tempo_ms}ms", extra={
                "task_id": task.id, "tempo_ms": tempo_ms,
                "iteracoes": task.iteracoes,
                "tokens_in": task.tokens_input_total,
                "tokens_out": task.tokens_output_total,
            })
            return {
                "task_id": task.id,
                "titulo": task.titulo,
                "status": "completed",
                "resposta": resposta.get("texto", ""),
                "artifacts": task.artifacts or [],
                "tokens_input": task.tokens_input_total,
                "tokens_output": task.tokens_output_total,
                "iteracoes": task.iteracoes,
                "tempo_ms": tempo_ms,
            }

        except Exception as e:
            fluxi_log.error("coding", "tarefa", "Erro ao processar mensagem", exc_info=True, extra={"task_id": task.id})
            task.status = "failed"
            task.error = f"{type(e).__name__}: {str(e)[:500]}"
            db.commit()
            return {
                "task_id": task.id,
                "status": "failed",
                "erro": task.error,
            }

    # ── Loop LLM ───────────────────────────────────────────────

    @staticmethod
    async def _executar_loop(
        db: Session,
        coding_session: CodingSession,
        task: CodingTask,
        agente: Agente,
        mensagem_usuario: str,
        imagem_base64: Optional[str] = None,
        on_llm_text_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """Loop principal LLM do coding agent."""

        # ── Skills do agente (progressive disclosure) ─────────
        _skills_section = ""
        try:
            from skill.skill_service import SkillService
            _agent_skills = SkillService.listar_skills_agente(db, agente.id)
            if _agent_skills:
                _familias: Dict[str, list] = {}
                for _sk in _agent_skills:
                    _fam = _sk.nome.split("-")[0] if "-" in _sk.nome else _sk.nome
                    _familias.setdefault(_fam, []).append(_sk)
                _sk_lines = [
                    "\n\n## Skills Disponíveis (use `invocar_skill` para carregar instruções completas)",
                ]
                for _fam, _membros in _familias.items():
                    # Verifica se existe um skill pai com nome exato da família
                    _pai_real = next((m for m in _membros if m.nome == _fam), None)
                    if _pai_real and len(_membros) == 1:
                        # Skill solo (sem sub-skills)
                        _sk_lines.append(f"- `{_pai_real.nome}`: {_pai_real.descricao}")
                    elif _pai_real:
                        # Família com pai real + sub-skills
                        _sk_lines.append(f"- `{_pai_real.nome}`: {_pai_real.descricao}")
                        for _sub in _membros:
                            if _sub.nome != _fam:
                                _sk_lines.append(f"  - `{_sub.nome}`: {_sub.descricao}")
                    else:
                        # Família SEM pai real — listar todos com nome completo
                        # (ex: coding-planejamento, coding-delegacao — NÃO agrupa como "coding")
                        for _sub in _membros:
                            _sk_lines.append(f"- `{_sub.nome}`: {_sub.descricao}")
                _sk_lines.append(
                    "\n⚡ REGRA: Quando a tarefa se encaixa em uma skill, invoque-a ANTES de começar. "
                    "Use o nome EXATO entre crases (ex: `coding-planejamento`, não apenas `coding`). "
                    "As instruções da skill melhoram significativamente a qualidade do resultado."
                )
                _skills_section = "\n".join(_sk_lines)
                fluxi_log.debug("coding", "skills", f"{len(_agent_skills)} skills carregadas para o prompt", extra={
                    "task_id": task.id, "skills": [s.nome for s in _agent_skills],
                })
        except Exception as _sk_err:
            fluxi_log.warning("coding", "skills", f"Erro ao carregar skills: {_sk_err}", extra={"task_id": task.id})

        # ── System prompt + contexto dinâmico ─────────────────
        memoria = CodingMemoryService.ler(db, coding_session.id)
        mem_injetada = CodingMemoryService.injetar_no_prompt(memoria)

        # Contexto dinâmico (injetado automaticamente a cada tarefa)
        import platform as _platform
        workspace = coding_session.workspace_path
        ctx_parts = [f"\n\n## Contexto Atual (injetado automaticamente)"]
        ctx_parts.append(f"- OS: {_platform.system()} {_platform.release()}")
        ctx_parts.append(f"- Data: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        ctx_parts.append(f"- Modelo: {coding_session.modelo_coding or agente.modelo_llm or 'padrão'}")
        ctx_parts.append(f"- Workspace: {workspace}")
        # Git info
        try:
            import subprocess as _sp
            _git_branch = _sp.check_output(
                ["git", "branch", "--show-current"],
                cwd=workspace, timeout=5, text=True, stderr=_sp.DEVNULL,
            ).strip()
            _git_status = _sp.check_output(
                ["git", "status", "--porcelain"],
                cwd=workspace, timeout=5, text=True, stderr=_sp.DEVNULL,
            ).strip()
            _n_changes = len(_git_status.splitlines()) if _git_status else 0
            ctx_parts.append(f"- Git: branch `{_git_branch}` ({_n_changes} arquivo(s) modificado(s))")
        except Exception:
            ctx_parts.append("- Git: não inicializado")
        # Projetos no workspace (subdiretórios)
        try:
            _subdirs = [d for d in os.listdir(workspace) if os.path.isdir(os.path.join(workspace, d)) and not d.startswith('.')]
            if _subdirs:
                ctx_parts.append(f"- Projetos no workspace: {', '.join(sorted(_subdirs)[:10])}")
        except Exception:
            pass
        ctx_dinamico = "\n".join(ctx_parts) + "\n"

        system_prompt = _SYSTEM_PROMPT_BASE + ctx_dinamico + _skills_section + mem_injetada

        # ── Histórico da tarefa ───────────────────────────────
        messages = list(task.get_messages())

        # Adiciona mensagem atual do usuário
        if imagem_base64:
            content = [
                {"type": "text", "text": mensagem_usuario},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{imagem_base64}"},
                },
            ]
        else:
            content = mensagem_usuario

        messages.append({"role": "user", "content": content})

        # Salva mensagem do usuário imediatamente para que o frontend
        # a veja antes do loop completar a primeira iteração.
        task.messages = list(messages)
        db.commit()

        # ── Tools MCP (carregadas uma vez) ───────────────────
        mcp_tools_list = []
        mcp_tools_map: Dict[str, int] = {}
        try:
            mcp_clients = MCPService.listar_ativos_por_agente(db, agente.id)
            for mcp_client in mcp_clients:
                mcp_tools_db = MCPService.listar_tools_ativas(db, mcp_client.id)
                for mcp_tool in mcp_tools_db:
                    openai_tool = MCPService.converter_mcp_tool_para_openai(mcp_client, mcp_tool)
                    mcp_tools_list.append(openai_tool)
                    mcp_tools_map[openai_tool["function"]["name"]] = mcp_client.id
        except Exception as e:
            fluxi_log.warning("coding", "mcp", "Erro ao carregar MCP tools", extra={"erro": str(e)})

        # ── Parâmetros LLM ───────────────────────────────────
        modelo = (
            coding_session.modelo_coding
            or agente.modelo_llm
            or ConfiguracaoService.obter_valor(db, "openrouter_modelo_padrao", "openai/gpt-4o")
        )
        temperatura = agente.temperatura if agente.temperatura is not None else 0.3
        max_tokens = agente.max_tokens or 4096
        max_iteracoes = coding_session.max_iteracoes or 200

        # ── Reasoning tokens (OpenRouter) ───────────────────
        # Ativo por padrão no coding agent — o modelo usa reasoning
        # interno para planejar melhor antes de responder.
        # thinking_mode (DB) controla se está habilitado.
        _reasoning_config: Optional[Dict[str, Any]] = None
        if coding_session.thinking_mode:
            _reasoning_config = {"effort": "high"}
            fluxi_log.info("coding", "reasoning", "Reasoning tokens habilitado (effort=high)", extra={
                "task_id": task.id, "modelo": modelo,
            })

        # ── Loop ─────────────────────────────────────────────
        # Garante que a queue existe ANTES de qualquer emit, para não perder eventos
        # quando o frontend conecta o WebSocket após o loop já ter começado.
        from coding_agent.coding_stream import ensure_queue as _ensure_q, emit_status
        _ensure_q(task.id)

        logger.info("[CODING task=%d] Loop iniciado — modelo=%s max_iter=%d", task.id, modelo, max_iteracoes)
        fluxi_log.info("coding", "loop", "Loop coding iniciado", extra={
            "task_id": task.id, "modelo": modelo, "max_iteracoes": max_iteracoes,
            "n_mcp_tools": len(mcp_tools_list),
            "telefone": task.telefone_cliente,
        })

        coding_tool_names = obter_nomes_coding_tools()
        iteracao = 0
        texto_final = ""
        erro_anterior = ""
        contagem_erros_iguais = 0

        # ── Detecção inteligente de loop por padrão de tools ────
        # Rastreia as últimas N tools chamadas; se um padrão se repetir
        # (ex: browser_navigate → browser_get_page → browser_navigate → ...),
        # injeta aviso no contexto do LLM para mudar de abordagem.
        _tool_history: list = []          # últimas tools chamadas
        _TOOL_WINDOW = 12                 # janela de análise
        _PATTERN_REPEAT_THRESHOLD = 3     # repetições do padrão para detectar loop
        _loop_warning_injected = False     # já avisou o LLM?
        _loop_abort_count = 0             # quantas vezes o aviso foi ignorado

        # Watchdog: timestamp do último evento emitido
        _ultimo_evento = time.time()
        _WATCHDOG_TIMEOUT = 120  # segundos sem nenhum evento → aborta

        while iteracao < max_iteracoes:
            iteracao += 1

            # ── Watchdog: verifica se houve atividade recente ─────
            if time.time() - _ultimo_evento > _WATCHDOG_TIMEOUT:
                msg_wd = f"⏱️ Watchdog: sem atividade por {_WATCHDOG_TIMEOUT}s — tarefa interrompida."
                logger.warning("[CODING task=%d] %s", task.id, msg_wd)
                fluxi_log.error("coding", "loop", f"Watchdog disparou: {_WATCHDOG_TIMEOUT}s sem atividade", extra={
                    "task_id": task.id, "iteracao": iteracao, "watchdog_timeout_s": _WATCHDOG_TIMEOUT,
                })
                await emit_status(task.id, msg_wd)
                return {"texto": msg_wd, "iteracoes": iteracao, "watchdog": True}

            # ── Aviso de iterações restantes (últimas 10%) ─────
            restantes = max_iteracoes - iteracao
            _pct_90 = int(max_iteracoes * 0.9)
            if iteracao == _pct_90:
                aviso_iter = (
                    f"⚠️ AVISO DO SISTEMA: Você está na iteração {iteracao}/{max_iteracoes}. "
                    f"Restam apenas {restantes} iterações. Finalize a tarefa ou apresente "
                    f"um resultado parcial com o que já conseguiu."
                )
                messages.append({"role": "user", "content": aviso_iter})
                fluxi_log.warning("coding", "loop", f"Aviso de iterações restantes injetado ({restantes} restam)",
                    extra={"task_id": task.id, "iteracao": iteracao, "max": max_iteracoes})

            # Notifica início de novo turno LLM — cria nova bolha no frontend
            from coding_agent.coding_stream import emit_llm_stream_start
            await emit_llm_stream_start(task.id)
            _ultimo_evento = time.time()

            # ── Recarrega Tools Dinamicamente (Skills) ───────────
            active_skills = list(getattr(task, "active_skills", []) or [])
            # Browser skill sempre ativa — o agente decide quando usar
            if "browser" not in active_skills:
                active_skills.append("browser")
            loop_tools = obter_coding_tools(active_skills=active_skills)

            # Quando reasoning nativo está ativo, remove a tool think
            # (o modelo já raciocina internamente via reasoning tokens)
            # Quando reasoning NÃO está ativo E thinking_mode está desligado, remove também
            if _reasoning_config or not coding_session.thinking_mode:
                loop_tools = [t for t in loop_tools if t["function"]["name"] != "think"]

            loop_tools.extend(mcp_tools_list)

            # Verificar se a tarefa ainda é 'running' (pode ter sido cancelada por outra thread)
            db.refresh(task)
            if task.status != "running":
                msg_cancel = f"⚠️ Tarefa interrompida (status: {task.status})"
                if task.telefone_cliente:
                    await CodingService._enviar_status_whatsapp(db, coding_session, task, msg_cancel)
                return {"texto": msg_cancel, "iteracoes": iteracao}

            # Notifica progresso no WhatsApp em tarefas longas
            if task.telefone_cliente and iteracao > 1 and iteracao % 3 == 0:
                await CodingService._enviar_status_whatsapp(
                    db, coding_session, task, f"🧠 *Coding Agent:* Analisando resultados e planejando próximo passo... (iteração {iteracao}/{max_iteracoes})"
                )

            fluxi_log.info("coding", "loop", f"Chamando LLM iter={iteracao}", extra={
                "task_id": task.id, "iteracao": iteracao, "modelo": modelo,
                "n_msgs": len(messages), "n_tools": len(loop_tools) if loop_tools else 0,
            })
            _LLM_TIMEOUT = 180.0  # 3 minutos máximo por chamada LLM
            try:
                resposta_llm = await asyncio.wait_for(
                    LLMIntegrationService.processar_mensagem_com_llm(
                        db=db,
                        messages=[{"role": "system", "content": system_prompt}] + messages,
                        modelo=modelo,
                        agente_id=agente.id,
                        temperatura=temperatura,
                        max_tokens=max_tokens,
                        tools=loop_tools if loop_tools else None,
                        on_text_delta=on_llm_text_delta,
                        reasoning=_reasoning_config,
                    ),
                    timeout=_LLM_TIMEOUT,
                )
            except asyncio.TimeoutError:
                msg_timeout = f"Timeout de {_LLM_TIMEOUT:.0f}s na chamada LLM (iteracao {iteracao})"
                logger.error("[CODING task=%d] %s", task.id, msg_timeout)
                fluxi_log.error("coding", "tarefa", msg_timeout, extra={"task_id": task.id, "modelo": modelo, "iteracao": iteracao})
                if task.telefone_cliente:
                    await CodingService._enviar_status_whatsapp(
                        db, coding_session, task, f"⏱️ *Timeout:* A chamada ao LLM demorou mais de {_LLM_TIMEOUT:.0f}s. Tentando novamente..."
                    )
                # Tenta mais uma vez com timeout maior antes de desistir
                if iteracao <= 2:
                    continue
                return {"texto": f"⏱️ Timeout na chamada LLM após {iteracao} iterações. Tente novamente.", "iteracoes": iteracao, "timeout": True}
            _ultimo_evento = time.time()

            # Atualiza contadores (protege contra None vindo de provedores locais)
            task.tokens_input_total = (task.tokens_input_total or 0) + (resposta_llm.get("tokens_input") or 0)
            task.tokens_output_total = (task.tokens_output_total or 0) + (resposta_llm.get("tokens_output") or 0)
            task.iteracoes = iteracao

            # Persiste o estado atual das mensagens e contadores imediatamente
            db.commit()
            db.refresh(task)

            # Suporta provedores que retornam "text" ou "conteudo"
            conteudo_texto = (
                resposta_llm.get("text")
                or resposta_llm.get("conteudo")
                or ""
            )
            finish_reason = resposta_llm.get("finish_reason", "stop")
            tool_calls = resposta_llm.get("tool_calls") or []
            logger.info("[CODING task=%d] iter=%d LLM respondeu finish=%s tools=%d texto=%d chars",
                        task.id, iteracao, finish_reason, len(tool_calls), len(conteudo_texto))
            fluxi_log.info("coding", "loop", f"LLM respondeu iter={iteracao}", extra={
                "task_id": task.id, "iteracao": iteracao,
                "finish_reason": finish_reason, "n_tool_calls": len(tool_calls),
                "texto_chars": len(conteudo_texto),
                "tokens_in": resposta_llm.get("tokens_input", 0),
                "tokens_out": resposta_llm.get("tokens_output", 0),
            })

            # Adiciona resposta do assistente ao histórico
            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": conteudo_texto}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            # Preserva reasoning entre turnos (OpenRouter multi-turn)
            _resp_reasoning = resposta_llm.get("reasoning")
            _resp_reasoning_details = resposta_llm.get("reasoning_details")
            # Debug: log para rastrear se reasoning chega ao coding_service
            if _resp_reasoning or _resp_reasoning_details:
                _r_len = len(_resp_reasoning or "") + sum(
                    len(d.get("content", "") if isinstance(d, dict) else str(d))
                    for d in (_resp_reasoning_details or [])
                )
                logger.info("[CODING task=%d] iter=%d REASONING presente: reasoning=%s details=%s total=%d chars",
                            task.id, iteracao,
                            len(_resp_reasoning) if _resp_reasoning else "None",
                            len(_resp_reasoning_details) if _resp_reasoning_details else "None",
                            _r_len)
            else:
                logger.info("[CODING task=%d] iter=%d REASONING ausente nas chaves: %s",
                            task.id, iteracao,
                            [k for k in resposta_llm.keys() if 'reason' in k.lower()])
            # ── Extrair e emitir reasoning para o frontend (ANTES da resposta) ──
            # Monta o texto de reasoning de TODAS as fontes disponíveis
            _reasoning_text = ""

            # 1) Tenta reasoning_details (array de blocos)
            if _resp_reasoning_details and isinstance(_resp_reasoning_details, list):
                assistant_msg["reasoning_details"] = _resp_reasoning_details
                _reasoning_text = " ".join(
                    d.get("content", "") if isinstance(d, dict) else str(d)
                    for d in _resp_reasoning_details
                ).strip()
                logger.debug("[CODING task=%d] reasoning_details extraído: %d chars de %d items, content_sample=%s",
                             task.id, len(_reasoning_text), len(_resp_reasoning_details),
                             repr(_reasoning_text[:200]) if _reasoning_text else "VAZIO")

            # 2) Se details não tinha conteúdo, usa reasoning string
            if not _reasoning_text and _resp_reasoning:
                assistant_msg["reasoning"] = _resp_reasoning
                _reasoning_text = _resp_reasoning.strip()
                logger.debug("[CODING task=%d] reasoning string usado: %d chars, sample=%s",
                             task.id, len(_reasoning_text), repr(_reasoning_text[:200]))

            # 3) Emite reasoning PRIMEIRO para o frontend aparecer antes da resposta
            if _reasoning_text:
                from coding_agent.coding_stream import emit_reasoning
                await emit_reasoning(task.id, _reasoning_text)
                logger.info("[CODING task=%d] emit_reasoning CHAMADO: %d chars", task.id, len(_reasoning_text))
            elif _resp_reasoning or _resp_reasoning_details:
                logger.warning("[CODING task=%d] reasoning presente mas texto vazio! reasoning=%s details=%s",
                               task.id, type(_resp_reasoning), type(_resp_reasoning_details))

            # Emite texto completo do LLM no frontend (após o reasoning)
            if conteudo_texto:
                from coding_agent.coding_stream import emit_llm_delta
                await emit_llm_delta(task.id, conteudo_texto)
                _ultimo_evento = time.time()
            messages.append(assistant_msg)

            # Sem tool calls → resposta final
            if not tool_calls or finish_reason == "stop":
                texto_final = conteudo_texto
                break

            # ── Batch Execution: tools read-only podem rodar em paralelo ──
            # Tools que NUNCA podem rodar em paralelo (modificam estado)
            _SERIAL_TOOLS = {
                "file_write", "file_edit", "shell_exec", "shell_start",
                "shell_write", "shell_kill", "change_workspace", "project_init",
                "memory_write", "send_file_whatsapp", "send_screenshot_whatsapp",
                "activate_skill", "task_create", "agent_run", "context_compact",
                "fluxi_criar_ferramenta", "fluxi_atualizar_ferramenta",
                "fluxi_criar_agente", "fluxi_criar_skill", "fluxi_conectar_mcp",
                "browser_navigate",
            }

            # Parse todos os tool_calls primeiro
            _parsed_tcs = []
            for tc in tool_calls:
                _tc_name = tc.get("function", {}).get("name", "")
                _tc_id = tc.get("id", f"call_{iteracao}")
                try:
                    import json
                    _tc_args_raw = tc.get("function", {}).get("arguments", "{}")
                    _tc_args = json.loads(_tc_args_raw) if isinstance(_tc_args_raw, str) else _tc_args_raw
                except Exception:
                    _tc_args = {}
                _parsed_tcs.append((_tc_name, _tc_id, _tc_args, tc))

            # Decide se pode executar em paralelo
            _tc_names = [n for n, _, _, _ in _parsed_tcs]
            _can_parallel = (
                len(_parsed_tcs) > 1
                and all(n not in _SERIAL_TOOLS for n in _tc_names)
            )

            if _can_parallel:
                fluxi_log.info("coding", "batch", f"Executando {len(_parsed_tcs)} tools em paralelo: {_tc_names}", extra={
                    "task_id": task.id, "iteracao": iteracao, "tools": _tc_names,
                })

            async def _execute_single_tool(_tool_name, _tool_call_id, _args, _tc_raw):
                """Executa uma tool e retorna (tool_name, tool_call_id, args, resultado_texto, resultado_raw)."""
                from coding_agent.coding_stream import emit_tool_start, emit_tool_result as _emit_tr

                fluxi_log.info("coding", "ferramenta", f"Executando tool: {_tool_name}", extra={
                    "task_id": task.id, "iteracao": iteracao, "tool": _tool_name,
                    "args_keys": list(_args.keys())[:5],
                    "parallel": _can_parallel,
                })
                # Log também em module=ferramenta para aparecer no filtro da UI de logs
                fluxi_log.info("ferramenta", "coding", f"[Coding] Executando: {_tool_name}", extra={
                    "task_id": task.id, "iteracao": iteracao, "tool": _tool_name,
                })

                await emit_tool_start(task.id, _tool_name, _args)

                _t_tool = time.time()
                try:
                    _resultado = await CodingService._executar_tool(
                        db=db,
                        coding_session=coding_session,
                        task=task,
                        agente=agente,
                        tool_name=_tool_name,
                        args=_args,
                        mcp_tools_map=mcp_tools_map,
                    )
                    _tool_ms = int((time.time() - _t_tool) * 1000)
                    fluxi_log.info("coding", "ferramenta", f"Tool concluida: {_tool_name} ({_tool_ms}ms)", extra={
                        "task_id": task.id, "tool": _tool_name, "tempo_ms": _tool_ms,
                    })
                    fluxi_log.info("ferramenta", "coding", f"[Coding] Concluida: {_tool_name} ({_tool_ms}ms)", extra={
                        "task_id": task.id, "tool": _tool_name, "tempo_ms": _tool_ms,
                    })
                    if _resultado is None:
                        _resultado = {"error": f"Tool '{_tool_name}' retornou None — sem resultado"}
                except Exception as _tool_exc:
                    logger.exception("[CODING task=%d] Exceção em tool '%s': %s", task.id, _tool_name, _tool_exc)
                    fluxi_log.error("coding", "ferramenta", f"Erro em tool {_tool_name}: {_tool_exc}", extra={
                        "task_id": task.id, "tool": _tool_name, "erro_tipo": type(_tool_exc).__name__,
                    }, exc_info=True)
                    fluxi_log.error("ferramenta", "coding", f"[Coding] Erro: {_tool_name} — {_tool_exc}", extra={
                        "task_id": task.id, "tool": _tool_name,
                    })
                    _resultado = {"error": f"{type(_tool_exc).__name__}: {str(_tool_exc)[:300]}"}

                _res_texto = _resultado_para_texto(_resultado)
                await _emit_tr(task.id, _tool_name, _res_texto)
                return (_tool_name, _tool_call_id, _args, _res_texto, _resultado)

            # Executa em paralelo ou sequencial
            if _can_parallel:
                _batch_results = await asyncio.gather(*[
                    _execute_single_tool(n, cid, a, tc)
                    for n, cid, a, tc in _parsed_tcs
                ])
            else:
                _batch_results = []
                for n, cid, a, tc in _parsed_tcs:
                    # Notifica início de ferramenta no WhatsApp (só no modo sequencial)
                    if task.telefone_cliente:
                        msg_status = f"🛠️ *Coding Agent:* Executando `{n}`..."
                        if n == "think" and a.get("thought"):
                            thought = a["thought"][:150].strip() + "..." if len(a["thought"]) > 150 else a["thought"]
                            msg_status = f"💭 *Pensando:* {thought}"
                        await CodingService._enviar_status_whatsapp(db, coding_session, task, msg_status)

                    _batch_results.append(await _execute_single_tool(n, cid, a, tc))

            _ultimo_evento = time.time()

            # Processa resultados (adiciona ao histórico, detecta erros e loops)
            for (_r_tool_name, _r_call_id, _r_args, _r_res_str, _r_resultado) in _batch_results:
                logger.info("[CODING task=%d] iter=%d tool_result: %s ok=%s",
                            task.id, iteracao, _r_tool_name,
                            "error" not in _r_res_str.lower()[:100])

                # Adiciona resultado ao histórico
                messages.append({
                    "role": "tool",
                    "tool_call_id": _r_call_id,
                    "tool_name": _r_tool_name,
                    "content": _r_res_str,
                })

                # Detecção de loops de erro infinitos
                if "error" in _r_res_str.lower() or "failed" in _r_res_str.lower():
                    if _r_res_str == erro_anterior:
                        contagem_erros_iguais += 1
                    else:
                        contagem_erros_iguais = 1
                    erro_anterior = _r_res_str

                    if task.telefone_cliente and contagem_erros_iguais >= 1:
                        await CodingService._enviar_status_whatsapp(
                            db, coding_session, task, f"⚠️ *Aviso de Erro:* O agente encontrou um problema ao executar `{_r_tool_name}`. Ele tentará corrigir automaticamente.\n\n`{_r_res_str[:250]}`"
                        )
                else:
                    erro_anterior = ""
                    contagem_erros_iguais = 0

                if contagem_erros_iguais >= 3:
                    msg_pausa = "🛑 *Parada de Segurança:* O agente está preso no mesmo erro repetidamente. Processo interrompido para evitar loop infinito."
                    if task.telefone_cliente:
                        await CodingService._enviar_status_whatsapp(db, coding_session, task, msg_pausa)
                    return {"texto": msg_pausa, "iteracoes": iteracao, "erro_repetitivo": True}

                # ── Detecção de loop por padrão de tools ────────────
                _tool_history.append(_r_tool_name)
                if len(_tool_history) > _TOOL_WINDOW:
                    _tool_history = _tool_history[-_TOOL_WINDOW:]

                if len(_tool_history) >= 6:
                    _detected_pattern = None
                    for plen in range(2, 5):
                        if len(_tool_history) < plen * _PATTERN_REPEAT_THRESHOLD:
                            continue
                        pattern = _tool_history[-plen:]
                        repeats = 0
                        for offset in range(0, len(_tool_history) - plen + 1, plen):
                            start = len(_tool_history) - plen - (repeats * plen)
                            if start < 0:
                                break
                            chunk = _tool_history[start:start + plen]
                            if chunk == pattern:
                                repeats += 1
                            else:
                                break
                        if repeats >= _PATTERN_REPEAT_THRESHOLD:
                            _detected_pattern = pattern
                            break

                    if _detected_pattern:
                        pattern_str = " → ".join(_detected_pattern)
                        fluxi_log.warning("coding", "loop",
                            f"Padrão repetitivo detectado: [{pattern_str}] x{repeats}",
                            extra={"task_id": task.id, "iteracao": iteracao, "pattern": _detected_pattern})

                        if not _loop_warning_injected:
                            _loop_warning_injected = True
                            aviso_loop = (
                                f"⚠️ AVISO DO SISTEMA: Detectado comportamento circular. "
                                f"Você está repetindo o padrão [{pattern_str}] sem progresso. "
                                f"PARE de usar essas mesmas ferramentas. Mude completamente de abordagem: "
                                f"tente uma ferramenta diferente, simplifique o objetivo, ou apresente "
                                f"sua resposta final com o que já tem."
                            )
                            messages.append({"role": "user", "content": aviso_loop})
                            await emit_status(task.id, f"⚠️ Loop detectado: {pattern_str} — forçando mudança de abordagem")
                            if task.telefone_cliente:
                                await CodingService._enviar_status_whatsapp(
                                    db, coding_session, task,
                                    f"⚠️ Loop detectado ({pattern_str}). Mudando abordagem..."
                                )
                        else:
                            _loop_abort_count += 1
                            if _loop_abort_count >= 2:
                                msg_abort = (
                                    f"🛑 Tarefa interrompida: o agente ficou preso em loop "
                                    f"({pattern_str}) mesmo após aviso. "
                                    f"Tente reformular o pedido ou use um modelo mais capaz."
                                )
                                if task.telefone_cliente:
                                    await CodingService._enviar_status_whatsapp(db, coding_session, task, msg_abort)
                                return {"texto": msg_abort, "iteracoes": iteracao, "loop_detectado": True}

                # Trata envio de arquivos/screenshots (side-effect)
                await CodingService._handle_delivery_side_effects(
                    db=db,
                    coding_session=coding_session,
                    task=task,
                    tool_name=_r_tool_name,
                    args=_r_args,
                    resultado=_r_resultado,
                )

            # Salva mensagens após todas as ferramentas da iteração
            task.messages = messages
            db.commit()
            db.refresh(task)

        # Salva histórico final
        task.messages = messages
        db.commit()

        # Fallback: se máximo de iterações atingido sem resposta final, usa a última mensagem do assistente
        if not texto_final and iteracao >= max_iteracoes:
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    c = msg["content"]
                    if isinstance(c, list):
                        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
                    if c:
                        texto_final = c
                        break
            if not texto_final:
                texto_final = f"⚠️ Máximo de iterações ({max_iteracoes}) atingido. A tarefa pode estar incompleta."
            logger.warning("[CODING task=%d] Máximo de iterações atingido — usando fallback", task.id)

        logger.info("[CODING task=%d] Loop concluído em %d iterações — texto=%d chars",
                    task.id, iteracao, len(texto_final))
        fluxi_log.info("coding", "loop", f"Loop concluido em {iteracao} iteracoes", extra={
            "task_id": task.id, "iteracoes": iteracao,
            "texto_chars": len(texto_final),
            "tokens_in_total": task.tokens_input_total,
            "tokens_out_total": task.tokens_output_total,
        })
        return {"texto": texto_final, "iteracoes": iteracao}

    # ── Executor de tools ───────────────────────────────────────

    @staticmethod
    async def _executar_tool(
        db: Session,
        coding_session: CodingSession,
        task: CodingTask,
        agente: Agente,
        tool_name: str,
        args: Dict[str, Any],
        mcp_tools_map: Dict[str, int],
    ) -> Dict[str, Any]:
        """Dispatch de tools do coding agent."""

        workspace = coding_session.workspace_path

        # ── Skills (Carregamento Dinâmico) ─────────────────────
        if tool_name == "activate_skill":
            skill_name = args.get("skill_name")
            if not skill_name:
                return {"error": "skill_name não fornecido"}
                
            active_skills = getattr(task, "active_skills", []) or []
            if skill_name in active_skills:
                return {"result": f"A skill '{skill_name}' já está ativa."}
                
            active_skills.append(skill_name)
            task.active_skills = active_skills
            db.commit()
            
            return {
                "result": f"Skill '{skill_name}' ativada com sucesso! As ferramentas associadas a esta skill estão agora disponíveis no seu contexto."
            }

        # ── Shell ──────────────────────────────────────────────
        if tool_name == "shell_exec":
            cwd = args.get("cwd") or workspace
            timeout = args.get("timeout") or coding_session.timeout_shell_rapido or 30
            return await ShellService.exec_command(
                command=args["command"],
                exec_dir=cwd,
                timeout=float(timeout),
            )

        if tool_name == "shell_start":
            cwd = args.get("cwd") or workspace
            result = await ShellService.exec_command(
                command=args["command"],
                exec_dir=cwd,
                background=True,
            )
            # Registra na tarefa
            session_id = result.get("session_id", "")
            if session_id:
                task.register_shell_session(session_id, args["command"])
                db.commit()
                # Encaminha output em tempo real para o stream da tarefa
                asyncio.create_task(_stream_shell_output(task.id, session_id))
            return result

        if tool_name == "shell_status":
            session_id = args["session_id"]
            result = ShellService.view_session(session_id)
            # Suporte a tail_lines
            tail = args.get("tail_lines")
            if tail and "output" in result and result["output"]:
                lines = result["output"].splitlines()
                result["output"] = "\n".join(lines[-tail:])
            # Atualiza status na tarefa se concluído
            if result.get("status") in ("done", "error", "killed"):
                task.update_shell_session_status(session_id, result["status"])
                db.commit()
            return result

        if tool_name == "shell_write":
            return await ShellService.write_to_session(
                session_id=args["session_id"],
                input_text=args["input"],
                press_enter=args.get("press_enter", True),
            )

        if tool_name == "shell_kill":
            result = await ShellService.kill_session(args["session_id"])
            task.update_shell_session_status(args["session_id"], "killed")
            db.commit()
            return result

        # ── Arquivo ───────────────────────────────────────────
        if tool_name == "file_read":
            return FileService.read_file(
                file=args["path"],
                start_line=args.get("start_line"),
                end_line=args.get("end_line"),
            )

        if tool_name == "file_write":
            result = FileService.write_file(
                file=args["path"],
                content=args["content"],
                append=args.get("append", False),
            )
            if result.get("success"):
                task.add_artifact(args["path"], "created")
                db.commit()
            return result

        if tool_name == "file_edit":
            result = FileService.edit_file(
                file=args["path"],
                old_str=args["old_str"],
                new_str=args["new_str"],
                expected_replacements=args.get("expected_replacements", 1),
            )
            if result.get("success"):
                task.add_artifact(args["path"], "modified")
                db.commit()
            return result

        if tool_name == "file_list":
            return FileService.list_path(
                path=args["path"],
                recursive=args.get("recursive", False),
                show_hidden=args.get("show_hidden", False),
            )

        if tool_name == "file_find":
            return FileService.find_files(
                path=args["path"],
                glob=args["glob"],
            )

        if tool_name == "file_grep":
            return FileService.grep_files(
                path=args["path"],
                pattern=args["pattern"],
                include=args.get("include"),
                case_insensitive=args.get("case_insensitive", True),
                max_results=args.get("max_results", 50),
            )

        if tool_name == "file_zip":
            result = FileService.zip_path(
                source_path=args["source_path"],
                output_path=args.get("output_path"),
            )
            if result.get("success"):
                task.add_artifact(result["zip_path"], "created")
                db.commit()
            return result

        # ── Workspace / Memória ───────────────────────────────
        if tool_name == "change_workspace":
            new_path = args["new_path"]
            # Tenta resolver/criar se for relativo ao sandbox, ou usar absoluto
            try:
                os.makedirs(new_path, exist_ok=True)
                coding_session.workspace_path = new_path
                db.commit()
                return {
                    "success": True, 
                    "message": f"Workspace alterado para: {new_path}",
                    "path": new_path
                }
            except Exception as e:
                return {"error": f"Erro ao mudar workspace: {str(e)}"}

        if tool_name == "workspace_info":
            info = FileService.workspace_info(workspace)
            # Enriquece com lista de projetos (subdiretórios)
            try:
                subdirs = []
                for d in os.listdir(workspace):
                    full = os.path.join(workspace, d)
                    if os.path.isdir(full) and not d.startswith('.'):
                        # Calcula tamanho e último acesso
                        try:
                            mtime = os.path.getmtime(full)
                            from datetime import datetime as _dt
                            last_mod = _dt.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                        except Exception:
                            last_mod = "?"
                        subdirs.append({"name": d, "last_modified": last_mod})
                if subdirs:
                    info["projects"] = sorted(subdirs, key=lambda x: x["name"])
                    info["projects_hint"] = (
                        f"Projetos encontrados: {', '.join(s['name'] for s in subdirs)}. "
                        "Use change_workspace para trocar para um projeto existente ou project_init para criar um novo."
                    )
                else:
                    info["projects"] = []
                    info["projects_hint"] = "Nenhum projeto encontrado. Use project_init para criar um novo projeto."
            except Exception:
                pass
            return info

        if tool_name == "project_init":
            import re
            project_name = args.get("project_name", "novo-projeto")
            description = args.get("description", "")
            template = args.get("template", "empty")
            # Sanitiza nome
            project_name = re.sub(r'[^a-z0-9\-_]', '-', project_name.lower().strip())
            project_name = re.sub(r'-+', '-', project_name).strip('-') or "novo-projeto"
            project_path = os.path.join(workspace, project_name)
            if os.path.exists(project_path):
                return {"error": f"Projeto '{project_name}' já existe em {project_path}. Use change_workspace para acessá-lo."}
            os.makedirs(project_path, exist_ok=True)
            # README
            readme = f"# {project_name}\n\n{description}\n" if description else f"# {project_name}\n"
            with open(os.path.join(project_path, "README.md"), "w") as f:
                f.write(readme)
            # .gitignore
            gitignore_content = "node_modules/\n__pycache__/\n*.pyc\n.env\n.venv/\nvenv/\ndist/\nbuild/\n.DS_Store\n"
            with open(os.path.join(project_path, ".gitignore"), "w") as f:
                f.write(gitignore_content)
            # Templates
            created_files = ["README.md", ".gitignore"]
            if template == "python":
                os.makedirs(os.path.join(project_path, "src"), exist_ok=True)
                os.makedirs(os.path.join(project_path, "tests"), exist_ok=True)
                with open(os.path.join(project_path, "src", "__init__.py"), "w") as f:
                    f.write("")
                with open(os.path.join(project_path, "tests", "__init__.py"), "w") as f:
                    f.write("")
                with open(os.path.join(project_path, "requirements.txt"), "w") as f:
                    f.write("# Dependências do projeto\n")
                created_files.extend(["src/__init__.py", "tests/__init__.py", "requirements.txt"])
            elif template == "node":
                os.makedirs(os.path.join(project_path, "src"), exist_ok=True)
                pkg = {
                    "name": project_name,
                    "version": "1.0.0",
                    "description": description or "",
                    "main": "src/index.js",
                    "scripts": {"start": "node src/index.js", "test": "echo 'no tests'"},
                }
                import json as _json
                with open(os.path.join(project_path, "package.json"), "w") as f:
                    _json.dump(pkg, f, indent=2)
                with open(os.path.join(project_path, "src", "index.js"), "w") as f:
                    f.write("// Entry point\nconsole.log('Hello from " + project_name + "');\n")
                created_files.extend(["package.json", "src/index.js"])
            elif template == "web":
                os.makedirs(os.path.join(project_path, "css"), exist_ok=True)
                os.makedirs(os.path.join(project_path, "js"), exist_ok=True)
                with open(os.path.join(project_path, "index.html"), "w") as f:
                    f.write(f'<!DOCTYPE html>\n<html lang="pt-BR">\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n  <title>{project_name}</title>\n  <link rel="stylesheet" href="css/style.css">\n</head>\n<body>\n  <h1>{project_name}</h1>\n  <script src="js/main.js"></script>\n</body>\n</html>\n')
                with open(os.path.join(project_path, "css", "style.css"), "w") as f:
                    f.write("/* Estilos do projeto */\n* { margin: 0; padding: 0; box-sizing: border-box; }\nbody { font-family: sans-serif; }\n")
                with open(os.path.join(project_path, "js", "main.js"), "w") as f:
                    f.write("// JavaScript principal\nconsole.log('" + project_name + " carregado');\n")
                created_files.extend(["index.html", "css/style.css", "js/main.js"])
            # Muda workspace automaticamente
            coding_session.workspace_path = project_path
            db.commit()
            # Registra artefatos
            for cf in created_files:
                task.add_artifact(os.path.join(project_path, cf), "created")
            db.commit()
            return {
                "success": True,
                "project_name": project_name,
                "project_path": project_path,
                "template": template,
                "created_files": created_files,
                "message": f"Projeto '{project_name}' criado com template '{template}'. Workspace alterado automaticamente. Use memory_write para registrar o contexto do projeto.",
            }

        if tool_name == "memory_read":
            content = CodingMemoryService.ler(db, coding_session.id)
            if not content or not content.strip():
                from coding_agent.coding_memory import MEMORY_TEMPLATE
                return {
                    "memory": "(vazia)",
                    "chars": 0,
                    "template": MEMORY_TEMPLATE,
                    "hint": "A memória está vazia. Use memory_write com o template acima para registrar o contexto do projeto. Organize com seções ## para manter a memória estruturada.",
                }
            return {
                "memory": content,
                "chars": len(content),
                "max_chars": 8000,
            }

        if tool_name == "memory_write":
            success = CodingMemoryService.escrever(db, coding_session.id, args["content"])
            return {"success": success, "message": "Memória atualizada"}

        # ── Tarefas ───────────────────────────────────────────
        if tool_name == "task_list":
            status_filter = args.get("status_filter", "all")
            tarefas = CodingService.listar_tarefas(
                db, coding_session.id, status_filter=status_filter
            )
            return {
                "tasks": [
                    {
                        "id": t.id,
                        "titulo": t.titulo,
                        "status": t.status,
                        "iteracoes": t.iteracoes,
                        "artifacts": len(t.artifacts or []),
                        "criado_em": str(t.criado_em),
                    }
                    for t in tarefas
                ]
            }

        if tool_name == "task_status":
            t = CodingService.obter_tarefa(db, args["task_id"])
            if not t:
                return {"error": f"Tarefa {args['task_id']} não encontrada"}
            # Última mensagem do assistente
            ultima_assistente = None
            for msg in reversed(t.get_messages()):
                if msg.get("role") == "assistant" and msg.get("content"):
                    ultima_assistente = msg["content"]
                    if isinstance(ultima_assistente, list):
                        ultima_assistente = " ".join(
                            p.get("text", "") for p in ultima_assistente if isinstance(p, dict)
                        )
                    break
            return {
                "id": t.id,
                "titulo": t.titulo,
                "status": t.status,
                "iteracoes": t.iteracoes,
                "artifacts": t.artifacts or [],
                "shell_sessions_ativas": [
                    sid for sid, info in (t.shell_sessions or {}).items()
                    if info.get("status") == "running"
                ],
                "ultima_mensagem_assistente": ultima_assistente,
                "error": t.error,
            }

        # ── Web fetch / search ───────────────────────────────
        if tool_name == "web_fetch":
            import httpx
            from html.parser import HTMLParser

            class _TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.texts: list = []
                    self._skip = False

                def handle_starttag(self, tag, attrs):
                    if tag in ("script", "style", "nav", "footer", "head"):
                        self._skip = True

                def handle_endtag(self, tag):
                    if tag in ("script", "style", "nav", "footer", "head"):
                        self._skip = False

                def handle_data(self, data):
                    if not self._skip and data.strip():
                        self.texts.append(data.strip())

            url = args["url"]
            method = args.get("method", "GET").upper()
            headers = args.get("headers", {})
            body = args.get("body")
            max_chars = args.get("max_chars", 8000)
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                    if method == "POST":
                        r = await client.post(url, headers=headers, content=body)
                    else:
                        r = await client.get(url, headers=headers)
                content_type = r.headers.get("content-type", "")
                if "text/html" in content_type:
                    parser = _TextExtractor()
                    parser.feed(r.text)
                    text = "\n".join(parser.texts)
                else:
                    text = r.text
                return {
                    "url_final": str(r.url),
                    "status_code": r.status_code,
                    "content": text[:max_chars],
                    "truncated": len(text) > max_chars,
                }
            except Exception as e:
                return {"error": str(e), "url": url}

        if tool_name == "web_search":
            query = args["query"]
            num = min(args.get("num_results", 8), 20)
            try:
                import warnings
                warnings.filterwarnings("ignore", message=".*duckduckgo_search.*")
                from duckduckgo_search import DDGS

                # Executa busca em executor (a lib é síncrona)
                def _buscar():
                    return list(DDGS().text(query, max_results=num))

                raw = await asyncio.get_event_loop().run_in_executor(None, _buscar)
                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                    for r in raw
                ]
                if not results:
                    return {
                        "query": query,
                        "results": [],
                        "note": "Nenhum resultado encontrado. Tente reformular a busca com termos diferentes.",
                    }
                return {"query": query, "results": results, "total": len(results)}
            except Exception as e:
                return {"error": str(e), "query": query}

        # ── Think ─────────────────────────────────────────────
        if tool_name == "think":
            return {
                "thought_received": True,
                "chars": len(args.get("thought", "")),
                "note": "Raciocínio registrado. Continue com a próxima ação.",
            }

        # ── Invocar Skill (progressive disclosure) ───────────
        if tool_name == "invocar_skill":
            from skill.skill_service import SkillService

            skill_nome = (args.get("skill_nome") or "").strip()
            argumentos = args.get("argumentos") or {}

            if not skill_nome:
                return {"error": "skill_nome é obrigatório"}

            skill = SkillService.obter_por_nome(db, skill_nome)

            # Fallback: se não encontrou, procura skills com esse prefixo
            if not skill or not skill.ativa:
                _agent_skills = SkillService.listar_skills_agente(db, agente.id)
                _nomes_permitidos = sorted(s.nome for s in _agent_skills)
                _sugestoes = [n for n in _nomes_permitidos if n.startswith(skill_nome + "-") or n.startswith(skill_nome)]
                if _sugestoes:
                    return {
                        "error": f"Skill '{skill_nome}' não existe. Você quis dizer uma destas?",
                        "skills_sugeridas": _sugestoes,
                        "dica": f"Use o nome exato, ex: invocar_skill(skill_nome='{_sugestoes[0]}')",
                    }
                return {"error": f"Skill '{skill_nome}' não encontrada ou inativa. Skills disponíveis: {', '.join(_nomes_permitidos)}"}

            # Verifica se a skill está associada ao agente
            _agent_skills = SkillService.listar_skills_agente(db, agente.id)
            _nomes_permitidos = {s.nome for s in _agent_skills}
            if skill_nome not in _nomes_permitidos:
                return {"error": f"Skill '{skill_nome}' não está associada a este agente. Skills disponíveis: {', '.join(sorted(_nomes_permitidos))}"}

            # Executa script se houver
            dados_script = SkillService.executar_script(skill, argumentos)

            # Processa instrução com substituição de variáveis
            instrucao = skill.instrucao_completa or ""
            if dados_script:
                for chave, valor in dados_script.items():
                    instrucao = instrucao.replace(f"{{{chave}}}", str(valor))

            fluxi_log.info("coding", "skill", f"Skill '{skill_nome}' invocada ({len(instrucao)} chars)", extra={
                "task_id": task.id, "skill": skill_nome, "versao": skill.versao,
            })
            # Log também em module=skill para aparecer no filtro da UI de logs
            fluxi_log.info("skill", "coding", f"[Coding] Skill '{skill_nome}' invocada ({len(instrucao)} chars)", extra={
                "task_id": task.id, "skill": skill_nome, "versao": skill.versao,
            })

            return {
                "skill": skill_nome,
                "instrucao": instrucao,
                "versao": skill.versao,
                **({"dados_contexto": dados_script} if dados_script else {}),
                "post_instruction": (
                    f"IMPORTANTE: Você carregou a skill '{skill_nome}'. "
                    f"Siga rigorosamente as instruções acima para garantir qualidade máxima."
                ),
            }

        # ── Context compact (7 seções estruturadas — estilo ClearTool) ──
        if tool_name == "context_compact":
            msgs = task.get_messages()
            keep = args.get("keep_last", 15)
            if len(msgs) <= keep:
                return {"already_compact": True, "message_count": len(msgs)}
            old = msgs[:-keep]
            recent = msgs[-keep:]
            # Sumarizar via LLM com template estruturado de 7 seções
            old_text = "\n".join(
                f"[{m.get('role','?')}]: {str(m.get('content',''))[:500]}"
                for m in old
            )
            _COMPACT_PROMPT = """Sumarize a conversa abaixo em um documento estruturado com EXATAMENTE estas 7 seções.
Seja conciso mas inclua caminhos de arquivos, números de linha e detalhes técnicos suficientes para retomar o trabalho.

## 1. Objetivo Principal
O que o usuário pediu e por quê.

## 2. Conceitos Técnicos
Stack, ferramentas, padrões e frameworks usados.

## 3. Arquivos e Código
Arquivos criados/modificados com caminhos exatos.

## 4. Problemas Resolvidos
Erros encontrados e como foram corrigidos.

## 5. Tarefas Pendentes
O que ainda falta fazer.

## 6. Trabalho Atual
Em que ponto a conversa parou.

## 7. Próximo Passo
O que deve ser feito a seguir.

--- CONVERSA ---
""" + old_text

            modelo = (
                coding_session.modelo_coding
                or agente.modelo_llm
                or ConfiguracaoService.obter_valor(db, "openrouter_modelo_padrao", "openai/gpt-4o")
            )
            try:
                resp = await LLMIntegrationService.processar_mensagem_com_llm(
                    db=db,
                    messages=[{
                        "role": "user",
                        "content": _COMPACT_PROMPT,
                    }],
                    modelo=modelo,
                    max_tokens=1500,
                )
                summary = resp.get("text") or resp.get("conteudo") or "Histórico anterior comprimido."
            except Exception:
                summary = f"[{len(old)} mensagens anteriores comprimidas — erro na sumarização]"

            new_messages = [
                {"role": "user", "content": f"[CONTEXTO COMPRIMIDO — {len(old)} msgs anteriores]\n\n{summary}"},
                {"role": "assistant", "content": "Entendido. Tenho todo o contexto necessário para continuar. Prosseguindo de onde paramos sem repetir trabalho já feito."},
            ] + recent
            task.messages = new_messages
            db.commit()
            return {
                "compressed": True,
                "removed_messages": len(old),
                "kept_messages": keep,
                "summary_chars": len(summary),
                "summary_preview": summary[:300] + "..." if len(summary) > 300 else summary,
            }

        # ── Task create (background sub-task) ─────────────────
        if tool_name == "task_create":
            titulo = args["title"]
            objective = args["objective"]
            new_task = CodingService.criar_tarefa(
                db,
                coding_session_id=coding_session.id,
                titulo=titulo,
                objetivo=objective,
            )

            async def _run_background():
                from database import SessionLocal
                bg_db = SessionLocal()
                try:
                    await CodingService.processar_mensagem(
                        db=bg_db,
                        coding_session_id=coding_session.id,
                        mensagem=objective,
                        task_id=new_task.id,
                    )
                except Exception as e:
                    fluxi_log.warning("coding", "tarefa", "Erro em sub-task", extra={"erro": str(e)})
                finally:
                    bg_db.close()

            asyncio.create_task(_run_background())
            return {
                "task_id": new_task.id,
                "titulo": titulo,
                "status": "running",
                "message": "Sub-tarefa iniciada em background. Use task_status para verificar progresso.",
            }

        # ── Agent run (sub-agent) ─────────────────────────────
        if tool_name == "agent_run":
            goal = args["goal"]
            context = args.get("context", "")
            max_iter = min(args.get("max_iterations", 15), 20)
            modelo = (
                coding_session.modelo_coding
                or agente.modelo_llm
                or ConfiguracaoService.obter_valor(db, "openrouter_modelo_padrao", "openai/gpt-4o")
            )
            # Coletar arquivos já criados nesta tarefa para dar contexto ao sub-agente
            _artifacts_ctx = ""
            _task_artifacts = task.artifacts or []
            if _task_artifacts:
                _art_list = [a.get("path", "") for a in _task_artifacts[-10:]]
                _artifacts_ctx = f"\nArquivos já criados nesta tarefa: {', '.join(_art_list)}"

            sub_system = f"""Você é um sub-agente focado em uma tarefa específica.
Seu trabalho é executar o objetivo abaixo com ALTA QUALIDADE e COMPLETUDE.

Objetivo: {goal}
{f'Contexto adicional: {context}' if context else ''}
Workspace: {coding_session.workspace_path}{_artifacts_ctx}

REGRAS:
- Execute o objetivo usando as ferramentas disponíveis
- Ao escrever código, seja COMPLETO — não use placeholders, não corte corners
- Inclua tratamento de erros, formatação adequada e boas práticas
- Ao finalizar, retorne um resumo DETALHADO do que foi feito
- Não peça confirmação — aja diretamente"""

            sub_msgs: List[Dict[str, Any]] = [{"role": "user", "content": goal}]
            # Tools para o sub-agente (sem sub-agents aninhados)
            from coding_agent.coding_tools import obter_coding_tools
            sub_tools = [
                t for t in obter_coding_tools()
                if t["function"]["name"] not in ("agent_run", "task_create", "context_compact")
            ]
            resultado_final = ""
            for sub_it in range(max_iter):
                sub_resp = await LLMIntegrationService.processar_mensagem_com_llm(
                    db=db,
                    messages=[{"role": "system", "content": sub_system}] + sub_msgs,
                    modelo=modelo,
                    max_tokens=8192,
                    tools=sub_tools,
                )
                sub_tc = sub_resp.get("tool_calls") or []
                sub_text = sub_resp.get("conteudo", "")
                sub_msgs.append({"role": "assistant", "content": sub_text, **({"tool_calls": sub_tc} if sub_tc else {})})
                if not sub_tc:
                    resultado_final = sub_text
                    break
                for stc in sub_tc:
                    s_name = stc.get("function", {}).get("name", "")
                    try:
                        import json as _json
                        s_args = _json.loads(stc.get("function", {}).get("arguments", "{}"))
                    except Exception:
                        s_args = {}
                    s_res = await CodingService._executar_tool(
                        db=db, coding_session=coding_session, task=task,
                        agente=agente, tool_name=s_name, args=s_args,
                        mcp_tools_map=mcp_tools_map,
                    )
                    sub_msgs.append({
                        "role": "tool",
                        "tool_call_id": stc.get("id", "sub"),
                        "content": _resultado_para_texto(s_res),
                    })
            return {
                "goal": goal,
                "result": resultado_final or "Sub-agente atingiu máximo de iterações",
                "iterations": sub_it + 1,
            }

        # ── Fluxi Meta — registrar sistemas criados ───────────
        if tool_name == "fluxi_listar_recursos":
            return await CodingService._fluxi_listar_recursos(db, args)

        if tool_name == "fluxi_criar_ferramenta":
            return await CodingService._fluxi_criar_ferramenta(db, args)

        if tool_name == "fluxi_atualizar_ferramenta":
            return await CodingService._fluxi_atualizar_ferramenta(db, args)

        if tool_name == "fluxi_criar_agente":
            return await CodingService._fluxi_criar_agente(db, args)

        if tool_name == "fluxi_criar_skill":
            return await CodingService._fluxi_criar_skill(db, args)

        if tool_name == "fluxi_conectar_mcp":
            return await CodingService._fluxi_conectar_mcp(db, args)

        # ── Browser ───────────────────────────────────────────
        if tool_name == "browser_navigate":
            bsvc = InternalBrowserService.obter_instancia(coding_session.agente_id)
            return await bsvc.navigate(url=args["url"])

        if tool_name == "browser_get_page":
            bsvc = InternalBrowserService.obter_instancia(coding_session.agente_id)
            return await bsvc.get_markdown()

        if tool_name == "browser_screenshot":
            bsvc = InternalBrowserService.obter_instancia(coding_session.agente_id)
            img_bytes = await bsvc.screenshot(full_page=args.get("full_page", False))
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return {
                "type": "image",
                "image_base64": b64,
                "mime_type": "image/png",
                "size_kb": round(len(img_bytes) / 1024, 1),
            }

        # ── MCP ───────────────────────────────────────────────
        if tool_name in mcp_tools_map:
            mcp_client_id = mcp_tools_map[tool_name]
            # Remove o prefixo mcp_{client_id}_ do nome da tool
            real_tool_name = tool_name.split("_", 2)[-1] if tool_name.count("_") >= 2 else tool_name
            resultado_mcp = await MCPService.executar_tool_mcp(
                db=db,
                mcp_client_id=mcp_client_id,
                tool_name=real_tool_name,
                arguments=args,
            )
            return resultado_mcp.get("resultado", resultado_mcp)

        # ── Entrega (send_file / send_screenshot) tratadas como side-effects ─
        # O resultado é retornado mas o envio real ocorre em _handle_delivery_side_effects
        if tool_name in ("send_file_whatsapp", "send_screenshot_whatsapp"):
            return {"pending_delivery": True, "tool": tool_name, "args": args}

        return {"error": f"Tool '{tool_name}' não reconhecida no coding agent"}

    # Timeout para envio de status WhatsApp — o send_message do neonize é
    # síncrono e pode bloquear 75s+ em condições de rede ruins.
    _WP_STATUS_TIMEOUT = 10.0  # segundos

    @staticmethod
    async def _enviar_status_whatsapp(
        db: Session,
        coding_session: CodingSession,
        task: CodingTask,
        mensagem: str,
    ) -> None:
        """Envia uma mensagem curta de status/feedback via WhatsApp se houver JID resolvido.

        O JID correto é cacheado em task._jid_destino_cache pelo processar_mensagem(),
        já resolvido com o Server correto (lid ou s.whatsapp.net) pelo mensagem_service.
        Sem JID cacheado, não tenta enviar — evita o problema de construir JID errado
        (ex: LID@s.whatsapp.net) que causava bloqueio de 75s sem entrega.
        """
        destinatario = getattr(task, '_jid_destino_cache', None)
        if not destinatario:
            return

        try:
            from sessao.sessao_service import gerenciador_sessoes
            from agente.agente_model import Agente as AgenteModel
            agente = db.query(AgenteModel).filter(
                AgenteModel.id == coding_session.agente_id
            ).first()
            if not agente:
                return

            cliente = gerenciador_sessoes.obter_cliente(agente.sessao_id)
            if not cliente:
                return

            # Executa envio em executor com TIMEOUT — o send_message do neonize
            # é síncrono e pode bloquear. Se não enviar em 10s, desiste.
            import asyncio
            _t_wp = time.time()
            try:
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: cliente.send_message(destinatario, message=mensagem),
                    ),
                    timeout=CodingService._WP_STATUS_TIMEOUT,
                )
                _ms_wp = int((time.time() - _t_wp) * 1000)
                fluxi_log.debug("coding", "whatsapp", f"Status WhatsApp enviado ({_ms_wp}ms)",
                    extra={"task_id": task.id, "tempo_ms": _ms_wp})
            except asyncio.TimeoutError:
                fluxi_log.warning("coding", "whatsapp",
                    f"Timeout {CodingService._WP_STATUS_TIMEOUT}s ao enviar status WhatsApp — ignorando",
                    extra={"task_id": task.id})
        except Exception as e:
            fluxi_log.warning("coding", "whatsapp", f"Erro ao enviar status WhatsApp: {e}",
                extra={"task_id": task.id, "erro": str(e)[:200]})

    # ── Side effects de entrega ─────────────────────────────────

    @staticmethod
    async def _handle_delivery_side_effects(
        db: Session,
        coding_session: CodingSession,
        task: CodingTask,
        tool_name: str,
        args: Dict[str, Any],
        resultado: Dict[str, Any],
    ) -> None:
        """
        Realiza o envio de arquivo/screenshot via WhatsApp.
        Chamado após o resultado ser adicionado ao histórico do LLM.
        """
        if not task.telefone_cliente:
            return

        if tool_name == "send_file_whatsapp":
            try:
                from internal_sandbox.file_service import FileService as FS
                from sessao.sessao_service import gerenciador_sessoes
                from agente.agente_model import Agente as AgenteModel
                agente = db.query(AgenteModel).filter(
                    AgenteModel.id == coding_session.agente_id
                ).first()
                if not agente:
                    return

                file_path = args.get("file_path", "")
                caption = args.get("caption", "")
                filename = args.get("filename") or os.path.basename(file_path)

                file_bytes = FS.download_file_bytes(file_path)
                cliente = gerenciador_sessoes.obter_cliente(agente.sessao_id)
                if cliente:
                    # Usa JID resolvido cacheado na task (correto para LID e s.whatsapp.net)
                    destinatario = getattr(task, '_jid_destino_cache', None)
                    if not destinatario:
                        fluxi_log.warning("coding", "whatsapp", "Sem JID cache para envio de arquivo — ignorando", extra={"task_id": task.id})
                        return
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: cliente.send_document(
                            destinatario,
                            file_bytes,
                            filename=filename,
                            caption=caption,
                        ),
                    )
            except Exception as e:
                fluxi_log.warning("coding", "whatsapp", "Erro ao enviar arquivo WhatsApp", extra={"erro": str(e)})

        elif tool_name == "send_screenshot_whatsapp":
            try:
                from sessao.sessao_service import gerenciador_sessoes
                from agente.agente_model import Agente as AgenteModel
                agente = db.query(AgenteModel).filter(
                    AgenteModel.id == coding_session.agente_id
                ).first()
                if not agente:
                    return

                bsvc = InternalBrowserService.obter_instancia(coding_session.agente_id)
                img_bytes = await bsvc.screenshot(
                    full_page=args.get("full_page", False)
                )
                caption = args.get("caption", "")
                cliente = gerenciador_sessoes.obter_cliente(agente.sessao_id)
                if cliente:
                    # Usa JID resolvido cacheado na task (correto para LID e s.whatsapp.net)
                    destinatario = getattr(task, '_jid_destino_cache', None)
                    if not destinatario:
                        fluxi_log.warning("coding", "whatsapp", "Sem JID cache para envio de screenshot — ignorando", extra={"task_id": task.id})
                        return
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: cliente.send_image(
                            destinatario,
                            img_bytes,
                            caption=caption,
                        ),
                    )
            except Exception as e:
                fluxi_log.warning("coding", "whatsapp", "Erro ao enviar screenshot WhatsApp", extra={"erro": str(e)})

    # ── Fluxi Meta — implementações ────────────────────────────

    @staticmethod
    async def _fluxi_listar_recursos(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """Lista ferramentas, agentes ou skills do Fluxi."""
        tipo = args.get("tipo", "ferramentas")

        if tipo == "ferramentas":
            from ferramenta.ferramenta_service import FerramentaService
            items = FerramentaService.listar_todas(db)
            return {
                "total": len(items),
                "ferramentas": [
                    {"id": f.id, "nome": f.nome, "descricao": f.descricao,
                     "tool_type": f.tool_type.value if f.tool_type else None,
                     "ativa": f.ativa}
                    for f in items
                ],
            }

        if tipo == "agentes":
            from agente.agente_service import AgenteService
            sessao_id = args.get("sessao_id")
            if sessao_id:
                items = AgenteService.listar_por_sessao(db, sessao_id)
            else:
                items = AgenteService.listar_todos(db)
            return {
                "total": len(items),
                "agentes": [
                    {"id": a.id, "codigo": a.codigo, "nome": a.nome,
                     "sessao_id": a.sessao_id, "ativo": a.ativo}
                    for a in items
                ],
            }

        if tipo == "skills":
            from skill.skill_service import SkillService
            items = SkillService.listar_todas(db)
            return {
                "total": len(items),
                "skills": [
                    {"id": s.id, "nome": s.nome, "descricao": s.descricao,
                     "categoria": s.categoria, "ativa": s.ativa}
                    for s in items
                ],
            }

        if tipo == "mcp_presets":
            from mcp_client.mcp_service import MCPService
            presets = MCPService.listar_presets_disponiveis()
            return {
                "total": len(presets),
                "presets": [
                    {"key": p["key"], "name": p["name"], "description": p["description"],
                     "transport_type": p["transport_type"],
                     "inputs_necessarios": [i["id"] for i in p.get("inputs", [])]}
                    for p in presets
                ],
            }

        return {"erro": f"Tipo '{tipo}' inválido. Use: ferramentas, agentes, skills, mcp_presets"}

    @staticmethod
    async def _fluxi_criar_ferramenta(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """Cria uma ferramenta CODE no Fluxi."""
        import json as _json
        from ferramenta.ferramenta_service import FerramentaService
        from ferramenta.ferramenta_schema import FerramentaCriar
        from ferramenta.ferramenta_model import ToolType, ToolScope, OutputDestination, ChannelType

        nome = args.get("nome", "").strip()
        if not nome:
            return {"erro": "Campo 'nome' obrigatório"}

        # Verifica se já existe
        existente = FerramentaService.obter_por_nome(db, nome)
        if existente:
            return {
                "aviso": f"Ferramenta '{nome}' já existe com ID {existente.id}",
                "id": existente.id,
                "nome": existente.nome,
                "ja_existia": True,
            }

        params_json = args.get("params_json", "{}")
        try:
            _json.loads(params_json)  # valida JSON
        except Exception:
            return {"erro": f"params_json inválido: {params_json}"}

        output_str = args.get("output", "LLM").upper()
        output_map = {"LLM": OutputDestination.LLM, "USER": OutputDestination.USER, "BOTH": OutputDestination.BOTH}
        output = output_map.get(output_str, OutputDestination.LLM)

        dados = FerramentaCriar(
            nome=nome,
            descricao=args.get("descricao", ""),
            tool_type=ToolType.CODE,
            tool_scope=ToolScope.PRINCIPAL,
            params=params_json,
            codigo_python=args.get("codigo_python", "resultado = {}"),
            substituir=False,
            output=output,
            channel=ChannelType.TEXT,
            ativa=True,
        )
        ferramenta = FerramentaService.criar(db, dados)
        return {
            "sucesso": True,
            "id": ferramenta.id,
            "nome": ferramenta.nome,
            "mensagem": f"Ferramenta '{ferramenta.nome}' criada com ID {ferramenta.id}",
        }

    @staticmethod
    async def _fluxi_atualizar_ferramenta(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """Atualiza código ou descrição de ferramenta existente."""
        import json as _json
        from ferramenta.ferramenta_service import FerramentaService
        from ferramenta.ferramenta_schema import FerramentaAtualizar

        fid = args.get("ferramenta_id")
        if not fid:
            return {"erro": "Campo 'ferramenta_id' obrigatório"}

        update_data: Dict[str, Any] = {}
        if "codigo_python" in args:
            update_data["codigo_python"] = args["codigo_python"]
        if "descricao" in args:
            update_data["descricao"] = args["descricao"]
        if "params_json" in args:
            try:
                _json.loads(args["params_json"])
                update_data["params"] = args["params_json"]
            except Exception:
                return {"erro": "params_json inválido"}

        if not update_data:
            return {"erro": "Nenhum campo para atualizar. Forneça codigo_python, descricao ou params_json"}

        ferramenta = FerramentaService.atualizar(db, fid, FerramentaAtualizar(**update_data))
        if not ferramenta:
            return {"erro": f"Ferramenta ID {fid} não encontrada"}

        return {
            "sucesso": True,
            "id": ferramenta.id,
            "nome": ferramenta.nome,
            "mensagem": f"Ferramenta '{ferramenta.nome}' atualizada",
        }

    @staticmethod
    async def _fluxi_criar_agente(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """Cria um agente personalizado no Fluxi e associa ferramentas."""
        from agente.agente_service import AgenteService
        from agente.agente_schema import AgenteCriar

        sessao_id = args.get("sessao_id")
        codigo = args.get("codigo", "").strip()
        nome = args.get("nome", "").strip()

        if not all([sessao_id, codigo, nome]):
            return {"erro": "Campos obrigatórios: sessao_id, codigo, nome"}

        # Verifica se já existe agente com esse código na sessão
        existente = AgenteService.obter_por_codigo(db, sessao_id, codigo)
        if existente:
            return {
                "aviso": f"Agente com código '{codigo}' já existe na sessão (ID: {existente.id})",
                "id": existente.id,
                "codigo": existente.codigo,
                "nome": existente.nome,
                "ja_existia": True,
            }

        papel = args.get("papel", f"Você é o agente {nome}")
        objetivo = args.get("objetivo", f"Auxiliar o usuário com tarefas de {nome.lower()}")
        politicas = args.get("politicas", "Seja direto, objetivo e útil")
        tarefa = args.get("tarefa", "Receba solicitações e execute as ações necessárias")
        restricoes = args.get("restricoes", "Não execute ações destrutivas sem confirmação")

        dados = AgenteCriar(
            sessao_id=sessao_id,
            codigo=codigo,
            nome=nome,
            descricao=args.get("descricao", f"Agente {nome}"),
            agente_papel=papel,
            agente_objetivo=objetivo,
            agente_politicas=politicas,
            agente_tarefa=tarefa,
            agente_objetivo_explicito=args.get("objetivo_explicito", "Solicitação atendida com sucesso"),
            agente_publico=args.get("publico", "Usuário final via WhatsApp"),
            agente_restricoes=restricoes,
            ativo=True,
        )
        agente = AgenteService.criar(db, dados)

        # Associa ferramentas se fornecidas
        ferramentas_ids = args.get("ferramentas_ids", [])
        if ferramentas_ids:
            try:
                AgenteService.atualizar_ferramentas(db, agente.id, ferramentas_ids)
            except Exception as e:
                return {
                    "sucesso": True,
                    "id": agente.id,
                    "codigo": agente.codigo,
                    "nome": agente.nome,
                    "aviso": f"Agente criado mas erro ao associar ferramentas: {e}",
                    "mensagem": f"Agente '{agente.nome}' (#{codigo}) criado com ID {agente.id}",
                }

        return {
            "sucesso": True,
            "id": agente.id,
            "codigo": agente.codigo,
            "nome": agente.nome,
            "sessao_id": agente.sessao_id,
            "ferramentas_associadas": len(ferramentas_ids),
            "mensagem": (
                f"Agente '{agente.nome}' criado!\n"
                f"  • ID: {agente.id}\n"
                f"  • Prefixo: #{codigo}\n"
                f"  • Ferramentas: {len(ferramentas_ids)} associada(s)\n"
                f"  • Ative pelo WhatsApp com: #{codigo} <mensagem>"
            ),
        }

    @staticmethod
    async def _fluxi_criar_skill(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """Cria uma skill no Fluxi e opcionalmente associa a um agente."""
        from skill.skill_service import SkillService
        from skill.skill_schema import SkillCriar

        nome = args.get("nome", "").strip()
        if not nome:
            return {"erro": "Campo 'nome' obrigatório"}

        existente = SkillService.obter_por_nome(db, nome)
        if existente:
            return {
                "aviso": f"Skill '{nome}' já existe com ID {existente.id}",
                "id": existente.id,
                "ja_existia": True,
            }

        dados = SkillCriar(
            nome=nome,
            descricao=args.get("descricao", f"Skill {nome}")[:250],
            instrucao_completa=args.get("instrucao_completa", ""),
            categoria=args.get("categoria", "geral"),
            icone=args.get("icone", "🔧"),
            ativa=True,
        )
        skill = SkillService.criar(db, dados)

        # Associa ao agente se fornecido
        agente_id = args.get("agente_id")
        if agente_id:
            try:
                skills_atuais = [s.id for s in SkillService.listar_skills_agente(db, agente_id)]
                if skill.id not in skills_atuais:
                    skills_atuais.append(skill.id)
                SkillService.atualizar_skills_agente(db, agente_id, skills_atuais)
            except Exception as e:
                return {
                    "sucesso": True,
                    "id": skill.id,
                    "nome": skill.nome,
                    "aviso": f"Skill criada mas erro ao associar ao agente: {e}",
                    "mensagem": f"Skill '{skill.nome}' criada com ID {skill.id}",
                }

        return {
            "sucesso": True,
            "id": skill.id,
            "nome": skill.nome,
            "mensagem": (
                f"Skill '{skill.nome}' criada com ID {skill.id}"
                + (f" e associada ao agente {agente_id}" if agente_id else "")
            ),
        }

    @staticmethod
    async def _fluxi_conectar_mcp(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """Conecta um servidor MCP a um agente via service layer."""
        from mcp_client.mcp_service import MCPService
        from mcp_client.mcp_schema import MCPClientCriar, MCPPresetAplicarRequest, MCPOneClickRequest

        agente_id = args.get("agente_id")
        modo = args.get("modo", "url")

        if not agente_id:
            return {"erro": "Campo 'agente_id' obrigatório"}

        try:
            if modo == "preset":
                preset_key = args.get("preset_key")
                if not preset_key:
                    return {"erro": "Campo 'preset_key' obrigatório para modo=preset"}
                payload = MCPPresetAplicarRequest(
                    preset_key=preset_key,
                    agente_id=agente_id,
                    nome=args.get("nome"),
                    inputs=args.get("preset_inputs"),
                )
                db_mcp = MCPService.aplicar_preset(db, payload)

            elif modo == "url":
                url = args.get("url")
                if not url:
                    return {"erro": "Campo 'url' obrigatório para modo=url"}
                payload = MCPClientCriar(
                    agente_id=agente_id,
                    nome=args.get("nome", "Servidor MCP"),
                    transport_type=args.get("transport_type", "streamable-http"),
                    url=url,
                    headers=args.get("headers"),
                    ativo=True,
                )
                db_mcp = MCPService.criar(db, payload)

            elif modo == "stdio":
                command = args.get("command")
                if not command:
                    return {"erro": "Campo 'command' obrigatório para modo=stdio"}
                payload = MCPClientCriar(
                    agente_id=agente_id,
                    nome=args.get("nome", "Servidor MCP Local"),
                    transport_type="stdio",
                    command=command,
                    args=args.get("args", []),
                    env_vars=args.get("env_vars"),
                    ativo=True,
                )
                db_mcp = MCPService.criar(db, payload)

            elif modo == "one_click":
                json_config = args.get("json_config")
                if not json_config:
                    return {"erro": "Campo 'json_config' obrigatório para modo=one_click"}
                payload = MCPOneClickRequest(
                    agente_id=agente_id,
                    json_config=json_config,
                    nome=args.get("nome"),
                )
                db_mcp = MCPService.aplicar_one_click(db, payload)

            else:
                return {"erro": f"Modo '{modo}' inválido. Use: preset, url, stdio, one_click"}

            # Conectar e sincronizar
            resultado_conexao = await MCPService.conectar_cliente(db, db_mcp.id)
            db.refresh(db_mcp)
            tools = MCPService.listar_tools_ativas(db, db_mcp.id)

            return {
                "sucesso": True,
                "id": db_mcp.id,
                "nome": db_mcp.nome,
                "conectado": db_mcp.conectado,
                "total_tools": len(tools),
                "tools": [t.name for t in tools[:10]],
                "mensagem": (
                    f"Servidor MCP '{db_mcp.nome}' conectado com {len(tools)} tools disponíveis"
                    + (f"\nErro parcial: {db_mcp.ultimo_erro}" if db_mcp.ultimo_erro else "")
                ),
            }

        except ValueError as e:
            return {"erro": str(e)}
        except Exception as e:
            return {"erro": f"Erro ao conectar MCP: {str(e)}"}

    # ── Criação de agente de coding padrão ──────────────────────

    @staticmethod
    def criar_agente_coding_padrao(db: Session, sessao_id: int) -> tuple:
        """
        Cria um Agente com is_coding_agent=True e sua CodingSession vinculada.
        Retorna (agente, coding_session).
        """
        from agente.agente_service import AgenteService

        # Verifica se já existe um agente de coding para esta sessão
        existing = (
            db.query(Agente)
            .filter(
                Agente.sessao_id == sessao_id,
                Agente.is_coding_agent == True,
                Agente.ativo == True,
            )
            .first()
        )
        if existing:
            cs = CodingService.obter_sessao_por_agente(db, existing.id)
            return existing, cs

        # Cria o agente
        from agente.agente_schema import AgenteCriar
        agente_dados = AgenteCriar(
            sessao_id=sessao_id,
            codigo="cod",
            nome="Coding Agent",
            descricao="Agente autônomo de coding, devops e automação",
            agente_papel="Especialista em programação e automação",
            agente_objetivo="Executar tarefas de coding de forma autônoma e entregar os resultados",
            agente_politicas="Use shell para tudo. Documente o progresso. Entregue artefatos.",
            agente_tarefa="Receba a solicitação, planeje, execute passo a passo e entregue",
            agente_objetivo_explicito="Tarefa concluída com artefatos entregues ao usuário",
            agente_publico="Desenvolvedor",
            agente_restricoes="Não execute operações destrutivas sem confirmar",
        )

        agente = db.query(Agente).filter(
            Agente.sessao_id == sessao_id,
            Agente.codigo == "cod",
        ).first()

        if not agente:
            agente = Agente(
                sessao_id=sessao_id,
                codigo="cod",
                nome="Coding Agent",
                descricao="Agente autônomo de coding, devops e automação",
                agente_papel="Especialista em programação e automação",
                agente_objetivo="Executar tarefas de coding de forma autônoma e entregar os resultados",
                agente_politicas="Use shell para tudo. Documente o progresso. Entregue artefatos.",
                agente_tarefa="Receba a solicitação, planeje, execute passo a passo e entregue",
                agente_objetivo_explicito="Tarefa concluída com artefatos entregues ao usuário",
                agente_publico="Desenvolvedor",
                agente_restricoes="Não execute operações destrutivas sem confirmar",
                is_coding_agent=True,
                internal_sandbox_ativo=True,
                ativo=True,
            )
            db.add(agente)
            db.commit()
            db.refresh(agente)

        # Cria CodingSession
        cs = CodingService.criar_sessao(
            db,
            CodingSessionCriar(agente_id=agente.id),
        )
        return agente, cs


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

async def _stream_shell_output(task_id: int, session_id: str) -> None:
    """
    Background coroutine: subscreve no output de uma shell session e encaminha
    cada chunk para a task stream queue como eventos 'shell_chunk'.
    Termina quando a sessão encerrar ou a task queue for removida.
    """
    import asyncio
    from coding_agent.coding_stream import emit_shell_chunk, _queues
    from internal_sandbox.shell_service import ShellService

    # Aguarda um tick para garantir que a sessão já foi registrada
    await asyncio.sleep(0.05)

    session = ShellService.get_session(session_id)
    if not session:
        return

    queue = session.subscribe()
    terminal = {"done", "error", "killed"}
    try:
        while True:
            # Para se a task queue foi removida (tarefa encerrada)
            if task_id not in _queues:
                break
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=5.0)
                await emit_shell_chunk(task_id, session_id, chunk)
            except asyncio.TimeoutError:
                if session.status in terminal:
                    break
    finally:
        session.unsubscribe(queue)


def _resultado_para_texto(resultado: Any) -> str:
    """Converte resultado de tool para string para o histórico LLM."""
    import json

    if resultado is None:
        return "(sem resultado)"
    if isinstance(resultado, str):
        return resultado
    if isinstance(resultado, dict):
        # Imagens: retorna descrição em vez da base64
        if resultado.get("type") == "image":
            return f"[Screenshot capturado — {resultado.get('size_kb', '?')} KB]"
        # Pending delivery
        if resultado.get("pending_delivery"):
            return f"[Enviando {resultado.get('tool', 'arquivo')} ao usuário...]"
        # Trunca outputs muito grandes (ex: listagens enormes)
        try:
            text = json.dumps(resultado, ensure_ascii=False, indent=2)
            if len(text) > 8000:
                text = text[:8000] + "\n... [truncado]"
            return text
        except Exception:
            return str(resultado)[:8000]
    return str(resultado)[:8000]
