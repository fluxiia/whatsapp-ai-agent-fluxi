"""
Serviço do agente LLM com integração OpenRouter.
"""
import asyncio
import logging
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import httpx
import json
import base64
import time
from datetime import datetime

logger = logging.getLogger(__name__)
from log.log_service import fluxi_log
from config.config_service import ConfiguracaoService
from agente.agente_model import Agente, agente_ferramenta
from agente.agente_schema import AgenteCriar, AgenteAtualizar
from ferramenta.ferramenta_model import Ferramenta
from ferramenta.ferramenta_service import FerramentaService
from llm_providers.llm_integration_service import LLMIntegrationService


class AgenteService:
    """Serviço para gerenciar agentes e processar mensagens com LLM."""

    @staticmethod
    def listar_todos(db: Session) -> List[Agente]:
        """Lista todos os agentes."""
        return db.query(Agente).all()

    @staticmethod
    def listar_por_sessao(db: Session, sessao_id: int) -> List[Agente]:
        """Lista agentes de uma sessão."""
        return db.query(Agente).filter(Agente.sessao_id == sessao_id).order_by(Agente.codigo).all()

    @staticmethod
    def listar_por_sessao_ativos(db: Session, sessao_id: int) -> List[Agente]:
        """Lista agentes ativos de uma sessão."""
        return db.query(Agente).filter(
            Agente.sessao_id == sessao_id,
            Agente.ativo == True
        ).order_by(Agente.codigo).all()

    @staticmethod
    def obter_por_id(db: Session, agente_id: int) -> Optional[Agente]:
        """Obtém um agente pelo ID."""
        return db.query(Agente).filter(Agente.id == agente_id).first()

    @staticmethod
    def obter_por_codigo(db: Session, sessao_id: int, codigo: str) -> Optional[Agente]:
        """Obtém um agente pelo código dentro de uma sessão."""
        return db.query(Agente).filter(
            Agente.sessao_id == sessao_id,
            Agente.codigo == codigo
        ).first()

    @staticmethod
    def criar(db: Session, agente: AgenteCriar) -> Agente:
        """Cria um novo agente."""
        # Verificar se já existe agente com mesmo código na sessão
        existe = AgenteService.obter_por_codigo(db, agente.sessao_id, agente.codigo)
        if existe:
            raise ValueError(f"Já existe um agente com o código '{agente.codigo}' nesta sessão")
        
        db_agente = Agente(**agente.model_dump())
        db.add(db_agente)
        db.commit()
        db.refresh(db_agente)
        return db_agente

    @staticmethod
    def atualizar(db: Session, agente_id: int, agente: AgenteAtualizar) -> Optional[Agente]:
        """Atualiza um agente existente."""
        db_agente = AgenteService.obter_por_id(db, agente_id)
        if not db_agente:
            return None

        update_data = agente.model_dump(exclude_unset=True)
        
        # Verificar se está mudando o código e se já existe outro com esse código
        if "codigo" in update_data and update_data["codigo"] != db_agente.codigo:
            existe = AgenteService.obter_por_codigo(db, db_agente.sessao_id, update_data["codigo"])
            if existe:
                raise ValueError(f"Já existe um agente com o código '{update_data['codigo']}' nesta sessão")
        
        for campo, valor in update_data.items():
            setattr(db_agente, campo, valor)

        db.commit()
        db.refresh(db_agente)
        return db_agente

    @staticmethod
    def deletar(db: Session, agente_id: int) -> bool:
        """Deleta um agente."""
        db_agente = AgenteService.obter_por_id(db, agente_id)
        if not db_agente:
            return False

        db.delete(db_agente)
        db.commit()
        return True

    @staticmethod
    def atualizar_ferramentas(db: Session, agente_id: int, ferramentas_ids: List[int]):
        """
        Atualiza as ferramentas de um agente.
        Limite configurável via 'agente_max_ferramentas'.
        """
        max_ferramentas = ConfiguracaoService.obter_valor(db, "agente_max_ferramentas", 20)
        if len(ferramentas_ids) > max_ferramentas:
            raise ValueError(f"Um agente pode ter no máximo {max_ferramentas} ferramentas ativas")
        
        db_agente = AgenteService.obter_por_id(db, agente_id)
        if not db_agente:
            raise ValueError("Agente não encontrado")
        
        # Remover todas as associações existentes
        db.execute(
            agente_ferramenta.delete().where(agente_ferramenta.c.agente_id == agente_id)
        )
        
        # Adicionar novas associações
        for ferramenta_id in ferramentas_ids:
            # Verificar se a ferramenta existe
            ferramenta = db.query(Ferramenta).filter(Ferramenta.id == ferramenta_id).first()
            if not ferramenta:
                raise ValueError(f"Ferramenta com ID {ferramenta_id} não encontrada")
            
            # Inserir associação
            db.execute(
                agente_ferramenta.insert().values(
                    agente_id=agente_id,
                    ferramenta_id=ferramenta_id,
                    ativa=True
                )
            )
        
        db.commit()

    @staticmethod
    def listar_ferramentas(db: Session, agente_id: int) -> List[Ferramenta]:
        """Lista as ferramentas ativas de um agente."""
        db_agente = AgenteService.obter_por_id(db, agente_id)
        if not db_agente:
            return []
        
        # Buscar ferramentas através da tabela de associação
        ferramentas = db.query(Ferramenta).join(
            agente_ferramenta,
            Ferramenta.id == agente_ferramenta.c.ferramenta_id
        ).filter(
            agente_ferramenta.c.agente_id == agente_id,
            agente_ferramenta.c.ativa == True,
            Ferramenta.ativa == True
        ).all()
        
        return ferramentas

    @staticmethod
    def criar_agente_padrao(db: Session, sessao_id: int) -> Agente:
        """
        Cria um agente padrão para uma sessão.
        Útil ao criar uma nova sessão.
        """
        from config.config_service import ConfiguracaoService
        
        agente_data = AgenteCriar(
            sessao_id=sessao_id,
            codigo="01",
            nome="Fluxi",
            descricao="Super assistente pessoal multidisciplinar",
            agente_papel=ConfiguracaoService.obter_valor(
                db, "agente_papel_padrao",
                "Você é Fluxi, um assistente pessoal altamente capaz e inteligente. Você combina o conhecimento de um especialista multidisciplinar com a empatia de um consultor de confiança. Fala em português brasileiro de forma natural e clara, adaptando o tom ao perfil de quem conversa — simples quando necessário, técnico quando exigido."
            ),
            agente_objetivo=ConfiguracaoService.obter_valor(
                db, "agente_objetivo_padrao",
                "Ser o assistente mais útil e completo do dia a dia. Resolver dúvidas, executar tarefas, pesquisar informações, criar conteúdo, analisar dados, calcular, planejar e apoiar decisões. O objetivo é economizar o tempo do usuário e entregar resultados de alta qualidade em cada interação."
            ),
            agente_politicas=ConfiguracaoService.obter_valor(
                db, "agente_politicas_padrao",
                "Use português brasileiro natural e fluido. Adapte o tom: descontraído com quem usa linguagem informal, preciso com quem demonstra expertise. Respostas objetivas e sem floreios. Use listas e negrito quando organizar o conteúdo melhorar a leitura. Nunca use linguagem excessivamente formal. Limite emojis a situações onde genuinamente ajudam a comunicação."
            ),
            agente_tarefa=ConfiguracaoService.obter_valor(
                db, "agente_tarefa_padrao",
                "1. Leia a mensagem e identifique o que o usuário realmente precisa (intenção + contexto). 2. Se a tarefa for clara, execute diretamente sem perguntas desnecessárias. 3. Se houver ambiguidade, faça UMA pergunta precisa antes de prosseguir. 4. Para tarefas complexas, organize a resposta em etapas ou listas. 5. Ao finalizar, verifique se o resultado atende ao pedido e ofereça um próximo passo relevante quando fizer sentido."
            ),
            agente_objetivo_explicito=ConfiguracaoService.obter_valor(
                db, "agente_objetivo_explicito_padrao",
                "Entregar uma resposta completa, acionável e direta ao ponto. Se o pedido envolver criação de texto, código, análise ou cálculo, apresente o resultado pronto para uso. Se envolver decisão, apresente as opções com prós e contras claros."
            ),
            agente_publico=ConfiguracaoService.obter_valor(
                db, "agente_publico_padrao",
                "Profissionais e empreendedores brasileiros que buscam produtividade, clareza e execução rápida no dia a dia."
            ),
            agente_restricoes=ConfiguracaoService.obter_valor(
                db, "agente_restricoes_padrao",
                "Nunca invente fatos, dados ou referências — se não souber, diga claramente e sugira onde encontrar. Não prometa coisas fora do seu controle. Não gere conteúdo ofensivo, discriminatório ou que viole privacidade. Se o pedido for ambíguo ou potencialmente prejudicial, peça esclarecimento antes de responder."
            ),
            ativo=True
        )
        
        agente = AgenteService.criar(db, agente_data)
        
        # Associar ferramentas padrão (configurável)
        nomes_ferramentas_padrao = ConfiguracaoService.obter_valor(
            db, "agente_ferramentas_padrao", ["obter_data_hora_atual", "calcular", "buscar_internet", "previsao_tempo", "cotacao_moeda", "buscar_cep", "buscar_wikipedia", "gerar_senha"]
        )
        ferramentas_padrao = db.query(Ferramenta).filter(
            Ferramenta.nome.in_(nomes_ferramentas_padrao)
        ).all()
        
        if ferramentas_padrao:
            ferramentas_ids = [f.id for f in ferramentas_padrao]
            AgenteService.atualizar_ferramentas(db, agente.id, ferramentas_ids)
        
        return agente

    @staticmethod
    def construir_system_prompt(agente: Agente, skills: Optional[List] = None) -> str:
        """
        Constrói o system prompt baseado na configuração do agente.
        Segue o padrão definido em agente.md
        """
        # Instrução fixa para priorizar tools
        instrucao_tools = """
IMPORTANTE - USO DE FERRAMENTAS:
Você tem acesso a ferramentas (tools) que podem executar ações reais.
SEMPRE verifique se existe uma ferramenta disponível para resolver a tarefa do usuário.
Se existir uma ferramenta adequada, USE-A OBRIGATORIAMENTE antes de responder.
Não tente responder com conhecimento próprio se houver uma tool que pode buscar dados reais.
Priorize SEMPRE o uso de tools para garantir respostas precisas e atualizadas.
"""

        prompt = (
            f"Você é: {agente.agente_papel}.\n"
            f"Objetivo: {agente.agente_objetivo}.\n"
            f"Políticas: {agente.agente_politicas}.\n"
            f"Tarefa: {agente.agente_tarefa}.\n"
            f"Objetivo explícito: {agente.agente_objetivo_explicito}.\n"
            f"Público/usuário-alvo: {agente.agente_publico}.\n"
            f"Restrições e políticas: {agente.agente_restricoes}.\n"
            f"{instrucao_tools}"
        )

        if skills:
            prompt += "\n\n" + AgenteService._construir_secao_skills(skills)

        return prompt

    @staticmethod
    def _construir_secao_skills(skills: List) -> str:
        """Constrói a seção de skills para o system prompt (só metadados — progressive disclosure)."""
        familias: Dict[str, List] = {}
        for skill in skills:
            familia = skill.nome.split("-")[0] if "-" in skill.nome else skill.nome
            familias.setdefault(familia, []).append(skill)

        linhas = [
            "═══════════════════════════════════════",
            "SKILLS DISPONÍVEIS",
            "═══════════════════════════════════════",
            "Você possui skills especializadas. Para acessar as instruções completas",
            "de uma skill, use a ferramenta `invocar_skill` com o nome exato.",
            "",
            "Skills disponíveis:"
        ]

        for familia, membros in familias.items():
            pai = next((m for m in membros if m.nome == familia), membros[0])
            if len(membros) == 1 and membros[0].nome == familia:
                linhas.append(f"  {pai.icone or '🔧'} [{pai.nome}] — {pai.descricao}")
            else:
                linhas.append(f"  {pai.icone or '🔧'} [{familia}] — {pai.descricao} (possui sub-skills)")
                for sub in membros:
                    if sub.nome != familia:
                        linhas.append(f"      └─ [{sub.nome}] — {sub.descricao}")

        linhas += [
            "",
            "REGRA: Quando o usuário solicitar algo que se encaixa em uma skill,",
            "invoque-a ANTES de responder para receber as instruções completas.",
            "Use `invocar_skill` com o nome exato (ex: skill_nome: \"vendas-abertura\").",
            "═══════════════════════════════════════"
        ]
        return "\n".join(linhas)

    @staticmethod
    def _definir_tool_invocar_skill() -> Dict[str, Any]:
        """Retorna a definição OpenAI da meta-tool invocar_skill."""
        return {
            "type": "function",
            "function": {
                "name": "invocar_skill",
                "description": (
                    "Acessa as instruções completas de uma skill disponível para este agente. "
                    "Use quando precisar seguir um fluxo específico ou especialização definida numa skill. "
                    "Depois de receber as instruções, SIGA-AS à risca."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_nome": {
                            "type": "string",
                            "description": "Nome exato da skill a invocar (conforme listado no system prompt)"
                        },
                        "argumentos": {
                            "type": "object",
                            "description": "Parâmetros opcionais aceitos pela skill",
                            "additionalProperties": True
                        }
                    },
                    "required": ["skill_nome"]
                }
            }
        }

    @staticmethod
    async def _executar_invocar_skill(
        db: Session,
        agente: Agente,
        args: Dict[str, Any],
        tools: list,
        messages: list
    ) -> Dict[str, Any]:
        """Executa a tool invocar_skill: busca skill, roda script, injeta ferramentas extras."""
        from skill.skill_service import SkillService
        from ferramenta.ferramenta_service import FerramentaService

        skill_nome = args.get("skill_nome", "").strip()
        argumentos = args.get("argumentos") or {}

        skill = SkillService.obter_por_nome(db, skill_nome)
        if not skill or not skill.ativa:
            return {
                "resultado": {"erro": f"Skill '{skill_nome}' não encontrada ou inativa"},
                "output": "llm"
            }

        skills_agente = SkillService.listar_skills_agente(db, agente.id)
        nomes_permitidos = {s.nome for s in skills_agente}
        if skill_nome not in nomes_permitidos:
            return {
                "resultado": {"erro": f"Skill '{skill_nome}' não está associada a este agente"},
                "output": "llm"
            }

        dados_script = SkillService.executar_script(skill, argumentos)

        ferramentas_extras = SkillService.obter_ferramentas_extras_da_skill(db, skill)
        nomes_tools_atuais = {
            t["function"]["name"] for t in (tools or []) if t.get("function")
        }
        for ferramenta_extra in ferramentas_extras:
            if ferramenta_extra.nome not in nomes_tools_atuais:
                tool_openai = FerramentaService.converter_para_openai_format(ferramenta_extra)
                if tool_openai:
                    tools.append(tool_openai)
                    logger.debug("[SKILL] Ferramenta extra '%s' injetada para skill '%s'",
                                 ferramenta_extra.nome, skill_nome)

        instrucao = skill.instrucao_completa
        if dados_script:
            for chave, valor in dados_script.items():
                instrucao = instrucao.replace(f"{{{chave}}}", str(valor))

        retorno: Dict[str, Any] = {
            "skill": skill_nome,
            "instrucao": instrucao,
            "versao": skill.versao,
        }
        if dados_script:
            retorno["dados_contexto"] = dados_script

        return {
            "resultado": retorno,
            "output": "llm",
            "post_instruction": (
                f"IMPORTANTE: Você invocou a skill '{skill_nome}'. "
                f"Siga rigorosamente as instruções acima. "
                f"Não desvie do fluxo definido pela skill."
            )
        }

    @staticmethod
    def _trim_messages_sandbox(messages: List[Dict], keep_recent: int = 2, max_old_chars: int = 350) -> List[Dict]:
        """
        Antes de cada chamada ao LLM no modo sandbox, trunca resultados antigos de tools
        para evitar estouro de contexto com modelos locais.
        Mantém as `keep_recent` tool-results mais recentes completas;
        as anteriores são reduzidas a `max_old_chars` chars.
        """
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        to_truncate = set(tool_indices[:-keep_recent]) if len(tool_indices) > keep_recent else set()
        if not to_truncate:
            return messages
        result = []
        for i, m in enumerate(messages):
            if i in to_truncate:
                content = m.get("content", "")
                if len(content) > max_old_chars:
                    m = {**m, "content": content[:max_old_chars] + "...[resumido]"}
            result.append(m)
        return result

    @staticmethod
    def _prompt_sandbox() -> str:
        """Prompt suplementar injetado quando o Sandbox Interno está ativo."""
        return """

═══════════════════════════════════════════════════
🚀 MODO AGENTE AUTÔNOMO — SANDBOX INTERNO ATIVO
═══════════════════════════════════════════════════

Você agora é um AGENTE SUPER AUTÔNOMO com poderes expandidos. O Sandbox Interno está ativo e pronto para uso. Isso significa que você tem acesso a um ambiente completo e isolado para executar ações reais no mundo digital.

── SUAS NOVAS CAPACIDADES ──────────────────────

1. 🌐 NAVEGADOR WEB COMPLETO (Browser)
   - Navegue por qualquer site da internet em tempo real
   - Faça pesquisas, acesse APIs, colete dados de páginas web
   - Preencha formulários, faça login em serviços, interaja com aplicações web
   - Tire screenshots de páginas para análise visual
   - Faça download de arquivos da internet
   - Use para verificar informações, comparar preços, buscar referências

2. 💻 TERMINAL / SHELL COM PYTHON
   - Execute comandos no terminal Linux (bash)
   - Rode scripts Python completos com acesso a pip
   - Instale pacotes e bibliotecas conforme necessário (pip install)
   - Processe dados, faça cálculos complexos, gere relatórios
   - Execute operações de rede (curl, wget, etc.)
   - Compile e execute código em tempo real

3. 📁 GERENCIADOR DE ARQUIVOS
   - Crie, leia, edite e organize arquivos e diretórios
   - Salve resultados de pesquisas, relatórios, dados processados
   - Gerencie o workspace de forma organizada
   - Transfira arquivos entre operações

4. 📄 CONVERSÃO DE DOCUMENTOS (Markitdown)
   - Converta documentos para Markdown para análise
   - Extraia texto de PDFs, DOCXs, planilhas e apresentações
   - Processe e analise o conteúdo extraído

── DIRETRIZES DE AUTONOMIA ─────────────────────

• SEJA PROATIVO: Não apenas responda — antecipe necessidades. Se o usuário pede algo que requer pesquisa, pesquise. Se requer código, escreva e execute.

• AÇÃO PRIMEIRO, PERMISSÃO DEPOIS: Quando a intenção do usuário for clara, EXECUTE a ação diretamente. Não pergunte "Você quer que eu faça X?" — simplesmente faça X e apresente o resultado.

• RESILIÊNCIA A ERROS E TIMEOUTS: Se uma ferramenta falhar ou der timeout, NÃO desista. Tente:
  1. Dividir a tarefa em partes menores (ex: em vez de um script longo, execute em etapas)
  2. Se um comando der timeout, tente uma versão mais simples ou direta
  3. Informar o usuário apenas se TODAS as alternativas falharem, explicando o que tentou

• OTIMIZAÇÃO DE PERFORMANCE: Prefira abordagens rápidas:
  - Divida scripts Python longos em execuções menores
  - Use o browser para navegação, pesquisas e interação com sites

• CAPTCHA / VERIFICAÇÃO HUMANA — FLUXO OBRIGATÓRIO:
  Quando sandbox_browser_navigate retornar captcha_detected=true, OU ao detectar qualquer bloqueio:
  1. Use sandbox_browser_detect_captcha para confirmar o tipo
  2. Informe o usuário: "Encontrei um CAPTCHA. Por favor abra: [vnc_url] no seu browser, resolva o CAPTCHA e me avise quando terminar."
  3. Use sandbox_browser_wait_user com seconds=60 para aguardar
  4. Após o wait, continue normalmente (navegue, extraia conteúdo, etc.)
  IMPORTANTE: O VNC mostra o Chrome em tempo real — o usuário resolve o CAPTCHA visualmente e você continua.

• NAVEGAÇÃO NO BROWSER — FLUXO CORRETO:
  NUNCA use sandbox_browser_get_html para ler páginas (HTML cru = centenas de tokens inúteis).
  Use sempre este fluxo:
  1. sandbox_browser_navigate → abre a página
  2. sandbox_browser_get_page_state → lê conteúdo limpo + elementos [N] numerados
  3. sandbox_browser_click_index(N) → clica em elemento pela posição (sem precisar de CSS selector)
  4. sandbox_browser_fill → preenche inputs com texto
  Exemplo de busca no Google:
    navigate("https://google.com") →
    get_page_state() → encontra [0]<searchbox> Pesquisa →
    fill(text="consulta", selector="input[name=q]") →
    click_index(1) → clica no botão Pesquisar →
    get_page_state() → lê resultados
  Para artigos/conteúdo: use sandbox_browser_get_markdown (usa Readability.js).
  Para screenshots: use enviar_screenshot_whatsapp.

• ENCADEAMENTO DE FERRAMENTAS: Combine múltiplas ferramentas para resolver tarefas complexas. Exemplos:
  - Pesquisar na web → Processar dados com Python → Salvar resultado em arquivo
  - Baixar documento → Converter para texto → Analisar e resumir
  - Acessar API via browser → Extrair dados → Gerar relatório com gráficos

• QUALIDADE DE ENTREGA: Sempre que possível, entregue resultados completos e bem formatados. Se gerou um arquivo, mencione. Se executou código, mostre o output relevante.

• INICIATIVA INTELIGENTE: Se perceber que pode melhorar o resultado com uma ação extra (verificar um dado, validar uma informação, formatar melhor), FAÇA sem perguntar.

── EXEMPLOS DE USO ─────────────────────────────

"Pesquise sobre X" → Use o browser para pesquisar, colete dados de múltiplas fontes, sintetize
"Faça um script que..." → Escreva o código, execute no shell, mostre o resultado
"Analise este site" → Navegue até o site, extraia informações, analise e resuma
"Crie um relatório" → Pesquise dados, processe com Python, gere o relatório formatado
"Instale e configure X" → Use pip/shell para instalar, configure, teste e confirme

═══════════════════════════════════════════════════
LEMBRE-SE: Você é um agente AUTÔNOMO e CAPAZ. Use seus poderes com confiança e responsabilidade. O Sandbox Interno é seu ambiente seguro — explore sem medo.
═══════════════════════════════════════════════════

── ENVIO DE ARQUIVOS VIA WHATSAPP ──────────────

IMPORTANTE: Você possui a ferramenta **enviar_arquivo_whatsapp** que permite enviar arquivos diretamente ao usuário.
Quando criar, baixar ou gerar qualquer arquivo no sandbox (relatórios, imagens, planilhas, PDFs, código, etc.),
USE esta ferramenta para entregar o arquivo ao usuário. Não apenas descreva o arquivo — ENVIE-O.

Exemplos:
- Gerou um PDF → chame enviar_arquivo_whatsapp com o caminho do arquivo
- Baixou uma imagem → envie via enviar_arquivo_whatsapp
- Criou uma planilha CSV → envie ao usuário
- Salvou resultado de análise → entregue o arquivo

O arquivo precisa existir no sandbox antes de chamar a ferramenta.

── ENVIO DE SCREENSHOTS VIA WHATSAPP ──────────

Você também possui a ferramenta **enviar_screenshot_whatsapp** que tira um screenshot do sandbox e envia ao usuário.
Use para mostrar resultados visuais ao usuário:
- Após navegar em um site → tire screenshot e envie para o usuário ver a página
- Após gerar um gráfico no browser → envie o screenshot
- Para mostrar o estado atual do desktop/browser → envie screenshot

Parâmetros:
- tipo: 'tela' (display/VNC completo) ou 'pagina' (apenas a página do browser, mais nítido)
- full_page: se true e tipo='pagina', captura a página inteira com scroll
- caption: legenda opcional

DICA: Screenshots de páginas web ficam automaticamente enviados ao usuário quando você usa
as tools sandbox_browser_screenshot ou sandbox_browser_page_screenshot. Mas use
enviar_screenshot_whatsapp quando quiser controlar o envio com legenda personalizada.
"""

    @staticmethod
    def _extrair_texto_mcp(resultado_mcp: Dict[str, Any]) -> str:
        """Extrai texto de um resultado padronizado de executar_tool_mcp."""
        resultado = resultado_mcp.get("resultado", {})
        if isinstance(resultado, dict):
            # Formato {"resposta": "texto"}
            if "resposta" in resultado:
                return str(resultado["resposta"])
            # Formato {"content": [{"type": "text", "text": "..."}]}
            if "content" in resultado:
                parts = []
                for item in resultado["content"]:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                return "".join(parts)
            # Formato {"erro": "..."}
            if "erro" in resultado:
                return f"error: {resultado['erro']}"
            return str(resultado)
        elif isinstance(resultado, list):
            parts = []
            for item in resultado:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "".join(parts)
        return str(resultado)

    @staticmethod
    async def _enviar_arquivo_sandbox(
        db: Session,
        sessao_id: int,
        telefone_cliente: str,
        agente_id: int,
        args: Dict[str, Any],
        jid_destino=None,
    ) -> Dict[str, Any]:
        """
        Baixa um arquivo do sandbox interno e envia ao usuário via WhatsApp.
        """
        import os
        
        file_path = args.get("file_path", "")
        filename = args.get("filename") or os.path.basename(file_path)
        caption = args.get("caption", "")
        
        if not file_path:
            return {
                "resultado": {"erro": "file_path é obrigatório"},
                "output": "llm",
                "enviado_usuario": False
            }
        
        try:
            from internal_sandbox.internal_service import InternalService
            logger.debug("[SANDBOX] Baixando arquivo: %s", file_path)
            file_bytes = await InternalService.baixar_arquivo(agente_id, file_path)

            if not file_bytes:
                return {
                    "resultado": {"erro": f"Arquivo não encontrado ou erro ao baixar: {file_path}"},
                    "output": "llm",
                    "enviado_usuario": False
                }

            file_size_kb = len(file_bytes) / 1024
            logger.debug("[SANDBOX] Arquivo baixado: %s (%.1f KB)", filename, file_size_kb)
            
            # Passo 4: Determinar tipo de mídia pela extensão
            ext = os.path.splitext(filename)[1].lower()
            
            MIME_MAP = {
                ".pdf": "application/pdf",
                ".doc": "application/msword",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".xls": "application/vnd.ms-excel",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".csv": "text/csv",
                ".txt": "text/plain",
                ".zip": "application/zip",
                ".json": "application/json",
                ".html": "text/html",
                ".py": "text/x-python",
                ".js": "text/javascript",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".svg": "image/svg+xml",
                ".mp3": "audio/mpeg",
                ".ogg": "audio/ogg",
                ".wav": "audio/wav",
                ".m4a": "audio/mp4",
                ".opus": "audio/opus",
                ".aac": "audio/aac",
                ".mp4": "video/mp4",
                ".webm": "video/webm",
                ".avi": "video/x-msvideo",
                ".mkv": "video/x-matroska",
            }
            mime_type = MIME_MAP.get(ext, "application/octet-stream")
            
            IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            AUDIO_EXTS = {".mp3", ".ogg", ".wav", ".m4a", ".opus", ".aac"}
            VIDEO_EXTS = {".mp4", ".webm", ".avi", ".mkv"}
            
            # Passo 5: Obter cliente WhatsApp e enviar
            from sessao.sessao_service import gerenciador_sessoes
            cliente = gerenciador_sessoes.obter_cliente(sessao_id)
            if not cliente:
                return {
                    "resultado": {"erro": "Cliente WhatsApp não disponível para esta sessão"},
                    "output": "llm",
                    "enviado_usuario": False
                }
            
            # Usar JID resolvido se disponível (suporta formato LID)
            if jid_destino is not None:
                jid = jid_destino
            else:
                from neonize.utils import build_jid
                jid = build_jid(telefone_cliente)
                logger.warning("[SANDBOX] JID fallback usado (build_jid sem server) para telefone %s — pode falhar com LID", telefone_cliente)

            if ext in IMAGE_EXTS:
                cliente.send_image(jid, file_bytes, caption=caption)
                tipo_envio = "imagem"
            elif ext in AUDIO_EXTS:
                cliente.send_audio(jid, file_bytes, ptt=False)
                tipo_envio = "áudio"
            elif ext in VIDEO_EXTS:
                cliente.send_video(jid, file_bytes, caption=caption)
                tipo_envio = "vídeo"
            else:
                cliente.send_document(
                    jid,
                    file_bytes,
                    filename=filename,
                    caption=caption,
                    mimetype=mime_type
                )
                tipo_envio = "documento"

            logger.info("[SANDBOX] Arquivo '%s' enviado como %s (%.1f KB)", filename, tipo_envio, file_size_kb)
            return {
                "resultado": {
                    "sucesso": True,
                    "mensagem": f"Arquivo '{filename}' enviado ao usuário como {tipo_envio} ({file_size_kb:.1f} KB)",
                    "tipo": tipo_envio,
                    "tamanho_kb": round(file_size_kb, 1)
                },
                "output": "llm",
                "enviado_usuario": True
            }

        except Exception as e:
            logger.exception("[SANDBOX] Erro ao enviar arquivo: %s", e)
            return {
                "resultado": {"erro": f"Erro ao enviar arquivo: {str(e)}"},
                "output": "llm",
                "enviado_usuario": False
            }

    @staticmethod
    async def _enviar_arquivo_generico(
        db,
        sessao_id: int,
        telefone_cliente: str,
        args: Dict[str, Any],
        jid_destino=None,
    ) -> Dict[str, Any]:
        """
        Tool `enviar_arquivo` — envia midia ao usuario por canal ativo (hoje WA).
        Aceita ref com prefixo id:/file:/url:/base64:.
        """
        import base64 as _b64
        import os as _os
        from pathlib import Path as _Path

        ref = (args.get("ref") or "").strip()
        caption = args.get("caption", "") or ""
        filename_override = args.get("filename")

        if not ref:
            return {"resultado": {"erro": "ref e obrigatorio"}, "output": "llm", "enviado_usuario": False}

        # ----- Resolver ref em (bytes, filename, mime_hint) -----
        file_bytes: Optional[bytes] = None
        filename: Optional[str] = filename_override
        mime_hint: Optional[str] = None
        try:
            if ref.startswith("id:"):
                from midia import midia_service as _midia_svc
                media_id = ref[3:].strip()
                midia = _midia_svc.buscar_por_media_id(db, media_id, sessao_id=sessao_id)
                if not midia:
                    return {"resultado": {"erro": f"media_id '{media_id}' nao encontrado nesta sessao"}, "output": "llm", "enviado_usuario": False}
                from midia.midia_storage import ler_bytes as _ler
                file_bytes = _ler(midia.path)
                filename = filename or _os.path.basename(midia.path)
                mime_hint = midia.mime

            elif ref.startswith("file:"):
                path_raw = ref[5:].strip()
                # Anti path-traversal: so paths dentro de uploads/
                upload_base = ConfiguracaoService.obter_valor(db, "sistema_diretorio_uploads", "./uploads")
                from midia.midia_storage import path_dentro_uploads as _check
                if not _check(path_raw, upload_base):
                    return {"resultado": {"erro": "file: deve apontar pra arquivo dentro de uploads/"}, "output": "llm", "enviado_usuario": False}
                p = _Path(path_raw)
                if not p.exists():
                    return {"resultado": {"erro": f"arquivo nao encontrado: {path_raw}"}, "output": "llm", "enviado_usuario": False}
                file_bytes = p.read_bytes()
                filename = filename or p.name

            elif ref.startswith("url:"):
                url = ref[4:].strip()
                import httpx
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as _c:
                    resp = await _c.get(url)
                    resp.raise_for_status()
                    file_bytes = resp.content
                    mime_hint = resp.headers.get("content-type", "").split(";")[0] or None
                filename = filename or _os.path.basename(url.split("?")[0]) or "arquivo"

            elif ref.startswith("base64:"):
                payload = ref[7:].strip()
                if payload.startswith("data:"):
                    # data:image/png;base64,xxxx
                    head, _, b64 = payload.partition(",")
                    mime_hint = head.split(":", 1)[1].split(";", 1)[0] if ":" in head else None
                    file_bytes = _b64.b64decode(b64)
                else:
                    file_bytes = _b64.b64decode(payload)
                filename = filename or "arquivo.bin"

            else:
                return {"resultado": {"erro": "ref deve comecar com id:/file:/url:/base64:"}, "output": "llm", "enviado_usuario": False}

        except Exception as e:
            logger.exception("[enviar_arquivo] erro ao resolver ref: %s", e)
            return {"resultado": {"erro": f"erro ao resolver ref: {e}"}, "output": "llm", "enviado_usuario": False}

        if not file_bytes:
            return {"resultado": {"erro": "conteudo vazio apos resolver ref"}, "output": "llm", "enviado_usuario": False}

        # ----- Determinar tipo de envio pela extensao -----
        ext = _os.path.splitext(filename or "")[1].lower()
        IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        AUDIO_EXTS = {".mp3", ".ogg", ".wav", ".m4a", ".opus", ".aac"}
        VIDEO_EXTS = {".mp4", ".webm", ".avi", ".mkv"}

        from sessao.sessao_service import gerenciador_sessoes
        cliente = gerenciador_sessoes.obter_cliente(sessao_id)
        if not cliente:
            return {"resultado": {"erro": "canal nao disponivel para esta sessao"}, "output": "llm", "enviado_usuario": False}

        # Interface unificada CanalClient (canal_base.py): enviar_imagem / enviar_audio /
        # enviar_video / enviar_documento aceitam `chat_id` como string e cada adapter
        # converte internamente (WA monta JID, TG usa direto).
        # `jid_destino` vinha do pipeline WA (LID) — passa pra string. Pra TG eh ignorado.
        dest = telefone_cliente
        if jid_destino is not None:
            user = getattr(jid_destino, "User", None)
            server = getattr(jid_destino, "Server", None)
            if user and server:
                dest = f"{user}@{server}"
            elif user:
                dest = str(user)

        size_kb = len(file_bytes) / 1024
        tipo_envio = "documento"
        try:
            if ext in IMAGE_EXTS:
                ok = cliente.enviar_imagem(dest, file_bytes, legenda=caption or "")
                tipo_envio = "imagem"
            elif ext in AUDIO_EXTS:
                ok = cliente.enviar_audio(dest, file_bytes, ptt=False)
                tipo_envio = "audio"
            elif ext in VIDEO_EXTS:
                ok = cliente.enviar_video(dest, file_bytes, legenda=caption or "")
                tipo_envio = "video"
            else:
                ok = cliente.enviar_documento(dest, file_bytes, nome_arquivo=filename or "arquivo")
                tipo_envio = "documento"
            if ok is False:
                return {"resultado": {"erro": f"canal retornou falha ao enviar {tipo_envio}"}, "output": "llm", "enviado_usuario": False}
        except Exception as e:
            logger.exception("[enviar_arquivo] erro no envio: %s", e)
            return {"resultado": {"erro": f"erro ao enviar: {e}"}, "output": "llm", "enviado_usuario": False}

        logger.info("[enviar_arquivo] %s '%s' enviado (%.1f KB, ref_prefix=%s)",
                    tipo_envio, filename, size_kb, ref.split(":", 1)[0])
        return {
            "resultado": {
                "sucesso": True,
                "tipo": tipo_envio,
                "filename": filename,
                "tamanho_kb": round(size_kb, 1),
            },
            "output": "llm",
            "enviado_usuario": True,
        }

    @staticmethod
    async def _extrair_e_enviar_imagens_sandbox(
        resultado_completo: Dict[str, Any],
        sessao_id: int,
        telefone_cliente: str,
        jid_destino=None
    ) -> Dict[str, Any]:
        """
        Intercepta imagens base64 em resultados do sandbox SDK, envia ao usuário
        via WhatsApp e substitui o base64 por um resumo leve para o LLM.
        Formato SDK: {"type": "image", "image_base64": "...", "mime_type": "image/png"}
        """
        try:
            resultado = resultado_completo.get("resultado", {})
            if not isinstance(resultado, dict):
                return resultado_completo
            
            # Formato SDK: resultado direto com image_base64
            image_b64 = resultado.get("image_base64")
            if not image_b64:
                return resultado_completo
            
            logger.debug("[SDK->WA] Imagem detectada: %d chars base64", len(image_b64))
            img_bytes = base64.b64decode(image_b64)
            mime = resultado.get("mime_type", "image/png")
            size_kb = len(img_bytes) / 1024

            from sessao.sessao_service import gerenciador_sessoes

            cliente = gerenciador_sessoes.obter_cliente(sessao_id)
            if not cliente:
                logger.warning("[SDK->WA] Cliente WhatsApp não encontrado para sessão %s", sessao_id)
                resultado_completo = dict(resultado_completo)
                resultado_completo["resultado"] = {
                    "type": "image",
                    "message": "[Screenshot capturado mas cliente WA indisponível]",
                    "size_kb": round(size_kb, 1)
                }
                return resultado_completo

            if jid_destino is not None:
                jid = jid_destino
            else:
                from neonize.utils import build_jid
                jid = build_jid(telefone_cliente)
                logger.warning("[SDK->WA] JID fallback usado (build_jid sem server) para telefone %s", telefone_cliente)

            cliente.send_image(jid, img_bytes, caption="")
            logger.info("[SDK->WA] Imagem enviada com sucesso (%.0f KB, %s)", size_kb, mime)

            resultado_completo = dict(resultado_completo)
            resultado_completo["resultado"] = {
                "type": "image",
                "message": f"[Screenshot {size_kb:.0f}KB enviado ao usuário via WhatsApp]",
                "size_kb": round(size_kb, 1)
            }
            resultado_completo["enviado_usuario"] = True
            return resultado_completo

        except Exception as e:
            logger.exception("[SDK->WA] Erro na interceptação de imagem: %s: %s", type(e).__name__, e)
            return resultado_completo

    @staticmethod
    async def _enviar_screenshot_sandbox(
        sessao_id: int,
        telefone_cliente: str,
        agente_id: int,
        args: Dict[str, Any],
        jid_destino=None,
    ) -> Dict[str, Any]:
        """
        Tira um screenshot do sandbox interno e envia ao usuário via WhatsApp.
        Tool virtual: enviar_screenshot_whatsapp.
        """
        tipo = args.get("tipo", "pagina")
        full_page = args.get("full_page", False)
        caption = args.get("caption", "")
        
        try:
            from internal_sandbox.internal_service import InternalService
            logger.debug("[SANDBOX] Tirando screenshot tipo='%s', full_page=%s", tipo, full_page)
            if tipo == "tela":
                img_bytes = await InternalService.tirar_screenshot(agente_id)
            else:
                img_bytes = await InternalService.tirar_screenshot_pagina(agente_id, full_page=full_page)
            
            if not img_bytes:
                return {
                    "resultado": {"erro": "Falha ao capturar screenshot do sandbox"},
                    "output": "llm",
                    "enviado_usuario": False
                }
            
            size_kb = len(img_bytes) / 1024
            logger.debug("[SANDBOX] Screenshot capturado: %.1f KB", size_kb)

            from sessao.sessao_service import gerenciador_sessoes
            cliente = gerenciador_sessoes.obter_cliente(sessao_id)
            if not cliente:
                return {
                    "resultado": {"erro": "Cliente WhatsApp não disponível"},
                    "output": "llm",
                    "enviado_usuario": False
                }

            if jid_destino is not None:
                jid = jid_destino
            else:
                from neonize.utils import build_jid
                jid = build_jid(telefone_cliente)
                logger.warning("[SANDBOX] JID fallback usado (build_jid sem server) para screenshot, telefone %s", telefone_cliente)

            cliente.send_image(jid, img_bytes, caption=caption)
            logger.info("[SANDBOX] Screenshot enviado via WhatsApp (%.1f KB)", size_kb)

            return {
                "resultado": {
                    "sucesso": True,
                    "mensagem": f"Screenshot ({tipo}) enviado ao usuário ({size_kb:.1f} KB)",
                    "tamanho_kb": round(size_kb, 1)
                },
                "output": "llm",
                "enviado_usuario": True
            }
        except Exception as e:
            logger.exception("[SANDBOX] Erro ao enviar screenshot: %s", e)
            return {
                "resultado": {"erro": f"Erro ao enviar screenshot: {str(e)}"},
                "output": "llm",
                "enviado_usuario": False
            }

    @staticmethod
    def construir_historico_mensagens(mensagens: List, mensagem_atual) -> List[Dict]:
        """
        Constrói o histórico de mensagens no formato do OpenRouter.
        """
        historico = []
        
        # Adicionar mensagens anteriores (invertido para ordem cronológica)
        for msg in reversed(mensagens[:10]):
            if msg.id == mensagem_atual.id:
                continue
            
            # Só processar mensagens recebidas
            if msg.direcao != "recebida":
                continue
            
            # Mensagem do usuário
            conteudo = []
            
            # Adicionar texto
            if msg.conteudo_texto:
                conteudo.append({
                    "type": "text",
                    "text": msg.conteudo_texto
                })
            
            # Adicionar imagem se houver
            if msg.tipo == "imagem" and msg.conteudo_imagem_base64:
                mime_type = msg.conteudo_mime_type or "image/jpeg"
                data_url = f"data:{mime_type};base64,{msg.conteudo_imagem_base64}"
                conteudo.append({
                    "type": "image_url",
                    "image_url": {
                        "url": data_url
                    }
                })
            
            if conteudo:
                # Se só tem um item e é texto, usar string simples
                if len(conteudo) == 1 and conteudo[0].get("type") == "text":
                    content = conteudo[0]["text"]
                else:
                    content = conteudo
                
                historico.append({
                    "role": "user",
                    "content": content
                })
                
                # Adicionar resposta do assistente (se houver)
                if msg.resposta_texto:
                    historico.append({
                        "role": "assistant",
                        "content": msg.resposta_texto
                    })
        
        return historico

    @staticmethod
    async def processar_mensagem(
        db: Session,
        sessao,
        mensagem,
        historico_mensagens: List,
        agente: Optional[Agente] = None,
        jid_destino=None
    ) -> Dict[str, Any]:
        """
        Processa uma mensagem com o agente LLM usando loop principal.
        Suporta múltiplas chamadas de ferramentas em paralelo.
        
        Args:
            db: Sessão do banco de dados
            sessao: Sessão WhatsApp
            mensagem: Mensagem a ser processada
            historico_mensagens: Histórico de mensagens
            agente: Agente a ser usado (se None, usa o agente ativo da sessão)
            jid_destino: JID resolvido do destinatário (preserva formato LID)
        
        Returns:
            Dict com: texto, tokens_input, tokens_output, tempo_ms, modelo, ferramentas
        """
        inicio = time.time()
        
        # Se não foi passado agente, usar o agente ativo da sessão
        if agente is None:
            if sessao.agente_ativo_id:
                agente = AgenteService.obter_por_id(db, sessao.agente_ativo_id)
            
            if agente is None:
                raise ValueError("Nenhum agente ativo configurado para esta sessão")
        
        # Obter modelo (do agente, ou padrão)
        modelo = agente.modelo_llm or ConfiguracaoService.obter_valor(
            db, "openrouter_modelo_padrao", "google/gemini-3.1-flash-lite-preview"
        )
        
        # Obter parâmetros (do agente, ou padrão)
        temperatura = float(agente.temperatura or ConfiguracaoService.obter_valor(
            db, "openrouter_temperatura", "0.7"
        ))
        max_tokens = int(agente.max_tokens or ConfiguracaoService.obter_valor(
            db, "openrouter_max_tokens", "2000"
        ))
        top_p = float(agente.top_p or ConfiguracaoService.obter_valor(
            db, "openrouter_top_p", "1.0"
        ))
        frequency_penalty = float(agente.frequency_penalty or ConfiguracaoService.obter_valor(
            db, "openrouter_frequency_penalty", "0.0"
        ))
        presence_penalty = float(agente.presence_penalty or ConfiguracaoService.obter_valor(
            db, "openrouter_presence_penalty", "0.0"
        ))
        
        # Buscar skills ativas do agente
        from skill.skill_service import SkillService
        skills_agente = SkillService.listar_skills_agente(db, agente.id)

        # Construir system prompt (com skills se houver)
        system_prompt = AgenteService.construir_system_prompt(agente, skills=skills_agente if skills_agente else None)
        
        # Construir histórico
        historico = AgenteService.construir_historico_mensagens(
            historico_mensagens,
            mensagem
        )
        
        # Construir mensagem atual
        conteudo_atual = []
        
        if mensagem.conteudo_texto:
            conteudo_atual.append({
                "type": "text",
                "text": mensagem.conteudo_texto
            })
        
        # Adicionar imagem se houver
        if mensagem.tipo == "imagem" and mensagem.conteudo_imagem_base64:
            mime_type = mensagem.conteudo_mime_type or "image/jpeg"
            data_url = f"data:{mime_type};base64,{mensagem.conteudo_imagem_base64}"
            conteudo_atual.append({
                "type": "image_url",
                "image_url": {
                    "url": data_url
                }
            })
        
        # Montar mensagens iniciais
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        messages.extend(historico)
        # Determinar content da mensagem atual
        if not conteudo_atual:
            content_atual = "..."
        elif len(conteudo_atual) == 1 and conteudo_atual[0].get("type") == "text":
            content_atual = conteudo_atual[0]["text"]
        else:
            content_atual = conteudo_atual
        
        messages.append({
            "role": "user",
            "content": content_atual
        })
        
        # Buscar ferramentas ativas do agente
        ferramentas_disponiveis = AgenteService.listar_ferramentas(db, agente.id)

        # Preparar tools no formato OpenAI
        tools = None
        if ferramentas_disponiveis:
            tools = []
            for ferramenta in ferramentas_disponiveis:
                tool_openai = FerramentaService.converter_para_openai_format(ferramenta)
                if tool_openai:  # Apenas ferramentas PRINCIPAL
                    tools.append(tool_openai)
        
        # Buscar clientes MCP ativos do agente (presets NÃO-sandbox)
        from mcp_client.mcp_service import MCPService
        mcp_clients = MCPService.listar_ativos_por_agente(db, agente.id)
        
        # Adicionar ferramentas MCP (excluir sandbox — agora é via toggle)
        for mcp_client in mcp_clients:
            if not mcp_client.conectado:
                continue
            
            if mcp_client.preset_key == "aio-sandbox":
                continue
            
            # Outros presets MCP continuam funcionando normalmente
            mcp_tools = MCPService.listar_tools_ativas(db, mcp_client.id)
            for mcp_tool in mcp_tools:
                if tools is None:
                    tools = []
                tool_openai = MCPService.converter_mcp_tool_para_openai(mcp_client, mcp_tool)
                tools.append(tool_openai)
        
        # Injetar tool invocar_skill se o agente tiver skills
        if skills_agente:
            if tools is None:
                tools = []
            tools.append(AgenteService._definir_tool_invocar_skill())

        # Injetar tools do Sandbox Interno removido - agora é responsabilidade exclusiva do Coding Agent

        # Adicionar ferramenta de busca RAG se o agente tiver treinamento vinculado
        if agente.rag_id:
            if tools is None:
                tools = []
            
            # Definir ferramenta de busca na base de conhecimento
            tools.append({
                "type": "function",
                "function": {
                    "name": "buscar_base_conhecimento",
                    "description": "Busca informações relevantes na base de conhecimento do treinamento para responder perguntas do usuário",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "A pergunta ou consulta para buscar na base de conhecimento"
                            },
                            "num_resultados": {
                                "type": "integer",
                                "description": "Número de resultados a retornar (padrão: 3)",
                                "default": 3
                            }
                        },
                        "required": ["query"]
                    }
                }
            })

        # Tool genérica enviar_arquivo — disponível pra todo agente.
        # Aceita ref com prefixo id:<media_id> | file:<path> | url:<https> | base64:<...>
        # Hoje funciona pra WhatsApp; será estendida pra Telegram/webchat na sequência.
        if tools is None:
            tools = []
        tools.append({
            "type": "function",
            "function": {
                "name": "enviar_arquivo",
                "description": (
                    "Envia um arquivo (imagem/audio/video/documento) ao usuario via canal ativo.\n\n"
                    "REGRA IMPORTANTE SOBRE media_id:\n"
                    "Quando o usuario envia uma midia (foto, audio, etc.), aparece no historico uma "
                    "anotacao no formato [midia anexada: tipo=..., media_id=\"s1_XXXXX_upload_YYYY\"]. "
                    "Este media_id eh REAL e foi registrado no sistema — use ele exatamente como aparece. "
                    "NUNCA invente nomes de arquivo (ex: 'input_file_0.png') nem URLs do tipo "
                    "openai/oaiusercontent — esses sao alucinacao e vao falhar.\n\n"
                    "Prefixos aceitos em `ref`:\n"
                    "• id:<media_id> - midia ja registrada. O media_id aparece em [midia anexada: ...] "
                    "no historico desta conversa. Exemplo de id real: 's1_5511_upload_a1b2c3d4ef'.\n"
                    "• url:<https://...> - URL publica REAL e acessivel (nao invente URLs).\n"
                    "• file:<path_absoluto> - arquivo local (so paths dentro de uploads/).\n"
                    "• base64:<data> - bytes embutidos (use so quando os anteriores nao se aplicarem).\n\n"
                    "Tipo de envio (imagem/audio/video/documento) eh determinado pela extensao do arquivo."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {
                            "type": "string",
                            "description": "Referencia da midia (com prefixo id:/url:/file:/base64:)",
                        },
                        "caption": {
                            "type": "string",
                            "description": "Legenda opcional",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Nome do arquivo (so usado quando ref nao tem extensao reconhecivel)",
                        },
                    },
                    "required": ["ref"],
                },
            }
        })

        # Sincronizar messages[0] com o system_prompt final (sandbox + skills)
        messages[0]["content"] = system_prompt

        # Variáveis de controle
        tokens_input_total = 0
        tokens_output_total = 0
        ferramentas_usadas = []
        texto_resposta_final = ""
        if agente.internal_sandbox_ativo:
            max_iteracoes = int(ConfiguracaoService.obter_valor(db, "agente_max_iteracoes_sandbox", 25))
        else:
            max_iteracoes = int(ConfiguracaoService.obter_valor(db, "agente_max_iteracoes_loop", 10))
        iteracao = 0
        # Controle de loop: rastreia chamadas consecutivas à mesma ferramenta
        _ultimas_tools: list = []
        _MAX_REPETICOES_TOOL = 3

        # Loop principal de processamento
        fluxi_log.info("agente", "loop", "Iniciando processamento", extra={
            "agente_id": agente.id,
            "modelo": modelo,
            "max_iteracoes": max_iteracoes,
            "sandbox": agente.internal_sandbox_ativo,
            "n_tools": len(tools) if tools else 0,
        }, session_id=sessao.id if sessao else None)
        try:
            while iteracao < max_iteracoes:
                iteracao += 1
                fluxi_log.debug("agente", "loop", f"Iteracao {iteracao}/{max_iteracoes}", extra={
                    "agente_id": agente.id,
                    "iteracao": iteracao,
                    "max_iteracoes": max_iteracoes,
                }, session_id=sessao.id if sessao else None)

                messages_llm = AgenteService._trim_messages_sandbox(messages) if agente.internal_sandbox_ativo else messages
                # Timeout por iteração: 120s normais, 300s em sandbox (execuções longas)
                _llm_timeout = 300.0 if agente.internal_sandbox_ativo else 120.0
                try:
                    resultado = await asyncio.wait_for(
                        LLMIntegrationService.processar_mensagem_com_llm(
                            db=db,
                            messages=messages_llm,
                            modelo=modelo,
                            agente_id=agente.id,
                            temperatura=temperatura,
                            max_tokens=max_tokens,
                            top_p=top_p,
                            frequency_penalty=frequency_penalty,
                            presence_penalty=presence_penalty,
                            tools=tools,
                            stream=False
                        ),
                        timeout=_llm_timeout,
                    )
                except asyncio.TimeoutError:
                    fluxi_log.error("agente", "loop", f"Timeout LLM {_llm_timeout:.0f}s na iteracao {iteracao}", extra={
                        "agente_id": agente.id, "modelo": modelo, "iteracao": iteracao,
                        "timeout_s": _llm_timeout,
                    }, session_id=sessao.id if sessao else None)
                    raise ValueError(
                        f"Timeout de {_llm_timeout:.0f}s atingido aguardando resposta do LLM "
                        f"(iteração {iteracao}/{max_iteracoes}). Modelo: {modelo}"
                    )
                # Extrair dados da resposta
                message_response = {
                    "role": "assistant",
                    "content": resultado.get("conteudo", ""),
                    "tool_calls": resultado.get("tool_calls")
                }
                
                # Atualizar contadores de tokens
                if resultado.get("tokens_input"):
                    tokens_input_total += resultado["tokens_input"]
                if resultado.get("tokens_output"):
                    tokens_output_total += resultado["tokens_output"]
                
                # Adicionar resposta do assistente ao histórico
                messages.append(message_response)
                
                # Verificar finish_reason
                finish_reason = resultado.get("finish_reason", "stop")
                fluxi_log.info("agente", "loop", "Resposta LLM recebida", extra={
                    "agente_id": agente.id,
                    "iteracao": iteracao,
                    "finish_reason": finish_reason,
                    "tokens_in": resultado.get("tokens_input", 0),
                    "tokens_out": resultado.get("tokens_output", 0),
                    "modelo": modelo,
                }, session_id=sessao.id if sessao else None)

                # Verificar se há tool calls
                tool_calls = message_response.get("tool_calls")

                # Processa tool_calls se presentes — independente do finish_reason,
                # pois diferentes LLMs retornam "stop", "tool_calls", "tool_use" ou None
                if tool_calls:
                    # Detectar loop: mesma(s) ferramenta(s) chamadas repetidamente
                    tool_names_agora = sorted(
                        tc.get("function", {}).get("name", "") for tc in tool_calls
                    )
                    _ultimas_tools.append(tool_names_agora)
                    if len(_ultimas_tools) > _MAX_REPETICOES_TOOL:
                        _ultimas_tools.pop(0)
                    if (
                        len(_ultimas_tools) == _MAX_REPETICOES_TOOL
                        and all(t == _ultimas_tools[0] for t in _ultimas_tools)
                    ):
                        logger.warning(
                            "[AGENTE %s] Loop de ferramentas detectado (%d repetições de %s). Interrompendo.",
                            agente.id, _MAX_REPETICOES_TOOL, tool_names_agora
                        )
                        fluxi_log.warning("agente", "loop", f"Loop de ferramentas detectado: {tool_names_agora}", extra={
                            "agente_id": agente.id, "repeticoes": _MAX_REPETICOES_TOOL,
                            "tools": tool_names_agora,
                        }, session_id=sessao.id if sessao else None)
                        texto_resposta_final = (
                            "Não foi possível concluir a operação: a ferramenta entrou em loop. "
                            "Por favor, reformule sua solicitação."
                        )
                        break

                    fluxi_log.info("agente", "ferramenta", f"LLM chamou {len(tool_calls)} ferramenta(s): {tool_names_agora}", extra={
                        "agente_id": agente.id, "iteracao": iteracao,
                        "tools": tool_names_agora, "n_tools": len(tool_calls),
                    }, session_id=sessao.id if sessao else None)
                    for tool_call in tool_calls:
                        function_name = tool_call.get("function", {}).get("name")
                        function_args = tool_call.get("function", {}).get("arguments")
                        args_dict = json.loads(function_args) if isinstance(function_args, str) else function_args
                        
                        _tool_inicio = time.time()
                        # Detectar se é ferramenta do Sandbox Interno (prefixo sandbox_)
                        if function_name.startswith("sandbox_") and agente.internal_sandbox_ativo:
                            try:
                                from internal_sandbox.internal_service import InternalService
                                fluxi_log.info("agente", "ferramenta", f"Executando sandbox tool: {function_name}", extra={
                                    "agente_id": agente.id, "tool": function_name, "tipo": "sandbox",
                                }, session_id=sessao.id if sessao else None)
                                resultado_completo = await InternalService.executar_tool(
                                    db, agente.id, function_name, args_dict
                                )
                                _tool_ms = int((time.time() - _tool_inicio) * 1000)
                                fluxi_log.info("agente", "ferramenta", f"Sandbox tool concluida: {function_name} ({_tool_ms}ms)", extra={
                                    "agente_id": agente.id, "tool": function_name, "tipo": "sandbox", "tempo_ms": _tool_ms,
                                }, session_id=sessao.id if sessao else None)
                            except Exception as e:
                                logger.exception("[AGENTE %s] Erro ao executar tool Sandbox Interno %s: %s", agente.id, function_name, e)
                                fluxi_log.error("agente", "ferramenta", f"Erro sandbox tool {function_name}: {e}", extra={
                                    "agente_id": agente.id, "tool": function_name, "tipo": "sandbox",
                                    "erro": str(e), "tempo_ms": int((time.time() - _tool_inicio) * 1000),
                                }, exc_info=True, session_id=sessao.id if sessao else None)
                                resultado_completo = {
                                    "resultado": {"erro": f"Erro ao executar tool Sandbox Interno: {str(e)}"},
                                    "output": "llm",
                                    "enviado_usuario": False
                                }

                        # Detectar se é ferramenta MCP (prefixo mcp_) — presets não-sandbox
                        elif function_name.startswith("mcp_"):
                            try:
                                parts = function_name.split("_", 2)
                                mcp_client_id = int(parts[1])
                                original_tool_name = parts[2]
                                fluxi_log.info("agente", "ferramenta", f"Executando MCP tool: {original_tool_name}", extra={
                                    "agente_id": agente.id, "tool": original_tool_name,
                                    "mcp_client_id": mcp_client_id, "tipo": "mcp",
                                }, session_id=sessao.id if sessao else None)
                                resultado_completo = await MCPService.executar_tool_mcp(
                                    db, mcp_client_id, original_tool_name, args_dict
                                )
                                _tool_ms = int((time.time() - _tool_inicio) * 1000)
                                fluxi_log.info("agente", "ferramenta", f"MCP tool concluida: {original_tool_name} ({_tool_ms}ms)", extra={
                                    "agente_id": agente.id, "tool": original_tool_name, "tipo": "mcp", "tempo_ms": _tool_ms,
                                }, session_id=sessao.id if sessao else None)
                            except Exception as e:
                                logger.exception("[AGENTE %s] Erro ao executar tool MCP %s: %s", agente.id, function_name, e)
                                fluxi_log.error("agente", "ferramenta", f"Erro MCP tool {function_name}: {e}", extra={
                                    "agente_id": agente.id, "tool": function_name, "tipo": "mcp",
                                    "erro": str(e), "tempo_ms": int((time.time() - _tool_inicio) * 1000),
                                }, exc_info=True, session_id=sessao.id if sessao else None)
                                resultado_completo = {
                                    "resultado": {"erro": f"Erro ao executar tool MCP: {str(e)}"},
                                    "output": "llm",
                                    "enviado_usuario": False
                                }
                        
                        # Verificar se é a ferramenta de busca RAG
                        elif function_name == "buscar_base_conhecimento" and agente.rag_id:
                            # Executar busca no RAG
                            from rag.rag_service import RAGService
                            from rag.rag_metrica_service import RAGMetricaService
                            fluxi_log.info("agente", "ferramenta", "Executando busca RAG", extra={
                                "agente_id": agente.id, "rag_id": agente.rag_id, "tipo": "rag",
                                "query": args_dict.get("query", "")[:100],
                            }, session_id=sessao.id if sessao else None)
                            try:
                                query = args_dict.get("query", "")
                                num_resultados_padrao = ConfiguracaoService.obter_valor(db, "agente_rag_resultados_padrao", 3)
                                num_resultados = args_dict.get("num_resultados", num_resultados_padrao)
                                
                                # Medir tempo de busca
                                tempo_inicio = time.time()
                                
                                # Buscar no RAG
                                resultados_busca = RAGService.buscar(
                                    db, agente.rag_id, query, num_resultados
                                )
                                
                                # Calcular tempo
                                tempo_ms = int((time.time() - tempo_inicio) * 1000)
                                
                                # Registrar métrica
                                RAGMetricaService.registrar_busca(
                                    db=db,
                                    rag_id=agente.rag_id,
                                    query=query,
                                    resultados=resultados_busca,
                                    num_solicitados=num_resultados,
                                    tempo_ms=tempo_ms,
                                    agente_id=agente.id,
                                    sessao_id=sessao.id,
                                    telefone_cliente=mensagem.telefone_cliente
                                )
                                
                                # Formatar resultados para o LLM
                                contextos = []
                                for r in resultados_busca:
                                    contextos.append({
                                        "conteudo": r.get("context", ""),
                                        "fonte": r.get("metadata", {}).get("titulo", ""),
                                    })
                                
                                resultado_completo = {
                                    "resultado": {
                                        "sucesso": True,
                                        "query": query,
                                        "total_resultados": len(contextos),
                                        "contextos": contextos
                                    },
                                    "output": "llm"
                                }
                            except Exception as e:
                                fluxi_log.error("agente", "ferramenta", f"Erro busca RAG: {e}", extra={
                                    "agente_id": agente.id, "rag_id": agente.rag_id, "tipo": "rag",
                                    "erro": str(e),
                                }, exc_info=True, session_id=sessao.id if sessao else None)
                                resultado_completo = {
                                    "resultado": {"erro": f"Erro ao buscar: {str(e)}"},
                                    "output": "llm"
                                }
                        # Executar skill invocada pelo LLM
                        elif function_name == "invocar_skill":
                            fluxi_log.info("agente", "ferramenta", f"Executando skill: {args_dict.get('skill_name', '?')}", extra={
                                "agente_id": agente.id, "tipo": "skill",
                                "skill_name": args_dict.get("skill_name"),
                            }, session_id=sessao.id if sessao else None)
                            try:
                                resultado_completo = await AgenteService._executar_invocar_skill(
                                    db=db,
                                    agente=agente,
                                    args=args_dict,
                                    tools=tools,
                                    messages=messages
                                )
                            except Exception as e:
                                logger.exception("[AGENTE %s] Erro ao executar invocar_skill: %s", agente.id, e)
                                fluxi_log.error("agente", "ferramenta", f"Erro skill: {e}", extra={
                                    "agente_id": agente.id, "tipo": "skill", "erro": str(e),
                                }, exc_info=True, session_id=sessao.id if sessao else None)
                                resultado_completo = {
                                    "resultado": {"erro": f"Erro ao invocar skill: {str(e)}"},
                                    "output": "llm"
                                }

                        # Tool genérica enviar_arquivo — funciona pra todo agente (sem sandbox).
                        # Aceita ref com prefixo id:/file:/url:/base64:.
                        elif function_name == "enviar_arquivo":
                            resultado_completo = await AgenteService._enviar_arquivo_generico(
                                db=db,
                                sessao_id=sessao.id,
                                telefone_cliente=mensagem.telefone_cliente,
                                args=args_dict,
                                jid_destino=jid_destino,
                            )

                        # Enviar arquivo do sandbox para o usuário via WhatsApp
                        elif function_name == "enviar_arquivo_whatsapp" and agente.internal_sandbox_ativo:
                            resultado_completo = await AgenteService._enviar_arquivo_sandbox(
                                db=db,
                                sessao_id=sessao.id,
                                telefone_cliente=mensagem.telefone_cliente,
                                agente_id=agente.id,
                                args=args_dict,
                                jid_destino=jid_destino,
                            )
                        
                        # Enviar screenshot do sandbox via WhatsApp
                        elif function_name == "enviar_screenshot_whatsapp" and agente.internal_sandbox_ativo:
                            resultado_completo = await AgenteService._enviar_screenshot_sandbox(
                                sessao_id=sessao.id,
                                telefone_cliente=mensagem.telefone_cliente,
                                agente_id=agente.id,
                                args=args_dict,
                                jid_destino=jid_destino,
                            )
                        
                        else:
                            # Executar ferramenta normal do banco
                            fluxi_log.info("agente", "ferramenta", f"Executando ferramenta: {function_name}", extra={
                                "agente_id": agente.id, "tool": function_name, "tipo": "regular",
                            }, session_id=sessao.id if sessao else None)
                            resultado_completo = await FerramentaService.executar_ferramenta(
                                db,
                                function_name,
                                args_dict,
                                sessao_id=sessao.id,
                                telefone_cliente=mensagem.telefone_cliente,
                                jid_destino=jid_destino,
                            )
                        
                        # Interceptar imagens em resultados do sandbox interno
                        if agente.internal_sandbox_ativo and function_name.startswith("sandbox_"):
                            resultado_completo = await AgenteService._extrair_e_enviar_imagens_sandbox(
                                resultado_completo, sessao.id, mensagem.telefone_cliente,
                                jid_destino=jid_destino
                            )
                        
                        # Extrair resultado para o LLM
                        resultado_llm = resultado_completo.get("resultado", resultado_completo)
                        output_type = resultado_completo.get("output", "llm")
                        enviado_usuario = resultado_completo.get("enviado_usuario", False)
                        post_instruction = resultado_completo.get("post_instruction")
                        
                        # Registrar uso da ferramenta
                        ferramentas_usadas.append({
                            "nome": function_name,
                            "argumentos": function_args,
                            "resultado": resultado_llm,
                            "output": output_type,
                            "enviado_usuario": enviado_usuario
                        })
                        
                        # Preparar conteúdo para o LLM
                        conteudo_tool = json.dumps(resultado_llm, ensure_ascii=False)
                        
                        # Se tem post_instruction, adicionar ao contexto
                        if post_instruction and output_type in ["llm", "both"]:
                            conteudo_tool = f"{conteudo_tool}\n\nInstrução: {post_instruction}"
                        
                        # Adicionar resultado ao histórico apenas se output inclui LLM
                        if output_type in ["llm", "both"]:
                            logger.debug("[AGENTE %s] Resultado da tool adicionado ao histórico (output=%s, %d chars)", agente.id, output_type, len(conteudo_tool))
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.get("id"),
                                "content": conteudo_tool
                            })
                        else:
                            # Se output é apenas USER, informar ao LLM que foi enviado
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.get("id"),
                                "content": json.dumps({
                                    "status": "enviado_ao_usuario",
                                    "mensagem": "Resultado enviado diretamente ao usuário via WhatsApp"
                                }, ensure_ascii=False)
                            })
                            logger.debug("[AGENTE %s] Resultado da tool enviado ao usuário (output=%s)", agente.id, output_type)

                    # Continuar o loop para processar os resultados das ferramentas
                    logger.debug("[AGENTE %s] %d tool(s) processadas. Continuando loop.", agente.id, len(tool_calls))
                    continue
                else:
                    # Sem tool_calls — resposta final em texto
                    texto_resposta_final = message_response.get("content", "") or ""
                    # Detectar falha: LLM retornou vazio E finish_reason não é de stop normal
                    _finish_ok = {"stop", "length", "end_turn", "max_tokens", "tool_calls", "tool_use"}
                    if not texto_resposta_final and finish_reason not in _finish_ok:
                        fluxi_log.error("agente", "loop", f"Resposta vazia do LLM (finish_reason={finish_reason})", extra={
                            "agente_id": agente.id, "finish_reason": finish_reason, "iteracao": iteracao,
                        }, session_id=sessao.id if sessao else None)
                        raise ValueError(
                            f"LLM retornou resposta vazia (finish_reason={finish_reason!r}). "
                            "Provável estouro de contexto ou timeout do modelo local."
                        )
                    fluxi_log.info("agente", "loop", f"Resposta final recebida ({len(texto_resposta_final)} chars)", extra={
                        "agente_id": agente.id, "iteracao": iteracao, "chars": len(texto_resposta_final),
                    }, session_id=sessao.id if sessao else None)
                    break

            # Calcular tempo total
            tempo_ms = int((time.time() - inicio) * 1000)
            logger.info("[AGENTE %s] Processamento concluído em %dms (%d iterações)", agente.id, tempo_ms, iteracao)
            fluxi_log.info("agente", "loop", f"Processamento concluido em {tempo_ms}ms", extra={
                "agente_id": agente.id, "iteracoes": iteracao,
                "tokens_in_total": tokens_input_total, "tokens_out_total": tokens_output_total,
                "n_ferramentas": len(ferramentas_usadas), "tempo_ms": tempo_ms,
                "modelo": modelo,
            }, session_id=sessao.id if sessao else None)
            return {
                "texto": texto_resposta_final,
                "tokens_input": tokens_input_total,
                "tokens_output": tokens_output_total,
                "tempo_ms": tempo_ms,
                "modelo": modelo,
                "ferramentas": ferramentas_usadas if ferramentas_usadas else None
            }

        except httpx.TimeoutException:
            logger.error("[AGENTE %s] Timeout ao conectar com OpenRouter", agente.id)
            fluxi_log.error("agente", "loop", "Timeout HTTP ao conectar com provider", extra={
                "agente_id": agente.id, "modelo": modelo, "iteracao": iteracao,
            }, session_id=sessao.id if sessao else None)
            raise ValueError("Timeout ao conectar com OpenRouter")
        except Exception as e:
            logger.exception("[AGENTE %s] Exceção no loop: %s: %s", agente.id, type(e).__name__, e)
            fluxi_log.error("agente", "loop", f"Excecao no loop: {type(e).__name__}: {e}", extra={
                "agente_id": agente.id, "modelo": modelo, "iteracao": iteracao,
                "erro_tipo": type(e).__name__, "erro": str(e),
            }, exc_info=True, session_id=sessao.id if sessao else None)
            raise ValueError(f"Erro ao processar com LLM: {str(e)}")
