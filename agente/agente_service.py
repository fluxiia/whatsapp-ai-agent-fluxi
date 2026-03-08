"""
Serviço do agente LLM com integração OpenRouter.
"""
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import httpx
import json
import base64
import time
from datetime import datetime
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
            nome="Assistente Padrão",
            descricao="Agente de atendimento geral",
            agente_papel=ConfiguracaoService.obter_valor(
                db, "agente_papel_padrao", "assistente pessoal"
            ),
            agente_objetivo=ConfiguracaoService.obter_valor(
                db, "agente_objetivo_padrao", "ajudar o usuário com suas dúvidas e tarefas"
            ),
            agente_politicas=ConfiguracaoService.obter_valor(
                db, "agente_politicas_padrao", "ser educado, respeitoso e prestativo"
            ),
            agente_tarefa=ConfiguracaoService.obter_valor(
                db, "agente_tarefa_padrao", "responder perguntas de forma clara e objetiva"
            ),
            agente_objetivo_explicito=ConfiguracaoService.obter_valor(
                db, "agente_objetivo_explicito_padrao", "fornecer informações úteis e precisas"
            ),
            agente_publico=ConfiguracaoService.obter_valor(
                db, "agente_publico_padrao", "usuários em geral"
            ),
            agente_restricoes=ConfiguracaoService.obter_valor(
                db, "agente_restricoes_padrao", "responder em português brasileiro, ser conciso"
            ),
            ativo=True
        )
        
        agente = AgenteService.criar(db, agente_data)
        
        # Associar ferramentas padrão (configurável)
        nomes_ferramentas_padrao = ConfiguracaoService.obter_valor(
            db, "agente_ferramentas_padrao", ["obter_data_hora_atual", "calcular"]
        )
        ferramentas_padrao = db.query(Ferramenta).filter(
            Ferramenta.nome.in_(nomes_ferramentas_padrao)
        ).all()
        
        if ferramentas_padrao:
            ferramentas_ids = [f.id for f in ferramentas_padrao]
            AgenteService.atualizar_ferramentas(db, agente.id, ferramentas_ids)
        
        return agente

    @staticmethod
    def construir_system_prompt(agente: Agente) -> str:
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
        
        return (
            f"Você é: {agente.agente_papel}.\n"
            f"Objetivo: {agente.agente_objetivo}.\n"
            f"Políticas: {agente.agente_politicas}.\n"
            f"Tarefa: {agente.agente_tarefa}.\n"
            f"Objetivo explícito: {agente.agente_objetivo_explicito}.\n"
            f"Público/usuário-alvo: {agente.agente_publico}.\n"
            f"Restrições e políticas: {agente.agente_restricoes}.\n"
            f"{instrucao_tools}"
        )

    @staticmethod
    def _prompt_aio_sandbox() -> str:
        """Prompt suplementar injetado quando o AIO Sandbox está ativo."""
        return """

═══════════════════════════════════════════════════
🚀 MODO AGENTE AUTÔNOMO — AIO SANDBOX ATIVO
═══════════════════════════════════════════════════

Você agora é um AGENTE SUPER AUTÔNOMO com poderes expandidos. O AIO Sandbox está conectado e pronto para uso. Isso significa que você tem acesso a um ambiente completo e isolado para executar ações reais no mundo digital.

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
  2. Se o browser demorar, tente usar curl/wget via shell como alternativa
  3. Se um comando der timeout, tente uma versão mais simples ou direta
  4. Use shell para operações rápidas e browser apenas quando necessário
  5. Informar o usuário apenas se TODAS as alternativas falharem, explicando o que tentou

• OTIMIZAÇÃO DE PERFORMANCE: Prefira abordagens rápidas:
  - Use curl/wget via shell em vez de browser para buscar dados de APIs e sites simples
  - Divida scripts Python longos em execuções menores
  - Para pesquisas, prefira shell com curl a navegar com browser (é mais rápido)
  - Use browser apenas para sites que exigem interação (login, JS dinâmico, screenshots)

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
LEMBRE-SE: Você é um agente AUTÔNOMO e CAPAZ. Use seus poderes com confiança e responsabilidade. O sandbox é seu ambiente seguro — explore sem medo.
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
        jid_destino=None
    ) -> Dict[str, Any]:
        """
        Baixa um arquivo do AIO Sandbox via SDK e envia ao usuário via WhatsApp.
        Usa file.download_file do SDK (direto, sem base64 via shell).
        """
        import os
        from sandbox_mcp.sandbox_service import SandboxService
        
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
            print(f"📎 [SANDBOX-SDK] Baixando arquivo: {file_path}")
            
            # Baixar arquivo diretamente via SDK
            file_bytes = await SandboxService.baixar_arquivo(agente_id, file_path)
            
            if not file_bytes:
                return {
                    "resultado": {"erro": f"Arquivo não encontrado ou erro ao baixar: {file_path}"},
                    "output": "llm",
                    "enviado_usuario": False
                }
            
            file_size_kb = len(file_bytes) / 1024
            print(f"📎 [SANDBOX-SDK] Arquivo baixado: {filename} ({file_size_kb:.1f} KB)")
            
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
            
            if ext in IMAGE_EXTS:
                print(f"🖼️  [SANDBOX] Enviando como imagem...")
                cliente.send_image(jid, file_bytes, caption=caption)
                tipo_envio = "imagem"
            elif ext in AUDIO_EXTS:
                print(f"🎵 [SANDBOX] Enviando como áudio...")
                cliente.send_audio(jid, file_bytes, ptt=False)
                tipo_envio = "áudio"
            elif ext in VIDEO_EXTS:
                print(f"🎬 [SANDBOX] Enviando como vídeo...")
                cliente.send_video(jid, file_bytes, caption=caption)
                tipo_envio = "vídeo"
            else:
                print(f"📄 [SANDBOX] Enviando como documento...")
                cliente.send_document(
                    jid,
                    file_bytes,
                    filename=filename,
                    caption=caption,
                    mimetype=mime_type
                )
                tipo_envio = "documento"
            
            print(f"✅ [SANDBOX] Arquivo enviado com sucesso: {filename} ({tipo_envio})")
            
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
            print(f"❌ [SANDBOX] Erro ao enviar arquivo: {e}")
            import traceback
            traceback.print_exc()
            return {
                "resultado": {"erro": f"Erro ao enviar arquivo: {str(e)}"},
                "output": "llm",
                "enviado_usuario": False
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
            
            print(f"🔍 [SDK→WA] Imagem detectada: {len(image_b64)} chars base64")
            img_bytes = base64.b64decode(image_b64)
            mime = resultado.get("mime_type", "image/png")
            size_kb = len(img_bytes) / 1024
            
            from sessao.sessao_service import gerenciador_sessoes
            
            cliente = gerenciador_sessoes.obter_cliente(sessao_id)
            if not cliente:
                print(f"❌ [SDK→WA] Cliente WhatsApp não encontrado para sessão {sessao_id}")
                resultado_completo = dict(resultado_completo)
                resultado_completo["resultado"] = {
                    "type": "image",
                    "message": "[Screenshot capturado mas cliente WA indisponível]",
                    "size_kb": round(size_kb, 1)
                }
                return resultado_completo
            
            # Usar JID resolvido se disponível (suporta formato LID)
            if jid_destino is not None:
                jid = jid_destino
            else:
                from neonize.utils import build_jid
                jid = build_jid(telefone_cliente)
            
            print(f"🖼️  [SDK→WA] Enviando imagem {size_kb:.0f}KB ({mime}) para {jid}...")
            cliente.send_image(jid, img_bytes, caption="")
            print(f"✅ [SDK→WA] Imagem enviada com sucesso ({size_kb:.0f} KB)")
            
            # Substituir base64 por resumo leve para o LLM
            resultado_completo = dict(resultado_completo)
            resultado_completo["resultado"] = {
                "type": "image",
                "message": f"[Screenshot {size_kb:.0f}KB enviado ao usuário via WhatsApp]",
                "size_kb": round(size_kb, 1)
            }
            resultado_completo["enviado_usuario"] = True
            return resultado_completo
        
        except Exception as e:
            print(f"❌ [SDK→WA] Erro na interceptação de imagem: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return resultado_completo

    @staticmethod
    async def _enviar_screenshot_sandbox(
        sessao_id: int,
        telefone_cliente: str,
        agente_id: int,
        args: Dict[str, Any],
        jid_destino=None
    ) -> Dict[str, Any]:
        """
        Tira um screenshot do sandbox e envia diretamente ao usuário via WhatsApp.
        Tool virtual: enviar_screenshot_whatsapp.
        """
        from sandbox_mcp.sandbox_service import SandboxService
        
        tipo = args.get("tipo", "pagina")
        full_page = args.get("full_page", False)
        caption = args.get("caption", "")
        
        try:
            print(f"📸 [SANDBOX-SDK] Tirando screenshot tipo='{tipo}', full_page={full_page}")
            
            if tipo == "tela":
                img_bytes = await SandboxService.tirar_screenshot(agente_id)
            else:
                img_bytes = await SandboxService.tirar_screenshot_pagina(agente_id, full_page=full_page)
            
            if not img_bytes:
                return {
                    "resultado": {"erro": "Falha ao capturar screenshot do sandbox"},
                    "output": "llm",
                    "enviado_usuario": False
                }
            
            size_kb = len(img_bytes) / 1024
            print(f"📸 [SANDBOX-SDK] Screenshot capturado: {size_kb:.1f} KB")
            
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
            
            cliente.send_image(jid, img_bytes, caption=caption)
            print(f"✅ [SANDBOX-SDK] Screenshot enviado via WhatsApp ({size_kb:.1f} KB)")
            
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
            print(f"❌ [SANDBOX-SDK] Erro ao enviar screenshot: {e}")
            import traceback
            traceback.print_exc()
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
            db, "openrouter_modelo_padrao", "google/gemini-2.0-flash-001"
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
        
        # Construir system prompt
        system_prompt = AgenteService.construir_system_prompt(agente)
        
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
            
            # Ignorar preset aio-sandbox (agora controlado pelo toggle sandbox_ativo)
            if mcp_client.preset_key == "aio-sandbox":
                continue
            
            # Outros presets MCP continuam funcionando normalmente
            mcp_tools = MCPService.listar_tools_ativas(db, mcp_client.id)
            for mcp_tool in mcp_tools:
                if tools is None:
                    tools = []
                tool_openai = MCPService.converter_mcp_tool_para_openai(mcp_client, mcp_tool)
                tools.append(tool_openai)
        
        # Injetar tools do AIO Sandbox via SDK direto (controlado pelo toggle)
        if agente.sandbox_ativo:
            from sandbox_mcp.sandbox_service import SandboxService
            from sandbox_mcp.sandbox_tools import obter_sandbox_tools
            
            # Conectar SDK se ainda não conectado
            if not SandboxService.obter_cliente(agente.id):
                sdk_url = agente.sandbox_url or ConfiguracaoService.obter_valor(
                    db, "sandbox_sdk_url", "http://fluxi-sandbox:8080"
                )
                SandboxService.conectar(agente.id, sdk_url)
            
            # Injetar prompt + tools do sandbox
            system_prompt += AgenteService._prompt_aio_sandbox()
            if tools is None:
                tools = []
            tools.extend(obter_sandbox_tools())

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
        
        # Variáveis de controle
        tokens_input_total = 0
        tokens_output_total = 0
        ferramentas_usadas = []
        texto_resposta_final = ""
        if agente.sandbox_ativo:
            max_iteracoes = ConfiguracaoService.obter_valor(db, "agente_max_iteracoes_sandbox", 25)
        else:
            max_iteracoes = ConfiguracaoService.obter_valor(db, "agente_max_iteracoes_loop", 10)
        iteracao = 0
        
        # Loop principal de processamento
        try:
            while iteracao < max_iteracoes:
                iteracao += 1
                print(f"🔄 [AGENTE] Iteração {iteracao}/{max_iteracoes}")
                
                # Usar o novo sistema de integração LLM
                print(f"📡 [AGENTE] Chamando LLM com {len(messages)} mensagens...")
                resultado = await LLMIntegrationService.processar_mensagem_com_llm(
                    db=db,
                    messages=messages,
                    modelo=modelo,
                    agente_id=agente.id,
                    temperatura=temperatura,
                    max_tokens=max_tokens,
                    top_p=top_p,
                    frequency_penalty=frequency_penalty,
                    presence_penalty=presence_penalty,
                    tools=tools,
                    stream=False
                )
                print(resultado)
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
                print(f"✅ [AGENTE] LLM respondeu. finish_reason={finish_reason}")
                
                # Verificar se há tool calls
                tool_calls = message_response.get("tool_calls")
               
                if tool_calls and finish_reason == "tool_calls":
                    print(f"🔧 [AGENTE] LLM chamou {len(tool_calls)} tool(s)")
                    # Processar todas as ferramentas em paralelo
                    for tool_call in tool_calls:
                        function_name = tool_call.get("function", {}).get("name")
                        function_args = tool_call.get("function", {}).get("arguments")
                        args_dict = json.loads(function_args) if isinstance(function_args, str) else function_args
                        
                        # Detectar se é ferramenta do Sandbox SDK (prefixo sandbox_)
                        if function_name.startswith("sandbox_") and agente.sandbox_ativo:
                            try:
                                from sandbox_mcp.sandbox_service import SandboxService
                                print(f"🚀 [AGENTE] Executando tool Sandbox SDK: {function_name}")
                                resultado_completo = await SandboxService.executar_tool(
                                    db, agente.id, function_name, args_dict
                                )
                                print(f"✅ [AGENTE] Tool Sandbox SDK executada: {resultado_completo.get('tempo_ms', 0)}ms")
                            except Exception as e:
                                print(f"❌ [AGENTE] Erro ao executar tool Sandbox SDK: {str(e)}")
                                resultado_completo = {
                                    "resultado": {"erro": f"Erro ao executar tool Sandbox: {str(e)}"},
                                    "output": "llm",
                                    "enviado_usuario": False
                                }
                        
                        # Detectar se é ferramenta MCP (prefixo mcp_) — presets não-sandbox
                        elif function_name.startswith("mcp_"):
                            try:
                                parts = function_name.split("_", 2)
                                mcp_client_id = int(parts[1])
                                original_tool_name = parts[2]
                                
                                print(f"🌐 [AGENTE] Executando tool MCP: {original_tool_name} (client {mcp_client_id})")
                                resultado_completo = await MCPService.executar_tool_mcp(
                                    db, mcp_client_id, original_tool_name, args_dict
                                )
                                print(f"✅ [AGENTE] Tool MCP executada com sucesso: {resultado_completo.get('tempo_ms', 0)}ms")
                            except Exception as e:
                                print(f"❌ [AGENTE] Erro ao executar tool MCP: {str(e)}")
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
                                        "fonte": r.get("metadata", {}).get("source", ""),
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
                                resultado_completo = {
                                    "resultado": {"erro": f"Erro ao buscar: {str(e)}"},
                                    "output": "llm"
                                }
                        # Enviar arquivo do sandbox para o usuário via WhatsApp
                        elif function_name == "enviar_arquivo_whatsapp" and agente.sandbox_ativo:
                            resultado_completo = await AgenteService._enviar_arquivo_sandbox(
                                db=db,
                                sessao_id=sessao.id,
                                telefone_cliente=mensagem.telefone_cliente,
                                agente_id=agente.id,
                                args=args_dict,
                                jid_destino=jid_destino
                            )
                        
                        # Enviar screenshot do sandbox via WhatsApp
                        elif function_name == "enviar_screenshot_whatsapp" and agente.sandbox_ativo:
                            resultado_completo = await AgenteService._enviar_screenshot_sandbox(
                                sessao_id=sessao.id,
                                telefone_cliente=mensagem.telefone_cliente,
                                agente_id=agente.id,
                                args=args_dict,
                                jid_destino=jid_destino
                            )
                        
                        else:
                            # Executar ferramenta normal do banco
                            resultado_completo = await FerramentaService.executar_ferramenta(
                                db,
                                function_name,
                                args_dict,
                                sessao_id=sessao.id,
                                telefone_cliente=mensagem.telefone_cliente
                            )
                        
                        # Interceptar imagens em resultados sandbox SDK e enviar direto ao WhatsApp
                        if agente.sandbox_ativo and function_name.startswith("sandbox_"):
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
                            print(f"📤 [AGENTE] Conteúdo enviado ao LLM (primeiros 500 chars): {conteudo_tool[:500]}")
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.get("id"),
                                "content": conteudo_tool
                            })
                            print(f"📝 [AGENTE] Resultado da tool adicionado ao histórico (output={output_type})")
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
                            print(f"📝 [AGENTE] Resultado enviado ao usuário (output={output_type})")
                    
                    # Continuar o loop para processar os resultados das ferramentas
                    print(f"🔁 [AGENTE] Todas as {len(tool_calls)} tool(s) processadas. Voltando ao LLM...")
                    continue
                else:
                    # Não há tool calls - resposta final (texto)
                    texto_resposta_final = message_response.get("content", "")
                    print(f"✅ [AGENTE] Resposta final recebida: {len(texto_resposta_final)} caracteres")
                    break
            
            # Calcular tempo total
            tempo_ms = int((time.time() - inicio) * 1000)
            
            print(f"🎯 [AGENTE] Processamento concluído em {tempo_ms}ms")
            return {
                "texto": texto_resposta_final,
                "tokens_input": tokens_input_total,
                "tokens_output": tokens_output_total,
                "tempo_ms": tempo_ms,
                "modelo": modelo,
                "ferramentas": ferramentas_usadas if ferramentas_usadas else None
            }
                
        except httpx.TimeoutException:
            print(f"❌ [AGENTE] Timeout ao conectar com OpenRouter")
            raise ValueError("Timeout ao conectar com OpenRouter")
        except Exception as e:
            print(f"❌ [AGENTE] Exceção capturada: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            raise ValueError(f"Erro ao processar com LLM: {str(e)}")
