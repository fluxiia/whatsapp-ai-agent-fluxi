"""
Serviço de lógica de negócio para ferramentas.
"""
import logging
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
import json
import re
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)
from ferramenta.ferramenta_model import Ferramenta, ToolType, ToolScope
from ferramenta.ferramenta_schema import FerramentaCriar, FerramentaAtualizar
from config.config_service import ConfiguracaoService

# Registry de handlers NATIVE: {nome_tool -> async callable(db, argumentos) -> dict}
# Populado no final deste arquivo após definir os handlers.
NATIVE_REGISTRY: Dict[str, Any] = {}


class FerramentaService:
    """Serviço para gerenciar ferramentas."""

    @staticmethod
    def listar_todas(db: Session) -> List[Ferramenta]:
        """Lista todas as ferramentas."""
        return db.query(Ferramenta).all()

    @staticmethod
    def listar_ferramentas_ativas(db: Session) -> List[Ferramenta]:
        """Lista ferramentas ativas."""
        return db.query(Ferramenta).filter(Ferramenta.ativa == True).all()

    @staticmethod
    def obter_por_id(db: Session, ferramenta_id: int) -> Optional[Ferramenta]:
        """Obtém uma ferramenta pelo ID."""
        return db.query(Ferramenta).filter(Ferramenta.id == ferramenta_id).first()

    @staticmethod
    def obter_por_nome(db: Session, nome: str) -> Optional[Ferramenta]:
        """Obtém uma ferramenta pelo nome."""
        return db.query(Ferramenta).filter(Ferramenta.nome == nome).first()

    @staticmethod
    def criar(db: Session, ferramenta: FerramentaCriar) -> Ferramenta:
        """Cria uma nova ferramenta."""
        db_ferramenta = Ferramenta(**ferramenta.model_dump())
        db.add(db_ferramenta)
        db.commit()
        db.refresh(db_ferramenta)
        return db_ferramenta

    @staticmethod
    def atualizar(db: Session, ferramenta_id: int, ferramenta: FerramentaAtualizar) -> Optional[Ferramenta]:
        """Atualiza uma ferramenta existente."""
        db_ferramenta = FerramentaService.obter_por_id(db, ferramenta_id)
        if not db_ferramenta:
            return None

        update_data = ferramenta.model_dump(exclude_unset=True)
        
        for campo, valor in update_data.items():
            setattr(db_ferramenta, campo, valor)

        db.commit()
        db.refresh(db_ferramenta)
        return db_ferramenta

    @staticmethod
    def deletar(db: Session, ferramenta_id: int) -> bool:
        """Deleta uma ferramenta."""
        db_ferramenta = FerramentaService.obter_por_id(db, ferramenta_id)
        if not db_ferramenta:
            return False

        db.delete(db_ferramenta)
        db.commit()
        return True

    @staticmethod
    def substituir_variaveis(
        texto: str,
        variaveis: Dict[str, Any],
        variaveis_ferramenta: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Substitui variáveis no formato {variavel}, {var.CHAVE} ou {resultado.campo}.

        Ordem de prioridade:
        1. {var.CHAVE}      - Variáveis da ferramenta (do banco)
        2. {variavel}       - Variáveis passadas como argumento
        3. {resultado.campo}- Variáveis aninhadas

        NOTA: Suporte a {env.VARIAVEL} foi removido por segurança — impedia vazamento
        de variáveis de ambiente (API keys, DATABASE_URL, etc.) via ferramentas maliciosas.
        Use {var.CHAVE} para injetar valores seguros cadastrados no banco.
        """
        def replacer(match):
            var_name = match.group(1)

            # 1. Variável da ferramenta (do banco)
            if var_name.startswith("var."):
                var_key = var_name[4:]
                if variaveis_ferramenta and var_key in variaveis_ferramenta:
                    return variaveis_ferramenta[var_key]
                return match.group(0)

            # 2. Bloquear explicitamente {env.*} — não expor variáveis de ambiente
            if var_name.startswith("env."):
                import logging as _log
                _log.getLogger(__name__).warning(
                    "Tentativa de acesso a variável de ambiente via {%s} bloqueada.", var_name
                )
                return match.group(0)

            # 3. Variável normal
            if var_name in variaveis:
                valor = variaveis[var_name]
                return str(valor) if not isinstance(valor, (dict, list)) else json.dumps(valor)

            # 4. Variável aninhada (ex: resultado.nome)
            if "." in var_name:
                parts = var_name.split(".")
                valor = variaveis
                for part in parts:
                    if isinstance(valor, dict) and part in valor:
                        valor = valor[part]
                    else:
                        return match.group(0)
                return str(valor) if not isinstance(valor, (dict, list)) else json.dumps(valor)

            return match.group(0)

        # Regex mais específico: captura apenas nomes de variáveis válidos (letras, números, _, .)
        return re.sub(r'\{([a-zA-Z_][a-zA-Z0-9_.]*)\}', replacer, texto)

    @staticmethod
    async def executar_ferramenta_web(
        ferramenta: Ferramenta,
        argumentos: Dict[str, Any],
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Executa uma ferramenta do tipo WEB (requisição HTTP).
        Usa CURL se disponível, senão usa campos individuais.
        """
        try:
            # Carregar variáveis da ferramenta do banco
            variaveis_ferramenta = {}
            if db:
                from ferramenta.ferramenta_variavel_service import FerramentaVariavelService
                variaveis_ferramenta = FerramentaVariavelService.obter_variaveis_como_dict(
                    db, ferramenta.id
                )
            
            # Se tem CURL, usar parser
            if hasattr(ferramenta, 'curl_command') and ferramenta.curl_command:
                from ferramenta.curl_parser import CurlParser
                
                # Substituir variáveis no CURL
                curl = ferramenta.curl_command
                curl = FerramentaService.substituir_variaveis(curl, argumentos, variaveis_ferramenta)
                
                # Parse CURL
                parsed = CurlParser.parse_curl(curl)
                
                # Executar requisição baseado no CURL parseado
                method = parsed.get('method', 'GET')
                url = parsed.get('url', '')
                headers = parsed.get('headers', {})
                query_params = parsed.get('query_params', {})
                body = parsed.get('body')
                
                # Obter timeout configurado
                timeout_http = ConfiguracaoService.obter_valor(db, "ferramenta_timeout_http", 30) if db else 30.0
                
                async with httpx.AsyncClient() as client:
                    if method == "GET":
                        response = await client.get(url, headers=headers, params=query_params, timeout=float(timeout_http))
                    elif method == "POST":
                        response = await client.post(url, headers=headers, params=query_params, json=json.loads(body) if body else None, timeout=float(timeout_http))
                    elif method == "PUT":
                        response = await client.put(url, headers=headers, params=query_params, json=json.loads(body) if body else None, timeout=float(timeout_http))
                    elif method == "PATCH":
                        response = await client.patch(url, headers=headers, params=query_params, json=json.loads(body) if body else None, timeout=float(timeout_http))
                    elif method == "DELETE":
                        response = await client.delete(url, headers=headers, params=query_params, timeout=float(timeout_http))
                    else:
                        return {"erro": f"Método HTTP '{method}' não suportado"}
                    
                    # Processar resposta
                    if response.status_code >= 400:
                        return {"erro": f"Erro HTTP {response.status_code}: {response.text}"}
                    
                    try:
                        resultado = response.json()
                    except:
                        resultado = {"resposta": response.text}
                    
                    # Aplicar mapeamento
                    if ferramenta.response_map:
                        response_map = json.loads(ferramenta.response_map)
                        resultado_mapeado = {}
                        for campo_origem, campo_destino in response_map.items():
                            if campo_origem in resultado:
                                resultado_mapeado[campo_destino] = resultado[campo_origem]
                        return resultado_mapeado
                    
                    return resultado
            
            # Se não tem CURL, retorna erro
            return {"erro": "Ferramenta WEB sem curl_command configurado"}
                
        except httpx.TimeoutException:
            return {"erro": "Timeout na requisição HTTP"}
        except Exception as e:
            return {"erro": f"Erro ao executar ferramenta web: {str(e)}"}

    @staticmethod
    async def executar_ferramenta_code(
        ferramenta: Ferramenta,
        argumentos: Dict[str, Any],
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Executa uma ferramenta do tipo CODE (código Python).
        """
        try:
            codigo = ferramenta.codigo_python
            if not codigo:
                return {"erro": "Ferramenta não possui código Python"}
            
            # Carregar variáveis da ferramenta do banco
            variaveis_ferramenta = {}
            if db:
                from ferramenta.ferramenta_variavel_service import FerramentaVariavelService
                variaveis_ferramenta = FerramentaVariavelService.obter_variaveis_como_dict(
                    db, ferramenta.id
                )
            
            # Substituir variáveis no código se necessário
            if ferramenta.substituir:
                codigo = FerramentaService.substituir_variaveis(
                    codigo, argumentos, variaveis_ferramenta
                )
            
            # Criar namespace para execução
            namespace = {
                "argumentos": argumentos,
                "resultado": None,
                "datetime": datetime,
                "json": json,
                "httpx": httpx
            }
            
            # Executar código
            exec(codigo, namespace)
            
            # Capturar resultado
            if ferramenta.print_output_var and ferramenta.print_output_var in namespace:
                return namespace[ferramenta.print_output_var]
            elif "resultado" in namespace and namespace["resultado"] is not None:
                return namespace["resultado"]
            else:
                return {"sucesso": True}
                
        except Exception as e:
            return {"erro": f"Erro ao executar código Python: {str(e)}"}

    @staticmethod
    async def executar_ferramenta(
        db: Session,
        nome_ferramenta: str,
        argumentos: Dict[str, Any],
        sessao_id: Optional[int] = None,
        telefone_cliente: Optional[str] = None,
        jid_destino=None,
    ) -> Dict[str, Any]:
        """
        Executa uma ferramenta com os argumentos fornecidos.
        Suporta ferramentas WEB e CODE.
        Retorna dict com: {"resultado": ..., "output": ..., "channel": ...}
        """
        ferramenta = FerramentaService.obter_por_nome(db, nome_ferramenta)
        if not ferramenta:
            return {"erro": f"Ferramenta '{nome_ferramenta}' não encontrada"}
        
        if not ferramenta.ativa:
            return {"erro": f"Ferramenta '{nome_ferramenta}' está desativada"}
        
        # Executar de acordo com o tipo
        if ferramenta.tool_type == ToolType.WEB:
            resultado = await FerramentaService.executar_ferramenta_web(ferramenta, argumentos, db)
        elif ferramenta.tool_type == ToolType.CODE:
            resultado = await FerramentaService.executar_ferramenta_code(ferramenta, argumentos, db)
        elif ferramenta.tool_type == ToolType.NATIVE:
            handler = NATIVE_REGISTRY.get(ferramenta.nome)
            if not handler:
                return {"erro": f"Handler nativo '{ferramenta.nome}' não registrado"}
            resultado = await handler(db, argumentos)
        else:
            return {"erro": f"Tipo de ferramenta '{ferramenta.tool_type}' não suportado"}
        
        # Normalizar resultado para garantir que seja um dict
        if not isinstance(resultado, dict):
            resultado = {"resultado": resultado}
        
        # Se há próxima ferramenta, executar em cadeia
        if ferramenta.next_tool and not resultado.get("erro"):
            # Mesclar resultado com argumentos para próxima ferramenta
            novos_argumentos = {**argumentos, "resultado": resultado}
            return await FerramentaService.executar_ferramenta(
                db, ferramenta.next_tool, novos_argumentos, sessao_id, telefone_cliente,
                jid_destino=jid_destino,
            )

        # Processar output da ferramenta
        return await FerramentaService.processar_output_ferramenta(
            db, ferramenta, resultado, sessao_id, telefone_cliente,
            jid_destino=jid_destino,
        )

    @staticmethod
    async def processar_output_ferramenta(
        db: Session,
        ferramenta: Ferramenta,
        resultado: Dict[str, Any],
        sessao_id: Optional[int] = None,
        telefone_cliente: Optional[str] = None,
        jid_destino=None,
    ) -> Dict[str, Any]:
        """
        Processa o output da ferramenta de acordo com as configurações.
        Envia para LLM, usuário ou ambos.
        """
        from ferramenta.ferramenta_model import OutputDestination, ChannelType
        
        # Normalizar resultado para garantir que seja um dict
        if not isinstance(resultado, dict):
            resultado = {"resultado": resultado}
        
        # Se houver erro, sempre retorna para o LLM
        if resultado.get("erro"):
            return {
                "resultado": resultado,
                "output": "llm",
                "enviado_usuario": False
            }
        
        output_config = ferramenta.output
        enviado_usuario = False
        
        # Enviar para usuário se configurado
        if output_config in [OutputDestination.USER, OutputDestination.BOTH]:
            if sessao_id and telefone_cliente:
                try:
                    enviado_usuario = await FerramentaService.enviar_para_usuario(
                        db, ferramenta, resultado, sessao_id, telefone_cliente,
                        jid_destino=jid_destino,
                    )
                except Exception as e:
                    logger.exception("Erro ao enviar para usuário: %s", e)
                    resultado["erro_envio"] = str(e)
        
        # Retornar informações sobre o processamento
        return {
            "resultado": resultado,
            "output": ferramenta.output.value,
            "channel": ferramenta.channel.value if ferramenta.channel else None,
            "enviado_usuario": enviado_usuario,
            "post_instruction": ferramenta.post_instruction
        }
    
    @staticmethod
    async def enviar_para_usuario(
        db: Session,
        ferramenta: Ferramenta,
        resultado: Dict[str, Any],
        sessao_id: int,
        telefone_cliente: str,
        jid_destino=None,
    ) -> bool:
        """
        Envia o resultado da ferramenta para o usuário via WhatsApp.
        Suporta diferentes tipos de canal (text, image, audio, video, document).
        Usa jid_destino resolvido (que preserva LID/@lid) se disponível.
        """
        from sessao.sessao_service import gerenciador_sessoes
        from neonize.utils import build_jid
        from ferramenta.ferramenta_model import ChannelType

        cliente = gerenciador_sessoes.obter_cliente(sessao_id)
        if not cliente:
            logger.warning("Cliente WhatsApp não encontrado para sessão %s", sessao_id)
            return False

        # Usa JID resolvido se disponível (correto para LID e s.whatsapp.net)
        # Fallback para build_jid(telefone) quando chamado de contextos sem resolver
        jid = jid_destino if jid_destino is not None else build_jid(telefone_cliente)
        channel = ferramenta.channel or ChannelType.TEXT

        try:
            if channel == ChannelType.TEXT:
                texto = FerramentaService.formatar_resultado_texto(resultado, ferramenta)
                cliente.send_message(jid, message=texto)
                logger.debug("Texto enviado para sessão %s", sessao_id)
                return True
            elif channel == ChannelType.IMAGE:
                return await FerramentaService.enviar_imagem(cliente, jid, resultado, ferramenta)
            elif channel == ChannelType.AUDIO:
                return await FerramentaService.enviar_audio(cliente, jid, resultado, ferramenta)
            elif channel == ChannelType.VIDEO:
                return await FerramentaService.enviar_video(cliente, jid, resultado, ferramenta)
            elif channel == ChannelType.DOCUMENT:
                return await FerramentaService.enviar_documento(cliente, jid, resultado, ferramenta)
            return False

        except Exception as e:
            logger.exception("Erro ao enviar para usuário (sessão %s): %s", sessao_id, e)
            return False
    
    @staticmethod
    def formatar_resultado_texto(resultado: Dict[str, Any], ferramenta: Ferramenta) -> str:
        """
        Formata o resultado da ferramenta como texto.
        Se houver post_instruction, usa para formatar.
        """
        # Se o resultado já é uma string, retornar diretamente
        if isinstance(resultado, str):
            return resultado
        
        # Se tem um campo 'mensagem' ou 'texto', usar
        if "mensagem" in resultado:
            return str(resultado["mensagem"])
        if "texto" in resultado:
            return str(resultado["texto"])
        
        # Se tem post_instruction, usar como template
        if ferramenta.post_instruction:
            try:
                # Substituir variáveis na post_instruction
                texto = FerramentaService.substituir_variaveis(
                    ferramenta.post_instruction,
                    resultado
                )
                return texto
            except:
                pass
        
        # Caso contrário, formatar como JSON
        return json.dumps(resultado, ensure_ascii=False, indent=2)
    
    @staticmethod
    async def enviar_imagem(
        cliente,
        jid,
        resultado: Dict[str, Any],
        ferramenta: Ferramenta
    ) -> bool:
        """
        Envia uma imagem para o usuário.
        Resultado pode conter: url, base64, path
        """
        try:
            import base64
            
            # Obter dados da imagem
            imagem_data = None
            caption = resultado.get("caption", "")
            
            if "url" in resultado:
                # Baixar imagem da URL
                async with httpx.AsyncClient() as client:
                    response = await client.get(resultado["url"], timeout=30.0)  # Imagens usam timeout menor
                    if response.status_code == 200:
                        imagem_data = response.content
            
            elif "base64" in resultado:
                # Decodificar base64
                imagem_data = base64.b64decode(resultado["base64"])
            
            elif "path" in resultado:
                # Ler arquivo local
                with open(resultado["path"], "rb") as f:
                    imagem_data = f.read()
            
            if imagem_data:
                cliente.send_image(jid, imagem_data, caption=caption)
                logger.debug("Imagem enviada com sucesso")
                return True

            return False

        except Exception as e:
            logger.exception("Erro ao enviar imagem: %s", e)
            return False
    
    @staticmethod
    async def enviar_audio(
        cliente,
        jid,
        resultado: Dict[str, Any],
        ferramenta: Ferramenta
    ) -> bool:
        """
        Envia um áudio para o usuário.
        """
        try:
            import base64
            
            audio_data = None
            
            if "url" in resultado:
                async with httpx.AsyncClient() as client:
                    response = await client.get(resultado["url"], timeout=30.0)  # Áudio usa timeout menor
                    if response.status_code == 200:
                        audio_data = response.content
            
            elif "base64" in resultado:
                audio_data = base64.b64decode(resultado["base64"])
            
            elif "path" in resultado:
                with open(resultado["path"], "rb") as f:
                    audio_data = f.read()
            
            if audio_data:
                cliente.send_audio(jid, audio_data, ptt=resultado.get("ptt", False))
                logger.debug("Áudio enviado com sucesso")
                return True

            return False

        except Exception as e:
            logger.exception("Erro ao enviar áudio: %s", e)
            return False
    
    @staticmethod
    async def enviar_video(
        cliente,
        jid,
        resultado: Dict[str, Any],
        ferramenta: Ferramenta
    ) -> bool:
        """
        Envia um vídeo para o usuário.
        """
        try:
            import base64
            
            video_data = None
            caption = resultado.get("caption", "")
            
            if "url" in resultado:
                # Timeout maior para vídeos (configurável)
                from database import SessionLocal
                db_temp = SessionLocal()
                try:
                    timeout_download = ConfiguracaoService.obter_valor(db_temp, "ferramenta_timeout_download", 60)
                finally:
                    db_temp.close()
                async with httpx.AsyncClient() as client:
                    response = await client.get(resultado["url"], timeout=float(timeout_download))
                    if response.status_code == 200:
                        video_data = response.content
            
            elif "base64" in resultado:
                video_data = base64.b64decode(resultado["base64"])
            
            elif "path" in resultado:
                with open(resultado["path"], "rb") as f:
                    video_data = f.read()
            
            if video_data:
                cliente.send_video(
                    jid,
                    video_data,
                    caption=caption
                )
                logger.debug("Vídeo enviado com sucesso")
                return True

            return False

        except Exception as e:
            logger.exception("Erro ao enviar vídeo: %s", e)
            return False
    
    @staticmethod
    async def enviar_documento(
        cliente,
        jid,
        resultado: Dict[str, Any],
        ferramenta: Ferramenta
    ) -> bool:
        """
        Envia um documento para o usuário.
        """
        try:
            import base64
            
            doc_data = None
            filename = resultado.get("filename", "document.pdf")
            caption = resultado.get("caption", "")
            
            if "url" in resultado:
                # Timeout maior para documentos (configurável)
                from database import SessionLocal
                db_temp = SessionLocal()
                try:
                    timeout_download = ConfiguracaoService.obter_valor(db_temp, "ferramenta_timeout_download", 60)
                finally:
                    db_temp.close()
                async with httpx.AsyncClient() as client:
                    response = await client.get(resultado["url"], timeout=float(timeout_download))
                    if response.status_code == 200:
                        doc_data = response.content
            
            elif "base64" in resultado:
                doc_data = base64.b64decode(resultado["base64"])
            
            elif "path" in resultado:
                with open(resultado["path"], "rb") as f:
                    doc_data = f.read()
            
            if doc_data:
                cliente.send_document(
                    jid,
                    doc_data,
                    filename=filename,
                    caption=caption,
                    mimetype=resultado.get("mime_type", "application/pdf")
                )
                logger.debug("Documento '%s' enviado com sucesso", filename)
                return True

            return False

        except Exception as e:
            logger.exception("Erro ao enviar documento: %s", e)
            return False
    
    @staticmethod
    def converter_para_openai_format(ferramenta: Ferramenta) -> Dict[str, Any]:
        """
        Converte uma ferramenta do banco para o formato OpenAI.
        Apenas ferramentas com tool_scope=PRINCIPAL são convertidas.
        """
        if ferramenta.tool_scope != ToolScope.PRINCIPAL:
            return None
        
        # Construir parameters a partir do campo params
        parameters = {
            "type": "object",
            "properties": {},
            "required": []
        }
        
        if ferramenta.params:
            try:
                params_dict = json.loads(ferramenta.params)
                for param_name, param_config in params_dict.items():
                    param_type = param_config.get("type", "string")
                    param_desc = param_config.get("description", "")
                    param_required = param_config.get("required", False)
                    
                    # Construir property
                    prop = {"type": param_type}
                    if param_desc:
                        prop["description"] = param_desc
                    
                    # Se for enum, adicionar options
                    if param_type == "enum":
                        prop["type"] = "string"
                        if "options" in param_config:
                            prop["enum"] = param_config["options"]
                    
                    # Se for array, adicionar items
                    if param_type == "array":
                        prop["items"] = {"type": param_config.get("item_type", "string")}
                    
                    parameters["properties"][param_name] = prop
                    
                    if param_required:
                        parameters["required"].append(param_name)
            except json.JSONDecodeError:
                pass
        
        return {
            "type": "function",
            "function": {
                "name": ferramenta.nome,
                "description": ferramenta.descricao,
                "parameters": parameters
            }
        }

    @staticmethod
    def criar_ferramentas_padrao(db: Session):
        """Cria ferramentas padrão do sistema usando novo formato."""
        ferramentas_padrao = [
            # ── Utilitários ──
            {
                "nome": "obter_data_hora_atual",
                "descricao": "Obtém a data e hora atual no formato brasileiro",
                "tool_type": ToolType.CODE,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({}),
                "codigo_python": """
from datetime import datetime
resultado = {
    "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    "data": datetime.now().strftime("%d/%m/%Y"),
    "hora": datetime.now().strftime("%H:%M:%S"),
    "dia_semana": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][datetime.now().weekday()]
}
""",
                "substituir": False,
                "output": "llm",
                "ativa": True
            },
            {
                "nome": "calcular",
                "descricao": "Realiza cálculos matemáticos. Suporta operações básicas: +, -, *, /, ** (potência)",
                "tool_type": ToolType.CODE,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "expressao": {
                        "type": "string",
                        "required": True,
                        "description": "Expressão matemática para calcular (ex: '2 + 2', '10 * 5', '2 ** 3')"
                    }
                }),
                "codigo_python": """
try:
    expressao = argumentos.get("expressao", "")
    allowed_chars = set("0123456789+-*/().** ")
    if all(c in allowed_chars for c in expressao):
        resultado_calculo = eval(expressao)
        resultado = {"expressao": expressao, "resultado": resultado_calculo}
    else:
        resultado = {"erro": "Expressão contém caracteres não permitidos"}
except Exception as e:
    resultado = {"erro": f"Erro ao calcular: {str(e)}"}
""",
                "substituir": False,
                "output": "llm",
                "ativa": True
            },
            {
                "nome": "gerar_senha",
                "descricao": "Gera uma senha aleatória segura com comprimento personalizável",
                "tool_type": ToolType.CODE,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "tamanho": {
                        "type": "integer",
                        "required": False,
                        "description": "Comprimento da senha (padrão: 12, mínimo: 6)"
                    },
                    "incluir_simbolos": {
                        "type": "boolean",
                        "required": False,
                        "description": "Se deve incluir símbolos especiais (padrão: true)"
                    }
                }),
                "codigo_python": """
import random, string
tamanho = max(6, argumentos.get("tamanho", 12))
incluir_simbolos = argumentos.get("incluir_simbolos", True)
caracteres = string.ascii_letters + string.digits
if incluir_simbolos:
    caracteres += "!@#$%&*+-=?"
senha = "".join(random.choice(caracteres) for _ in range(tamanho))
resultado = {"senha": senha, "tamanho": tamanho, "inclui_simbolos": incluir_simbolos}
""",
                "substituir": False,
                "output": "llm",
                "ativa": True
            },
            # ── Busca e Informação ──
            {
                "nome": "buscar_internet",
                "descricao": "Busca informações na internet usando DuckDuckGo. Retorna os resultados mais relevantes com títulos, links e descrições.",
                "tool_type": ToolType.WEB,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "query": {
                        "type": "string",
                        "required": True,
                        "description": "Termo de busca (ex: 'receita de bolo', 'preço do dólar hoje')"
                    }
                }),
                "curl_command": "curl -s 'https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1'",
                "substituir": True,
                "output": "llm",
                "post_instruction": "Apresente os resultados de forma organizada. Inclua títulos e descrições relevantes. Se houver um Abstract, apresente como destaque.",
                "ativa": True
            },
            {
                "nome": "buscar_noticias",
                "descricao": "Busca notícias recentes sobre um tema usando a API GNews. Retorna manchetes, fontes e links.",
                "tool_type": ToolType.WEB,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "tema": {
                        "type": "string",
                        "required": True,
                        "description": "Tema ou assunto para buscar notícias (ex: 'tecnologia', 'economia Brasil')"
                    },
                    "max_resultados": {
                        "type": "integer",
                        "required": False,
                        "description": "Número máximo de notícias (padrão: 5, máximo: 10)"
                    }
                }),
                "curl_command": "curl -s 'https://gnews.io/api/v4/search?q={tema}&lang=pt&country=br&max={max_resultados}&apikey=demo'",
                "substituir": True,
                "output": "llm",
                "post_instruction": "Apresente as notícias em formato de lista com: título, fonte e data. Se a API retornar erro de limite, informe que o serviço está temporariamente indisponível e sugira buscar diretamente na internet.",
                "ativa": True
            },
            {
                "nome": "buscar_wikipedia",
                "descricao": "Busca um resumo sobre um tema na Wikipedia em português. Ideal para definições, biografias e explicações enciclopédicas.",
                "tool_type": ToolType.WEB,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "tema": {
                        "type": "string",
                        "required": True,
                        "description": "Termo ou assunto para buscar na Wikipedia (ex: 'inteligência artificial', 'Brasil')"
                    }
                }),
                "curl_command": "curl -s 'https://pt.wikipedia.org/api/rest_v1/page/summary/{tema}'",
                "substituir": True,
                "output": "llm",
                "post_instruction": "Apresente o resumo de forma clara. Se houver uma imagem thumbnail, mencione que está disponível. Se o resultado indicar que a página não existe, sugira termos alternativos.",
                "ativa": True
            },
            # ── Clima e Localização ──
            {
                "nome": "previsao_tempo",
                "descricao": "Obtém a previsão do tempo atual para uma cidade. Retorna temperatura, umidade, vento e descrição do clima.",
                "tool_type": ToolType.WEB,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "cidade": {
                        "type": "string",
                        "required": True,
                        "description": "Nome da cidade (ex: 'São Paulo', 'Rio de Janeiro', 'Curitiba')"
                    }
                }),
                "curl_command": "curl -s 'https://wttr.in/{cidade}?format=j1&lang=pt'",
                "substituir": True,
                "output": "llm",
                "post_instruction": "Apresente a previsão de forma amigável: temperatura atual, sensação térmica, umidade, vento e descrição do clima. Use linguagem natural, não apenas dados brutos.",
                "ativa": True
            },
            {
                "nome": "buscar_cep",
                "descricao": "Busca endereço completo a partir de um CEP brasileiro usando a API ViaCEP.",
                "tool_type": ToolType.WEB,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "cep": {
                        "type": "string",
                        "required": True,
                        "description": "CEP para buscar (ex: '01001000', '01001-000')"
                    }
                }),
                "curl_command": "curl -s 'https://viacep.com.br/ws/{cep}/json/'",
                "substituir": True,
                "output": "llm",
                "post_instruction": "Apresente o endereço completo de forma organizada: rua, bairro, cidade, estado e CEP. Se houver erro, informe que o CEP pode ser inválido.",
                "ativa": True
            },
            # ── Finanças ──
            {
                "nome": "cotacao_moeda",
                "descricao": "Obtém cotações de moedas em tempo real (dólar, euro, etc.) contra o Real brasileiro.",
                "tool_type": ToolType.WEB,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "moeda": {
                        "type": "string",
                        "required": False,
                        "description": "Código da moeda (ex: 'USD', 'EUR', 'GBP', 'JPY'). Se vazio, retorna as principais."
                    }
                }),
                "curl_command": "curl -s 'https://api.exchangerate-api.com/v4/latest/BRL'",
                "substituir": True,
                "output": "llm",
                "post_instruction": "Apresente as cotações de forma clara. Para cada moeda, mostre quanto custa 1 unidade em Reais (BRL). Ex: 1 USD = R$ 5,12. Se uma moeda específica foi pedida, destaque-a. As taxas são inversas (1 BRL = X USD), então calcule o inverso para mostrar quanto custa a moeda em Reais.",
                "ativa": True
            },
            # ── Tradução ──
            {
                "nome": "traduzir_texto",
                "descricao": "Traduz um texto entre idiomas usando MyMemory API (gratuita, sem chave).",
                "tool_type": ToolType.WEB,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "texto": {
                        "type": "string",
                        "required": True,
                        "description": "Texto para traduzir"
                    },
                    "idioma_origem": {
                        "type": "string",
                        "required": False,
                        "description": "Código do idioma de origem (padrão: 'pt' para português)"
                    },
                    "idioma_destino": {
                        "type": "string",
                        "required": True,
                        "description": "Código do idioma de destino (ex: 'en' para inglês, 'es' para espanhol, 'fr' para francês)"
                    }
                }),
                "curl_command": "curl -s 'https://api.mymemory.translated.net/get?q={texto}&langpair={idioma_origem}%7C{idioma_destino}'",
                "substituir": True,
                "output": "llm",
                "post_instruction": "Apresente a tradução de forma direta. Se houver alternativas, mostre-as. Se a API retornar erro de limite diário, informe que o serviço atingiu o limite gratuito.",
                "ativa": True
            },
            # ── Meta — auto-modificação do sistema ──
            {
                "nome": "fluxi_ferramentas",
                "descricao": (
                    "Gerencia ferramentas (tools) do sistema Fluxi. "
                    "Use para criar novas ferramentas CODE ou WEB, editar ferramentas existentes, "
                    "associar/desassociar ferramentas de agentes, ou listar as ferramentas disponíveis. "
                    "Invoque a skill 'meta_ferramentas' antes de usar para obter o schema JSON completo."
                ),
                "tool_type": ToolType.CODE,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "acao": {
                        "type": "enum",
                        "required": True,
                        "description": "Ação a executar",
                        "options": ["listar", "criar", "editar", "deletar", "associar_agente", "desassociar_agente", "listar_agente", "definir_variaveis", "listar_variaveis"]
                    },
                    "ferramenta_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID da ferramenta (obrigatório para editar, deletar, associar_agente, desassociar_agente, definir_variaveis, listar_variaveis)"
                    },
                    "agente_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID do agente (obrigatório para associar_agente, desassociar_agente, listar_agente)"
                    },
                    "dados": {
                        "type": "string",
                        "required": False,
                        "description": "JSON com os campos da ferramenta. Obrigatório para criar e editar. Invoque meta_ferramentas para ver o schema completo."
                    },
                    "variaveis": {
                        "type": "string",
                        "required": False,
                        "description": "JSON com variáveis seguras da ferramenta. Obrigatório para definir_variaveis. Ex: {\"API_KEY\": \"valor\"} ou {\"API_KEY\": {\"valor\": \"...\", \"is_secret\": true}}"
                    }
                }),
                "codigo_python": """
import httpx, json, os

BASE = os.environ.get("FLUXI_INTERNAL_URL", "http://localhost:8000")
headers = {"Content-Type": "application/json"}
acao = argumentos.get("acao", "listar")

try:
    if acao == "listar":
        r = httpx.get(f"{BASE}/api/ferramentas/", timeout=10)
        items = r.json()
        resultado = {
            "total": len(items),
            "ferramentas": [
                {"id": x["id"], "nome": x["nome"], "descricao": x["descricao"],
                 "tool_type": x.get("tool_type"), "ativa": x.get("ativa", True)}
                for x in items
            ]
        }
    elif acao == "criar":
        dados = argumentos.get("dados", {})
        if isinstance(dados, str):
            dados = json.loads(dados)
        r = httpx.post(f"{BASE}/api/ferramentas/", json=dados, headers=headers, timeout=10)
        if r.status_code in (200, 201):
            f = r.json()
            resultado = {"sucesso": True, "id": f["id"], "nome": f["nome"],
                         "mensagem": f"Ferramenta '{f['nome']}' criada com ID {f['id']}"}
        else:
            resultado = {"sucesso": False, "erro": r.text}
    elif acao == "editar":
        fid = argumentos.get("ferramenta_id")
        dados = argumentos.get("dados", {})
        if isinstance(dados, str):
            dados = json.loads(dados)
        r = httpx.put(f"{BASE}/api/ferramentas/{fid}", json=dados, headers=headers, timeout=10)
        if r.status_code == 200:
            f = r.json()
            resultado = {"sucesso": True, "id": f["id"], "nome": f["nome"], "mensagem": "Ferramenta atualizada"}
        else:
            resultado = {"sucesso": False, "erro": r.text}
    elif acao == "deletar":
        fid = argumentos.get("ferramenta_id")
        r = httpx.delete(f"{BASE}/api/ferramentas/{fid}", timeout=10)
        resultado = {"sucesso": r.status_code == 200, "mensagem": r.json().get("mensagem", r.text)}
    elif acao == "associar_agente":
        aid = argumentos.get("agente_id")
        fid = argumentos.get("ferramenta_id")
        r_atual = httpx.get(f"{BASE}/api/agentes/{aid}/ferramentas", timeout=10)
        atual = [x["id"] for x in r_atual.json()] if r_atual.status_code == 200 else []
        if fid not in atual:
            atual.append(fid)
        r = httpx.post(f"{BASE}/api/agentes/{aid}/ferramentas",
                        json={"ferramentas": atual}, headers=headers, timeout=10)
        resultado = {"sucesso": r.status_code == 200,
                     "mensagem": f"Ferramenta {fid} associada ao agente {aid}",
                     "total_ferramentas": len(atual)}
    elif acao == "desassociar_agente":
        aid = argumentos.get("agente_id")
        fid = argumentos.get("ferramenta_id")
        r_atual = httpx.get(f"{BASE}/api/agentes/{aid}/ferramentas", timeout=10)
        atual = [x["id"] for x in r_atual.json()] if r_atual.status_code == 200 else []
        nova_lista = [x for x in atual if x != fid]
        r = httpx.post(f"{BASE}/api/agentes/{aid}/ferramentas",
                        json={"ferramentas": nova_lista}, headers=headers, timeout=10)
        resultado = {"sucesso": r.status_code == 200,
                     "mensagem": f"Ferramenta {fid} removida do agente {aid}"}
    elif acao == "listar_agente":
        aid = argumentos.get("agente_id")
        r = httpx.get(f"{BASE}/api/agentes/{aid}/ferramentas", timeout=10)
        items = r.json() if r.status_code == 200 else []
        resultado = {"ferramentas": [{"id": x["id"], "nome": x["nome"]} for x in items]}
    else:
        resultado = {"erro": f"Ação '{acao}' inválida. Use: listar, criar, editar, deletar, associar_agente, desassociar_agente, listar_agente"}
except Exception as e:
    resultado = {"erro": str(e)}
""",
                "substituir": False,
                "output": "llm",
                "ativa": True,
            },
            {
                "nome": "fluxi_skills",
                "descricao": (
                    "Gerencia skills do sistema Fluxi. "
                    "Use para criar novas skills com instruções especializadas, editar skills existentes, "
                    "ou associar/desassociar skills de agentes. "
                    "Invoque a skill 'meta_skills' antes de usar para entender a estrutura."
                ),
                "tool_type": ToolType.CODE,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "acao": {
                        "type": "enum",
                        "required": True,
                        "description": "Ação a executar",
                        "options": ["listar", "criar", "editar", "deletar", "associar_agente", "desassociar_agente", "listar_agente"]
                    },
                    "skill_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID da skill (obrigatório para editar, deletar, associar_agente, desassociar_agente)"
                    },
                    "agente_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID do agente (obrigatório para associar_agente, desassociar_agente, listar_agente)"
                    },
                    "dados": {
                        "type": "string",
                        "required": False,
                        "description": "JSON com os campos da skill. Invoque meta_skills para ver a estrutura."
                    }
                }),
                "codigo_python": """
import httpx, json, os

BASE = os.environ.get("FLUXI_INTERNAL_URL", "http://localhost:8000")
headers = {"Content-Type": "application/json"}
acao = argumentos.get("acao", "listar")

try:
    if acao == "listar":
        r = httpx.get(f"{BASE}/api/skills/", timeout=10)
        items = r.json()
        resultado = {
            "total": len(items),
            "skills": [{"id": x["id"], "nome": x["nome"], "descricao": x["descricao"],
                         "categoria": x.get("categoria"), "icone": x.get("icone")} for x in items]
        }
    elif acao == "criar":
        dados = argumentos.get("dados", {})
        if isinstance(dados, str):
            dados = json.loads(dados)
        r = httpx.post(f"{BASE}/api/skills/", json=dados, headers=headers, timeout=10)
        if r.status_code in (200, 201):
            s = r.json()
            resultado = {"sucesso": True, "id": s["id"], "nome": s["nome"],
                         "mensagem": f"Skill '{s['nome']}' criada com ID {s['id']}"}
        else:
            resultado = {"sucesso": False, "erro": r.text}
    elif acao == "editar":
        sid = argumentos.get("skill_id")
        dados = argumentos.get("dados", {})
        if isinstance(dados, str):
            dados = json.loads(dados)
        r = httpx.put(f"{BASE}/api/skills/{sid}", json=dados, headers=headers, timeout=10)
        if r.status_code == 200:
            s = r.json()
            resultado = {"sucesso": True, "id": s["id"], "nome": s["nome"], "mensagem": "Skill atualizada"}
        else:
            resultado = {"sucesso": False, "erro": r.text}
    elif acao == "deletar":
        sid = argumentos.get("skill_id")
        r = httpx.delete(f"{BASE}/api/skills/{sid}", timeout=10)
        resultado = {"sucesso": r.status_code == 200, "mensagem": r.json().get("mensagem", r.text)}
    elif acao == "associar_agente":
        aid = argumentos.get("agente_id")
        sid = argumentos.get("skill_id")
        r_atual = httpx.get(f"{BASE}/api/skills/agente/{aid}", timeout=10)
        atual = [x["id"] for x in r_atual.json()] if r_atual.status_code == 200 else []
        if sid not in atual:
            atual.append(sid)
        r = httpx.post(f"{BASE}/api/skills/agente/{aid}",
                        json={"skills": atual}, headers=headers, timeout=10)
        resultado = {"sucesso": r.status_code == 200,
                     "mensagem": f"Skill {sid} associada ao agente {aid}"}
    elif acao == "desassociar_agente":
        aid = argumentos.get("agente_id")
        sid = argumentos.get("skill_id")
        r_atual = httpx.get(f"{BASE}/api/skills/agente/{aid}", timeout=10)
        atual = [x["id"] for x in r_atual.json()] if r_atual.status_code == 200 else []
        nova_lista = [x for x in atual if x != sid]
        r = httpx.post(f"{BASE}/api/skills/agente/{aid}",
                        json={"skills": nova_lista}, headers=headers, timeout=10)
        resultado = {"sucesso": r.status_code == 200,
                     "mensagem": f"Skill {sid} removida do agente {aid}"}
    elif acao == "listar_agente":
        aid = argumentos.get("agente_id")
        r = httpx.get(f"{BASE}/api/skills/agente/{aid}", timeout=10)
        items = r.json() if r.status_code == 200 else []
        resultado = {"skills": [{"id": x["id"], "nome": x["nome"]} for x in items]}
    else:
        resultado = {"erro": f"Ação '{acao}' inválida. Use: listar, criar, editar, deletar, associar_agente, desassociar_agente, listar_agente"}
except Exception as e:
    resultado = {"erro": str(e)}
""",
                "substituir": False,
                "output": "llm",
                "ativa": True,
            },
            {
                "nome": "fluxi_mcp",
                "descricao": (
                    "Gerencia servidores MCP (Model Context Protocol) do sistema Fluxi. "
                    "Use para listar presets disponíveis, conectar servidores MCP a um agente "
                    "via preset, URL (SSE/HTTP) ou JSON one-click, sincronizar tools e desconectar. "
                    "Invoque a skill 'meta_mcp' antes de usar para entender as opções disponíveis."
                ),
                "tool_type": ToolType.CODE,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "acao": {
                        "type": "enum",
                        "required": True,
                        "description": "Ação a executar",
                        "options": [
                            "listar_presets",
                            "listar",
                            "conectar_preset",
                            "conectar_url",
                            "conectar_stdio",
                            "one_click",
                            "sincronizar",
                            "deletar"
                        ]
                    },
                    "agente_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID do agente (obrigatório para listar, conectar_*, one_click)"
                    },
                    "mcp_client_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID do cliente MCP (obrigatório para sincronizar, deletar)"
                    },
                    "preset_key": {
                        "type": "string",
                        "required": False,
                        "description": "Chave do preset (obrigatório para conectar_preset). Use listar_presets para ver as opções."
                    },
                    "nome": {
                        "type": "string",
                        "required": False,
                        "description": "Nome do servidor MCP"
                    },
                    "url": {
                        "type": "string",
                        "required": False,
                        "description": "URL do servidor (obrigatório para conectar_url). Ex: http://localhost:8080/mcp"
                    },
                    "transport_type": {
                        "type": "enum",
                        "required": False,
                        "description": "Tipo de transporte para conectar_url",
                        "options": ["sse", "streamable-http"]
                    },
                    "command": {
                        "type": "string",
                        "required": False,
                        "description": "Comando para conectar_stdio. Ex: python, npx, uv"
                    },
                    "args": {
                        "type": "string",
                        "required": False,
                        "description": "Argumentos do comando como JSON array string. Ex: '[\"run\", \"server.py\"]'"
                    },
                    "env_vars": {
                        "type": "string",
                        "required": False,
                        "description": "Variáveis de ambiente como JSON object string. Ex: '{\"TOKEN\": \"abc\"}'"
                    },
                    "headers": {
                        "type": "string",
                        "required": False,
                        "description": "Headers HTTP como JSON object string. Ex: '{\"Authorization\": \"Bearer TOKEN\"}'"
                    },
                    "inputs": {
                        "type": "string",
                        "required": False,
                        "description": "Inputs do preset como JSON object string. Ex: '{\"sandbox_url\": \"http://...\"}'"
                    },
                    "json_config": {
                        "type": "string",
                        "required": False,
                        "description": "JSON de configuração MCP no formato mcpServers (para one_click)"
                    }
                }),
                "codigo_python": """
import httpx, json, os

BASE = os.environ.get("FLUXI_INTERNAL_URL", "http://localhost:8000")
headers_req = {"Content-Type": "application/json"}
acao = argumentos.get("acao", "listar_presets")

def parse_json_arg(val):
    if not val:
        return None
    if isinstance(val, (dict, list)):
        return val
    return json.loads(val)

try:
    if acao == "listar_presets":
        r = httpx.get(f"{BASE}/api/mcp/presets", timeout=10)
        presets = r.json()
        resultado = {
            "total": len(presets),
            "presets": [
                {"key": p["key"], "name": p["name"], "description": p["description"],
                 "transport_type": p["transport_type"], "tags": p.get("tags", []),
                 "inputs": [i["id"] for i in p.get("inputs", [])]}
                for p in presets
            ]
        }

    elif acao == "listar":
        aid = argumentos["agente_id"]
        r = httpx.get(f"{BASE}/api/mcp/agente/{aid}/clients", timeout=10)
        items = r.json()
        resultado = {
            "total": len(items),
            "mcp_clients": [
                {"id": x["id"], "nome": x["nome"], "transport_type": x["transport_type"],
                 "conectado": x["conectado"], "total_tools": x.get("total_tools", 0),
                 "ultimo_erro": x.get("ultimo_erro")}
                for x in items
            ]
        }

    elif acao == "conectar_preset":
        payload = {
            "preset_key": argumentos["preset_key"],
            "agente_id": argumentos["agente_id"],
            "nome": argumentos.get("nome"),
            "inputs": parse_json_arg(argumentos.get("inputs"))
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        r = httpx.post(f"{BASE}/api/mcp/presets/aplicar",
                        json=payload, headers=headers_req, timeout=30)
        if r.status_code in (200, 201):
            c = r.json()
            resultado = {
                "sucesso": True, "id": c["id"], "nome": c["nome"],
                "conectado": c["conectado"], "total_tools": c.get("total_tools", 0),
                "mensagem": f"Servidor MCP '{c['nome']}' conectado com {c.get('total_tools', 0)} tools"
            }
        else:
            resultado = {"sucesso": False, "erro": r.text}

    elif acao == "conectar_url":
        payload = {
            "agente_id": argumentos["agente_id"],
            "nome": argumentos.get("nome", "Servidor MCP"),
            "url": argumentos["url"],
            "transport_type": argumentos.get("transport_type", "streamable-http"),
            "headers": parse_json_arg(argumentos.get("headers")),
            "ativo": True
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        aid = argumentos["agente_id"]
        r = httpx.post(f"{BASE}/api/mcp/agente/{aid}/clients",
                        json=payload, headers=headers_req, timeout=30)
        if r.status_code in (200, 201):
            c = r.json()
            resultado = {
                "sucesso": True, "id": c["id"], "nome": c["nome"],
                "conectado": c["conectado"], "total_tools": c.get("total_tools", 0),
                "mensagem": f"Servidor MCP '{c['nome']}' conectado via URL"
            }
        else:
            resultado = {"sucesso": False, "erro": r.text}

    elif acao == "conectar_stdio":
        payload = {
            "agente_id": argumentos["agente_id"],
            "nome": argumentos.get("nome", "Servidor MCP Local"),
            "transport_type": "stdio",
            "command": argumentos["command"],
            "args": parse_json_arg(argumentos.get("args")) or [],
            "env_vars": parse_json_arg(argumentos.get("env_vars")),
            "ativo": True
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        aid = argumentos["agente_id"]
        r = httpx.post(f"{BASE}/api/mcp/agente/{aid}/clients",
                        json=payload, headers=headers_req, timeout=30)
        if r.status_code in (200, 201):
            c = r.json()
            resultado = {
                "sucesso": True, "id": c["id"], "nome": c["nome"],
                "conectado": c["conectado"], "total_tools": c.get("total_tools", 0),
                "mensagem": f"Servidor MCP '{c['nome']}' conectado via STDIO"
            }
        else:
            resultado = {"sucesso": False, "erro": r.text}

    elif acao == "one_click":
        payload = {
            "agente_id": argumentos["agente_id"],
            "json_config": argumentos["json_config"],
            "nome": argumentos.get("nome"),
            "descricao": argumentos.get("descricao")
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        r = httpx.post(f"{BASE}/api/mcp/one-click/install",
                        data=payload, timeout=30)
        resultado = {"sucesso": r.status_code in (200, 201, 303), "status": r.status_code}

    elif acao == "sincronizar":
        mid = argumentos["mcp_client_id"]
        r = httpx.post(f"{BASE}/api/mcp/clients/{mid}/sincronizar", timeout=30)
        if r.status_code == 200:
            data = r.json()
            resultado = {"sucesso": True, "total_tools": data.get("total_tools", 0),
                         "mensagem": data.get("mensagem", "Sincronizado")}
        else:
            resultado = {"sucesso": False, "erro": r.text}

    elif acao == "deletar":
        mid = argumentos["mcp_client_id"]
        r = httpx.delete(f"{BASE}/api/mcp/clients/{mid}", timeout=10)
        resultado = {"sucesso": r.status_code == 200,
                     "mensagem": r.json().get("mensagem", r.text)}

    else:
        resultado = {"erro": f"Ação '{acao}' inválida. Use: listar_presets, listar, conectar_preset, conectar_url, conectar_stdio, one_click, sincronizar, deletar"}

except Exception as e:
    resultado = {"erro": str(e)}
""",
                "substituir": False,
                "output": "llm",
                "ativa": True,
            },
            {
                "nome": "fluxi_agentes",
                "descricao": (
                    "Gerencia agentes do sistema Fluxi. "
                    "Use para criar novos agentes personalizados, editar agentes existentes, ou listar agentes da sessão. "
                    "Para associar ferramentas ao agente use fluxi_ferramentas com acao='associar_agente'. "
                    "Invoque a skill 'meta_agentes' para ver o template completo dos campos."
                ),
                "tool_type": ToolType.CODE,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "acao": {
                        "type": "enum",
                        "required": True,
                        "description": "Ação a executar",
                        "options": ["listar", "criar", "editar", "deletar", "obter", "listar_skills", "associar_skill", "desassociar_skill", "ativar_sandbox"]
                    },
                    "agente_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID do agente (obrigatório para editar, deletar, obter, listar_skills, associar_skill, desassociar_skill, ativar_sandbox)"
                    },
                    "sessao_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID da sessão para filtrar ao listar"
                    },
                    "dados": {
                        "type": "string",
                        "required": False,
                        "description": "JSON com os campos do agente. Invoque meta_agentes para ver o template completo."
                    },
                    "skill_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID da skill (obrigatório para associar_skill e desassociar_skill)"
                    },
                    "ativo": {
                        "type": "boolean",
                        "required": False,
                        "description": "true para ativar, false para desativar (obrigatório para ativar_sandbox)"
                    }
                }),
                "codigo_python": """
import httpx, json, os

BASE = os.environ.get("FLUXI_INTERNAL_URL", "http://localhost:8000")
headers = {"Content-Type": "application/json"}
acao = argumentos.get("acao", "listar")

try:
    if acao == "listar":
        params = {}
        if argumentos.get("sessao_id"):
            params["sessao_id"] = argumentos["sessao_id"]
        r = httpx.get(f"{BASE}/api/agentes/", params=params, timeout=10)
        items = r.json()
        resultado = {
            "total": len(items),
            "agentes": [{"id": x["id"], "codigo": x["codigo"], "nome": x["nome"],
                          "descricao": x.get("descricao"), "sessao_id": x["sessao_id"],
                          "ativo": x.get("ativo", True)} for x in items]
        }
    elif acao == "criar":
        dados = argumentos.get("dados", {})
        if isinstance(dados, str):
            dados = json.loads(dados)
        r = httpx.post(f"{BASE}/api/agentes/", json=dados, headers=headers, timeout=10)
        if r.status_code in (200, 201):
            a = r.json()
            resultado = {"sucesso": True, "id": a["id"], "nome": a["nome"],
                         "codigo": a["codigo"],
                         "mensagem": f"Agente '{a['nome']}' criado com ID {a['id']}"}
        else:
            resultado = {"sucesso": False, "erro": r.text}
    elif acao == "editar":
        aid = argumentos.get("agente_id")
        dados = argumentos.get("dados", {})
        if isinstance(dados, str):
            dados = json.loads(dados)
        r = httpx.put(f"{BASE}/api/agentes/{aid}", json=dados, headers=headers, timeout=10)
        if r.status_code == 200:
            a = r.json()
            resultado = {"sucesso": True, "id": a["id"], "nome": a["nome"], "mensagem": "Agente atualizado"}
        else:
            resultado = {"sucesso": False, "erro": r.text}
    elif acao == "deletar":
        aid = argumentos.get("agente_id")
        r = httpx.delete(f"{BASE}/api/agentes/{aid}", timeout=10)
        resultado = {"sucesso": r.status_code == 200, "mensagem": r.json().get("mensagem", r.text)}
    elif acao == "obter":
        aid = argumentos.get("agente_id")
        r = httpx.get(f"{BASE}/api/agentes/{aid}", timeout=10)
        resultado = {"agente": r.json()} if r.status_code == 200 else {"erro": "Agente não encontrado"}
    else:
        resultado = {"erro": f"Ação '{acao}' inválida. Use: listar, criar, editar, deletar, obter"}
except Exception as e:
    resultado = {"erro": str(e)}
""",
                "substituir": False,
                "output": "llm",
                "ativa": True,
            },
            {
                "nome": "fluxi_rag",
                "descricao": (
                    "Gerencia bases de conhecimento RAG do sistema Fluxi. "
                    "Use para criar RAGs, adicionar textos ou arquivos como chunks, "
                    "vincular uma base de conhecimento a um agente, ou listar bases existentes. "
                    "Invoque a skill 'meta_rag' antes de usar para entender o fluxo completo."
                ),
                "tool_type": ToolType.CODE,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "acao": {
                        "type": "enum",
                        "required": True,
                        "description": "Ação a executar",
                        "options": [
                            "listar",
                            "criar",
                            "obter",
                            "adicionar_texto",
                            "adicionar_arquivo",
                            "vincular_agente",
                            "resetar",
                            "deletar"
                        ]
                    },
                    "rag_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID do RAG (obrigatório para obter, adicionar_texto, adicionar_arquivo, vincular_agente, resetar, deletar)"
                    },
                    "agente_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID do agente (obrigatório para vincular_agente)"
                    },
                    "nome": {
                        "type": "string",
                        "required": False,
                        "description": "Nome do RAG (obrigatório para criar)"
                    },
                    "descricao": {
                        "type": "string",
                        "required": False,
                        "description": "Descrição do RAG (opcional para criar)"
                    },
                    "titulo": {
                        "type": "string",
                        "required": False,
                        "description": "Título do chunk (obrigatório para adicionar_texto e adicionar_arquivo)"
                    },
                    "texto": {
                        "type": "string",
                        "required": False,
                        "description": "Conteúdo de texto a adicionar (obrigatório para adicionar_texto)"
                    },
                    "arquivo_path": {
                        "type": "string",
                        "required": False,
                        "description": "Caminho absoluto do arquivo no servidor (obrigatório para adicionar_arquivo). Formatos: .pdf, .txt, .md, .docx, .csv"
                    }
                }),
                "codigo_python": """
import httpx, json, os

BASE = os.environ.get("FLUXI_INTERNAL_URL", "http://localhost:8000")
headers_json = {"Content-Type": "application/json"}
acao = argumentos.get("acao", "listar")

try:
    if acao == "listar":
        r = httpx.get(f"{BASE}/api/rags/", timeout=10)
        items = r.json()
        resultado = {
            "total": len(items),
            "rags": [
                {"id": x["id"], "nome": x["nome"], "descricao": x.get("descricao"),
                 "total_chunks": x.get("total_chunks", 0), "ativo": x.get("ativo", True)}
                for x in items
            ]
        }

    elif acao == "criar":
        payload = {
            "nome": argumentos["nome"],
            "descricao": argumentos.get("descricao", ""),
            "ativo": True
        }
        r = httpx.post(f"{BASE}/api/rags/", json=payload, headers=headers_json, timeout=10)
        if r.status_code in (200, 201):
            rag = r.json()
            resultado = {
                "sucesso": True, "id": rag["id"], "nome": rag["nome"],
                "mensagem": f"RAG '{rag['nome']}' criado com ID {rag['id']}. Use adicionar_texto ou adicionar_arquivo para adicionar conteúdo."
            }
        else:
            resultado = {"sucesso": False, "erro": r.text}

    elif acao == "obter":
        rid = argumentos["rag_id"]
        r = httpx.get(f"{BASE}/api/rags/{rid}", timeout=10)
        if r.status_code == 200:
            rag = r.json()
            resultado = {"rag": rag}
        else:
            resultado = {"erro": "RAG não encontrado"}

    elif acao == "adicionar_texto":
        rid = argumentos["rag_id"]
        payload = {
            "titulo": argumentos.get("titulo", "Conteúdo"),
            "texto": argumentos["texto"],
            "chunk_size": 500,
            "chunk_overlap": 50
        }
        r = httpx.post(f"{BASE}/api/rags/{rid}/adicionar-texto",
                       json=payload, headers=headers_json, timeout=30)
        if r.status_code == 200:
            data = r.json()
            resultado = {
                "sucesso": True,
                "chunks_criados": data.get("chunks_criados", 0),
                "mensagem": f"{data.get('chunks_criados', 0)} chunk(s) adicionado(s) ao RAG {rid}"
            }
        else:
            resultado = {"sucesso": False, "erro": r.text}

    elif acao == "adicionar_arquivo":
        rid = argumentos["rag_id"]
        arquivo_path = argumentos["arquivo_path"]
        titulo = argumentos.get("titulo", os.path.basename(arquivo_path))
        if not os.path.exists(arquivo_path):
            resultado = {"sucesso": False, "erro": f"Arquivo não encontrado: {arquivo_path}"}
        else:
            with open(arquivo_path, "rb") as f:
                conteudo = f.read()
            nome_arquivo = os.path.basename(arquivo_path)
            files = {"arquivo": (nome_arquivo, conteudo)}
            data_form = {"titulo": titulo, "chunk_size": "500", "chunk_overlap": "50"}
            r = httpx.post(f"{BASE}/api/rags/{rid}/adicionar-arquivo",
                           files=files, data=data_form, timeout=60)
            if r.status_code == 200:
                data = r.json()
                resultado = {
                    "sucesso": True,
                    "chunks_criados": data.get("chunks_criados", 0),
                    "mensagem": f"Arquivo '{nome_arquivo}' adicionado com {data.get('chunks_criados', 0)} chunk(s)"
                }
            else:
                resultado = {"sucesso": False, "erro": r.text}

    elif acao == "vincular_agente":
        aid = argumentos["agente_id"]
        rid = argumentos["rag_id"]
        r = httpx.post(f"{BASE}/api/agentes/{aid}/vincular-treinamento",
                       json={"rag_id": rid}, headers=headers_json, timeout=10)
        if r.status_code == 200:
            resultado = {
                "sucesso": True,
                "mensagem": f"RAG {rid} vinculado ao agente {aid}. O agente agora tem acesso à base de conhecimento via 'buscar_base_conhecimento'."
            }
        else:
            resultado = {"sucesso": False, "erro": r.text}

    elif acao == "resetar":
        rid = argumentos["rag_id"]
        r = httpx.post(f"{BASE}/api/rags/{rid}/resetar", timeout=30)
        if r.status_code == 200:
            resultado = {"sucesso": True, "mensagem": f"RAG {rid} resetado (todos os chunks removidos)"}
        else:
            resultado = {"sucesso": False, "erro": r.text}

    elif acao == "deletar":
        rid = argumentos["rag_id"]
        r = httpx.delete(f"{BASE}/api/rags/{rid}", timeout=10)
        resultado = {"sucesso": r.status_code == 200}

    else:
        resultado = {"erro": f"Ação '{acao}' inválida. Use: listar, criar, obter, adicionar_texto, adicionar_arquivo, vincular_agente, resetar, deletar"}

except Exception as e:
    resultado = {"erro": str(e)}
""",
                "substituir": False,
                "output": "llm",
                "ativa": True,
            },
            {
                "nome": "fluxi_agendamento",
                "descricao": (
                    "Agenda tarefas para serem executadas no futuro: lembretes, mensagens automáticas, "
                    "verificações periódicas (heartbeat) ou callbacks que reativam o próprio agente após "
                    "um intervalo de tempo. Use sempre que o usuário pedir para 'lembrar', 'avisar mais tarde', "
                    "'verificar daqui a X minutos', ou quando você precisar voltar a uma conversa depois. "
                    "Ações: criar, listar, cancelar, deletar."
                ),
                "tool_type": ToolType.NATIVE,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({
                    "acao": {
                        "type": "enum",
                        "required": True,
                        "description": "Ação a executar",
                        "options": ["criar", "listar", "obter", "cancelar", "deletar"]
                    },
                    "titulo": {
                        "type": "string",
                        "required": False,
                        "description": "Título descritivo da tarefa (obrigatório em criar)"
                    },
                    "tipo": {
                        "type": "enum",
                        "required": False,
                        "description": "once = uma vez; interval = repete a cada N segundos; cron = expressão cron",
                        "options": ["once", "interval", "cron"]
                    },
                    "quando": {
                        "type": "string",
                        "required": False,
                        "description": (
                            "ISO timestamp (once, ex: '2026-05-27T09:00:00'), "
                            "segundos (interval, ex: '300'), ou expressão cron (cron, ex: '0 9 * * *')."
                        )
                    },
                    "acao_tarefa": {
                        "type": "enum",
                        "required": False,
                        "description": (
                            "O que executar no disparo. "
                            "enviar_mensagem: manda texto direto ao telefone; "
                            "rodar_ferramenta: executa uma ferramenta cadastrada; "
                            "callback_agente: re-injeta um prompt no próprio agente como se viesse do usuário."
                        ),
                        "options": ["enviar_mensagem", "rodar_ferramenta", "callback_agente"]
                    },
                    "sessao_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID da sessão WhatsApp para enviar a mensagem"
                    },
                    "agente_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID do agente que vai responder (usado em callback_agente)"
                    },
                    "telefone_destino": {
                        "type": "string",
                        "required": False,
                        "description": "Telefone (só dígitos) do destinatário"
                    },
                    "payload": {
                        "type": "string",
                        "required": False,
                        "description": (
                            "JSON com os parâmetros da ação. "
                            "enviar_mensagem: {\"texto\": \"...\"}. "
                            "rodar_ferramenta: {\"nome_ferramenta\": \"...\", \"argumentos\": {...}}. "
                            "callback_agente: {\"prompt\": \"...\"}."
                        )
                    },
                    "max_execucoes": {
                        "type": "integer",
                        "required": False,
                        "description": "Limite de execuções para interval/cron (None = ilimitado)"
                    },
                    "tarefa_id": {
                        "type": "integer",
                        "required": False,
                        "description": "ID da tarefa (obter, cancelar, deletar)"
                    },
                    "descricao": {
                        "type": "string",
                        "required": False,
                        "description": "Descrição livre da tarefa"
                    }
                }),
                "substituir": False,
                "output": "llm",
                "ativa": True,
            },
        ]

        NATIVE_TOOLS = {
            "fluxi_ferramentas", "fluxi_skills", "fluxi_agentes",
            "fluxi_mcp", "fluxi_rag", "fluxi_agendamento",
        }

        for ferramenta_data in ferramentas_padrao:
            nome = ferramenta_data["nome"]
            existe = FerramentaService.obter_por_nome(db, nome)
            if not existe:
                ferramenta = FerramentaCriar(**ferramenta_data)
                FerramentaService.criar(db, ferramenta)
                logger.info("Ferramenta padrão criada: %s", nome)
            elif nome in NATIVE_TOOLS:
                # Garante tipo NATIVE e mantém params/descricao sempre atualizados
                changed = False
                if existe.tool_type != ToolType.NATIVE:
                    existe.tool_type = ToolType.NATIVE
                    existe.codigo_python = None
                    changed = True
                    logger.info("Ferramenta '%s' migrada para tipo NATIVE", nome)
                new_params = ferramenta_data.get("params")
                if new_params and existe.params != new_params:
                    existe.params = new_params
                    changed = True
                new_descricao = ferramenta_data.get("descricao")
                if new_descricao and existe.descricao != new_descricao:
                    existe.descricao = new_descricao
                    changed = True
                if changed:
                    db.commit()
                    logger.info("Ferramenta '%s' atualizada", nome)


# ═══════════════════════════════════════════════════════════════════
# NATIVE HANDLERS
# Chamados diretamente pelo service layer — sem httpx, sem exec().
# Cada função recebe (db: Session, argumentos: dict) → dict resultado.
# ═══════════════════════════════════════════════════════════════════

async def _native_fluxi_ferramentas(db, argumentos: dict) -> dict:
    """Gerencia ferramentas via service layer."""
    from ferramenta.ferramenta_schema import FerramentaCriar, FerramentaAtualizar

    acao = argumentos.get("acao", "listar")
    try:
        if acao == "listar":
            items = FerramentaService.listar_todas(db)
            return {
                "total": len(items),
                "ferramentas": [
                    {"id": f.id, "nome": f.nome, "descricao": f.descricao,
                     "tool_type": f.tool_type.value if f.tool_type else None,
                     "ativa": f.ativa}
                    for f in items
                ]
            }

        elif acao == "criar":
            dados = argumentos.get("dados", {})
            if isinstance(dados, str):
                import json as _json
                dados = _json.loads(dados)
            f = FerramentaService.criar(db, FerramentaCriar(**dados))
            return {"sucesso": True, "id": f.id, "nome": f.nome,
                    "mensagem": f"Ferramenta '{f.nome}' criada com ID {f.id}"}

        elif acao == "editar":
            fid = argumentos.get("ferramenta_id")
            dados = argumentos.get("dados", {})
            if isinstance(dados, str):
                import json as _json
                dados = _json.loads(dados)
            f = FerramentaService.atualizar(db, fid, FerramentaAtualizar(**dados))
            if not f:
                return {"sucesso": False, "erro": f"Ferramenta {fid} não encontrada"}
            return {"sucesso": True, "id": f.id, "nome": f.nome, "mensagem": "Ferramenta atualizada"}

        elif acao == "deletar":
            fid = argumentos.get("ferramenta_id")
            ok = FerramentaService.deletar(db, fid)
            return {"sucesso": ok, "mensagem": "Deletada" if ok else "Não encontrada"}

        elif acao == "associar_agente":
            from agente.agente_service import AgenteService
            aid = argumentos.get("agente_id")
            fid = argumentos.get("ferramenta_id")
            atual = [f.id for f in AgenteService.listar_ferramentas(db, aid)]
            if fid not in atual:
                atual.append(fid)
            AgenteService.atualizar_ferramentas(db, aid, atual)
            return {"sucesso": True, "mensagem": f"Ferramenta {fid} associada ao agente {aid}",
                    "total_ferramentas": len(atual)}

        elif acao == "desassociar_agente":
            from agente.agente_service import AgenteService
            aid = argumentos.get("agente_id")
            fid = argumentos.get("ferramenta_id")
            atual = [f.id for f in AgenteService.listar_ferramentas(db, aid)]
            nova = [x for x in atual if x != fid]
            AgenteService.atualizar_ferramentas(db, aid, nova)
            return {"sucesso": True, "mensagem": f"Ferramenta {fid} removida do agente {aid}"}

        elif acao == "listar_agente":
            from agente.agente_service import AgenteService
            aid = argumentos.get("agente_id")
            items = AgenteService.listar_ferramentas(db, aid)
            return {"ferramentas": [{"id": f.id, "nome": f.nome} for f in items]}

        elif acao == "definir_variaveis":
            from ferramenta.ferramenta_variavel_service import FerramentaVariavelService
            fid = argumentos.get("ferramenta_id")
            variaveis = argumentos.get("variaveis", {})
            if isinstance(variaveis, str):
                import json as _json
                variaveis = _json.loads(variaveis)
            if not fid:
                return {"erro": "ferramenta_id é obrigatório"}
            if not variaveis:
                return {"erro": "variaveis é obrigatório (dict {CHAVE: valor})"}
            FerramentaVariavelService.definir_variaveis_padrao(db, fid, variaveis)
            return {
                "sucesso": True,
                "mensagem": f"{len(variaveis)} variável(is) definida(s) para ferramenta {fid}",
                "chaves": list(variaveis.keys())
            }

        elif acao == "listar_variaveis":
            from ferramenta.ferramenta_variavel_service import FerramentaVariavelService
            fid = argumentos.get("ferramenta_id")
            if not fid:
                return {"erro": "ferramenta_id é obrigatório"}
            variaveis = FerramentaVariavelService.listar_por_ferramenta(db, fid)
            return {
                "total": len(variaveis),
                "variaveis": [
                    {
                        "id": v.id,
                        "chave": v.chave,
                        "tipo": v.tipo,
                        "descricao": v.descricao,
                        "is_secret": v.is_secret,
                        "valor": "***" if v.is_secret else v.valor
                    }
                    for v in variaveis
                ]
            }

        else:
            return {"erro": f"Ação '{acao}' inválida"}
    except Exception as e:
        return {"erro": str(e)}


async def _native_fluxi_skills(db, argumentos: dict) -> dict:
    """Gerencia skills via service layer."""
    from skill.skill_service import SkillService
    from skill.skill_schema import SkillCriar, SkillAtualizar

    acao = argumentos.get("acao", "listar")
    try:
        if acao == "listar":
            items = SkillService.listar_todas(db)
            return {
                "total": len(items),
                "skills": [
                    {"id": s.id, "nome": s.nome, "descricao": s.descricao,
                     "categoria": s.categoria, "icone": s.icone}
                    for s in items
                ]
            }

        elif acao == "criar":
            dados = argumentos.get("dados", {})
            if isinstance(dados, str):
                import json as _json
                dados = _json.loads(dados)
            s = SkillService.criar(db, SkillCriar(**dados))
            return {"sucesso": True, "id": s.id, "nome": s.nome,
                    "mensagem": f"Skill '{s.nome}' criada com ID {s.id}"}

        elif acao == "editar":
            sid = argumentos.get("skill_id")
            dados = argumentos.get("dados", {})
            if isinstance(dados, str):
                import json as _json
                dados = _json.loads(dados)
            s = SkillService.atualizar(db, sid, SkillAtualizar(**dados))
            if not s:
                return {"sucesso": False, "erro": f"Skill {sid} não encontrada"}
            return {"sucesso": True, "id": s.id, "nome": s.nome, "mensagem": "Skill atualizada"}

        elif acao == "deletar":
            sid = argumentos.get("skill_id")
            ok = SkillService.deletar(db, sid)
            return {"sucesso": ok, "mensagem": "Deletada" if ok else "Não encontrada"}

        elif acao == "associar_agente":
            aid = argumentos.get("agente_id")
            sid = argumentos.get("skill_id")
            atual = [s.id for s in SkillService.listar_skills_agente(db, aid)]
            if sid not in atual:
                atual.append(sid)
            SkillService.atualizar_skills_agente(db, aid, atual)
            return {"sucesso": True, "mensagem": f"Skill {sid} associada ao agente {aid}"}

        elif acao == "desassociar_agente":
            aid = argumentos.get("agente_id")
            sid = argumentos.get("skill_id")
            atual = [s.id for s in SkillService.listar_skills_agente(db, aid)]
            nova = [x for x in atual if x != sid]
            SkillService.atualizar_skills_agente(db, aid, nova)
            return {"sucesso": True, "mensagem": f"Skill {sid} removida do agente {aid}"}

        elif acao == "listar_agente":
            aid = argumentos.get("agente_id")
            items = SkillService.listar_skills_agente(db, aid)
            return {"skills": [{"id": s.id, "nome": s.nome} for s in items]}

        else:
            return {"erro": f"Ação '{acao}' inválida"}
    except Exception as e:
        return {"erro": str(e)}


async def _native_fluxi_agentes(db, argumentos: dict) -> dict:
    """Gerencia agentes via service layer."""
    from agente.agente_service import AgenteService
    from agente.agente_schema import AgenteCriar, AgenteAtualizar

    acao = argumentos.get("acao", "listar")
    try:
        if acao == "listar":
            sessao_id = argumentos.get("sessao_id")
            items = (AgenteService.listar_por_sessao(db, sessao_id)
                     if sessao_id else AgenteService.listar_todos(db))
            return {
                "total": len(items),
                "agentes": [
                    {"id": a.id, "codigo": a.codigo, "nome": a.nome,
                     "descricao": a.descricao, "sessao_id": a.sessao_id,
                     "ativo": a.ativo}
                    for a in items
                ]
            }

        elif acao == "criar":
            dados = argumentos.get("dados", {})
            if isinstance(dados, str):
                import json as _json
                dados = _json.loads(dados)
            a = AgenteService.criar(db, AgenteCriar(**dados))
            return {"sucesso": True, "id": a.id, "nome": a.nome, "codigo": a.codigo,
                    "mensagem": f"Agente '{a.nome}' criado com ID {a.id}"}

        elif acao == "editar":
            aid = argumentos.get("agente_id")
            dados = argumentos.get("dados", {})
            if isinstance(dados, str):
                import json as _json
                dados = _json.loads(dados)
            a = AgenteService.atualizar(db, aid, AgenteAtualizar(**dados))
            if not a:
                return {"sucesso": False, "erro": f"Agente {aid} não encontrado"}
            return {"sucesso": True, "id": a.id, "nome": a.nome, "mensagem": "Agente atualizado"}

        elif acao == "deletar":
            aid = argumentos.get("agente_id")
            ok = AgenteService.deletar(db, aid)
            return {"sucesso": ok, "mensagem": "Deletado" if ok else "Não encontrado"}

        elif acao == "obter":
            aid = argumentos.get("agente_id")
            a = AgenteService.obter_por_id(db, aid)
            if not a:
                return {"erro": f"Agente {aid} não encontrado"}
            return {
                "id": a.id, "codigo": a.codigo, "nome": a.nome,
                "descricao": a.descricao, "sessao_id": a.sessao_id,
                "ativo": a.ativo,
                # System prompt
                "agente_papel": a.agente_papel,
                "agente_objetivo": a.agente_objetivo,
                "agente_politicas": a.agente_politicas,
                "agente_tarefa": a.agente_tarefa,
                "agente_objetivo_explicito": a.agente_objetivo_explicito,
                "agente_publico": a.agente_publico,
                "agente_restricoes": a.agente_restricoes,
                # LLM
                "provedor_llm_id": a.provedor_llm_id,
                "modelo_llm": a.modelo_llm,
                "temperatura": a.temperatura,
                "max_tokens": a.max_tokens,
                # Integrações
                "rag_id": a.rag_id,
                "internal_sandbox_ativo": a.internal_sandbox_ativo,
            }

        elif acao == "listar_skills":
            aid = argumentos.get("agente_id")
            if not aid:
                return {"erro": "agente_id é obrigatório"}
            from skill.skill_service import SkillService
            skills = SkillService.listar_skills_agente(db, aid)
            return {
                "total": len(skills),
                "skills": [{"id": s.id, "nome": s.nome, "descricao": s.descricao, "categoria": s.categoria} for s in skills]
            }

        elif acao == "associar_skill":
            aid = argumentos.get("agente_id")
            sid = argumentos.get("skill_id")
            if not aid or not sid:
                return {"erro": "agente_id e skill_id são obrigatórios"}
            from skill.skill_service import SkillService
            skill = SkillService.obter_por_id(db, sid)
            if not skill:
                return {"erro": f"Skill {sid} não encontrada"}
            atuais = [s.id for s in SkillService.listar_skills_agente(db, aid)]
            if sid not in atuais:
                atuais.append(sid)
            SkillService.atualizar_skills_agente(db, aid, atuais)
            return {"sucesso": True, "mensagem": f"Skill '{skill.nome}' associada ao agente {aid}"}

        elif acao == "desassociar_skill":
            aid = argumentos.get("agente_id")
            sid = argumentos.get("skill_id")
            if not aid or not sid:
                return {"erro": "agente_id e skill_id são obrigatórios"}
            from skill.skill_service import SkillService
            atuais = [s.id for s in SkillService.listar_skills_agente(db, aid)]
            nova = [x for x in atuais if x != sid]
            SkillService.atualizar_skills_agente(db, aid, nova)
            return {"sucesso": True, "mensagem": f"Skill {sid} removida do agente {aid}"}

        elif acao == "ativar_sandbox":
            aid = argumentos.get("agente_id")
            ativo = argumentos.get("ativo")
            if not aid or ativo is None:
                return {"erro": "agente_id e ativo (true/false) são obrigatórios"}
            a = AgenteService.obter_por_id(db, aid)
            if not a:
                return {"erro": f"Agente {aid} não encontrado"}
            a.internal_sandbox_ativo = bool(ativo)
            db.commit()
            estado = "ativado" if ativo else "desativado"
            return {"sucesso": True, "mensagem": f"Sandbox {estado} para o agente {aid}"}

        else:
            return {"erro": f"Ação '{acao}' inválida"}
    except Exception as e:
        return {"erro": str(e)}


async def _native_fluxi_mcp(db, argumentos: dict) -> dict:
    """Gerencia servidores MCP via service layer."""
    from mcp_client.mcp_service import MCPService
    from mcp_client.mcp_schema import (
        MCPClientCriar, MCPPresetAplicarRequest, MCPOneClickRequest
    )

    acao = argumentos.get("acao", "listar_presets")
    try:
        if acao == "listar_presets":
            presets = MCPService.listar_presets_disponiveis()
            return {
                "total": len(presets),
                "presets": [
                    {"key": p.key, "name": p.name, "description": p.description,
                     "transport_type": p.transport_type,
                     "inputs": [i.id for i in (p.inputs or [])],
                     "tags": p.tags or []}
                    for p in presets
                ]
            }

        elif acao == "listar":
            aid = argumentos.get("agente_id")
            items = MCPService.listar_por_agente(db, aid)
            return {
                "total": len(items),
                "mcp_clients": [
                    {"id": c.id, "nome": c.nome, "transport_type": c.transport_type,
                     "conectado": c.conectado, "total_tools": c.total_tools or 0,
                     "ultimo_erro": c.ultimo_erro}
                    for c in items
                ]
            }

        elif acao == "conectar_preset":
            payload = MCPPresetAplicarRequest(
                preset_key=argumentos["preset_key"],
                agente_id=argumentos["agente_id"],
                nome=argumentos.get("nome"),
                inputs=argumentos.get("inputs") or {},
            )
            c = MCPService.aplicar_preset(db, payload)
            result = await MCPService.conectar_cliente(db, c.id)
            return {
                "sucesso": result.get("conectado", False),
                "id": c.id, "nome": c.nome,
                "total_tools": result.get("total_tools", 0),
                "mensagem": f"Servidor MCP '{c.nome}' conectado com {result.get('total_tools', 0)} tools"
            }

        elif acao == "conectar_url":
            c = MCPService.criar(db, MCPClientCriar(
                agente_id=argumentos["agente_id"],
                nome=argumentos.get("nome", "Servidor MCP"),
                transport_type=argumentos.get("transport_type", "streamable-http"),
                url=argumentos["url"],
                headers=argumentos.get("headers"),
                ativo=True,
            ))
            result = await MCPService.conectar_cliente(db, c.id)
            return {
                "sucesso": result.get("conectado", False),
                "id": c.id, "nome": c.nome,
                "total_tools": result.get("total_tools", 0),
                "mensagem": f"Servidor MCP '{c.nome}' conectado via URL"
            }

        elif acao == "conectar_stdio":
            import json as _json
            args_raw = argumentos.get("args")
            args_list = (
                _json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            ) or []
            env_raw = argumentos.get("env_vars")
            env_dict = (
                _json.loads(env_raw) if isinstance(env_raw, str) else env_raw
            )
            c = MCPService.criar(db, MCPClientCriar(
                agente_id=argumentos["agente_id"],
                nome=argumentos.get("nome", "Servidor MCP Local"),
                transport_type="stdio",
                command=argumentos["command"],
                args=args_list,
                env_vars=env_dict,
                ativo=True,
            ))
            result = await MCPService.conectar_cliente(db, c.id)
            return {
                "sucesso": result.get("conectado", False),
                "id": c.id, "nome": c.nome,
                "total_tools": result.get("total_tools", 0),
                "mensagem": f"Servidor MCP '{c.nome}' conectado via STDIO"
            }

        elif acao == "one_click":
            payload = MCPOneClickRequest(
                agente_id=argumentos["agente_id"],
                json_config=argumentos["json_config"],
                nome=argumentos.get("nome"),
                descricao=argumentos.get("descricao"),
            )
            c = MCPService.aplicar_one_click(db, payload)
            result = await MCPService.conectar_cliente(db, c.id)
            return {
                "sucesso": result.get("conectado", False),
                "id": c.id, "nome": c.nome,
                "total_tools": result.get("total_tools", 0),
            }

        elif acao == "sincronizar":
            mid = argumentos["mcp_client_id"]
            total = await MCPService.sincronizar_tools(db, mid)
            return {"sucesso": True, "total_tools": total,
                    "mensagem": f"{total} tool(s) sincronizada(s)"}

        elif acao == "deletar":
            mid = argumentos["mcp_client_id"]
            ok = MCPService.deletar(db, mid)
            return {"sucesso": ok, "mensagem": "Deletado" if ok else "Não encontrado"}

        else:
            return {"erro": f"Ação '{acao}' inválida"}
    except Exception as e:
        return {"erro": str(e)}


async def _native_fluxi_rag(db, argumentos: dict) -> dict:
    """Gerencia RAG via service layer."""
    from rag.rag_service import RAGService
    from rag.rag_schema import RAGCriar
    from agente.agente_service import AgenteService
    from agente.agente_schema import AgenteAtualizar

    acao = argumentos.get("acao", "listar")
    try:
        if acao == "listar":
            items = RAGService.listar_todos(db)
            return {
                "total": len(items),
                "rags": [
                    {"id": r.id, "nome": r.nome, "descricao": r.descricao,
                     "total_chunks": r.total_chunks if hasattr(r, "total_chunks") else 0,
                     "ativo": r.ativo}
                    for r in items
                ]
            }

        elif acao == "criar":
            r = RAGService.criar(db, RAGCriar(
                nome=argumentos["nome"],
                descricao=argumentos.get("descricao", ""),
            ))
            return {"sucesso": True, "id": r.id, "nome": r.nome,
                    "mensagem": f"RAG '{r.nome}' criado com ID {r.id}. "
                                "Use adicionar_texto ou adicionar_arquivo para adicionar conteúdo."}

        elif acao == "obter":
            r = RAGService.obter_por_id(db, argumentos["rag_id"])
            if not r:
                return {"erro": "RAG não encontrado"}
            stats = RAGService.obter_estatisticas(db, r.id)
            return {"id": r.id, "nome": r.nome, "descricao": r.descricao,
                    "total_chunks": stats.get("total_chunks", 0), "ativo": r.ativo}

        elif acao == "adicionar_texto":
            rid = argumentos["rag_id"]
            chunks = RAGService.adicionar_texto(
                db, rid,
                titulo=argumentos.get("titulo", "Conteúdo"),
                texto=argumentos["texto"],
                chunk_size=argumentos.get("chunk_size", 500),
                chunk_overlap=argumentos.get("chunk_overlap", 50),
            )
            return {"sucesso": True, "chunks_criados": chunks,
                    "mensagem": f"{chunks} chunk(s) adicionado(s) ao RAG {rid}"}

        elif acao == "adicionar_arquivo":
            import os
            rid = argumentos["rag_id"]
            path = argumentos["arquivo_path"]
            if not os.path.exists(path):
                return {"sucesso": False, "erro": f"Arquivo não encontrado: {path}"}
            titulo = argumentos.get("titulo", os.path.basename(path))
            chunks = RAGService.adicionar_arquivo(
                db, rid, titulo=titulo, arquivo_path=path,
                chunk_size=argumentos.get("chunk_size", 500),
                chunk_overlap=argumentos.get("chunk_overlap", 50),
            )
            return {"sucesso": True, "chunks_criados": chunks,
                    "mensagem": f"Arquivo '{os.path.basename(path)}' adicionado com {chunks} chunk(s)"}

        elif acao == "vincular_agente":
            aid = argumentos["agente_id"]
            rid = argumentos["rag_id"]
            # Valida RAG existe
            if not RAGService.obter_por_id(db, rid):
                return {"sucesso": False, "erro": f"RAG {rid} não encontrado"}
            AgenteService.atualizar(db, aid, AgenteAtualizar(rag_id=rid))
            return {"sucesso": True,
                    "mensagem": f"RAG {rid} vinculado ao agente {aid}. "
                                "O agente agora tem acesso via 'buscar_base_conhecimento'."}

        elif acao == "resetar":
            rid = argumentos["rag_id"]
            ok = RAGService.resetar_rag(db, rid)
            return {"sucesso": ok, "mensagem": f"RAG {rid} resetado" if ok else "Não encontrado"}

        elif acao == "deletar":
            rid = argumentos["rag_id"]
            ok = RAGService.deletar(db, rid)
            return {"sucesso": ok}

        else:
            return {"erro": f"Ação '{acao}' inválida"}
    except Exception as e:
        return {"erro": str(e)}


async def _native_fluxi_agendamento(db, argumentos: dict) -> dict:
    """Gerencia tarefas agendadas (heartbeat / lembretes / callbacks) via service layer."""
    from agendamento.agendamento_service import AgendamentoService
    from agendamento.agendamento_schema import TarefaAgendadaCriar
    from agendamento.agendamento_model import (
        TipoAgendamento, AcaoAgendamento, StatusAgendamento,
    )

    acao = argumentos.get("acao", "listar")
    try:
        if acao == "criar":
            payload_raw = argumentos.get("payload")
            if isinstance(payload_raw, str) and payload_raw.strip():
                payload = json.loads(payload_raw)
            elif isinstance(payload_raw, dict):
                payload = payload_raw
            else:
                payload = None

            dados = TarefaAgendadaCriar(
                titulo=argumentos.get("titulo", "Tarefa agendada"),
                descricao=argumentos.get("descricao"),
                sessao_id=argumentos.get("sessao_id"),
                agente_id=argumentos.get("agente_id"),
                telefone_destino=argumentos.get("telefone_destino"),
                tipo=TipoAgendamento(argumentos.get("tipo", "once")),
                quando=argumentos["quando"],
                acao=AcaoAgendamento(argumentos["acao_tarefa"]),
                payload=payload,
                max_execucoes=argumentos.get("max_execucoes"),
            )
            tarefa = AgendamentoService.criar(db, dados)
            return {
                "sucesso": True,
                "id": tarefa.id,
                "titulo": tarefa.titulo,
                "proxima_execucao": tarefa.proxima_execucao.isoformat() if tarefa.proxima_execucao else None,
                "mensagem": f"Tarefa '{tarefa.titulo}' agendada (ID {tarefa.id})",
            }

        elif acao == "listar":
            status_filtro = argumentos.get("status")
            telefone = argumentos.get("telefone_destino")
            sessao_id = argumentos.get("sessao_id")
            status_enum = StatusAgendamento(status_filtro) if status_filtro else None
            items = AgendamentoService.listar(db, status=status_enum, telefone=telefone, sessao_id=sessao_id)
            return {
                "total": len(items),
                "tarefas": [
                    {
                        "id": t.id,
                        "titulo": t.titulo,
                        "tipo": t.tipo.value,
                        "quando": t.quando,
                        "acao": t.acao.value,
                        "status": t.status.value,
                        "telefone_destino": t.telefone_destino,
                        "proxima_execucao": t.proxima_execucao.isoformat() if t.proxima_execucao else None,
                        "total_execucoes": t.total_execucoes,
                    }
                    for t in items
                ],
            }

        elif acao == "obter":
            tid = argumentos["tarefa_id"]
            t = AgendamentoService.obter_por_id(db, tid)
            if not t:
                return {"erro": "Tarefa não encontrada"}
            return {
                "tarefa": {
                    "id": t.id,
                    "titulo": t.titulo,
                    "descricao": t.descricao,
                    "tipo": t.tipo.value,
                    "quando": t.quando,
                    "acao": t.acao.value,
                    "payload_json": t.payload_json,
                    "status": t.status.value,
                    "resultado": t.resultado,
                    "erro": t.erro,
                    "proxima_execucao": t.proxima_execucao.isoformat() if t.proxima_execucao else None,
                    "ultima_execucao": t.ultima_execucao.isoformat() if t.ultima_execucao else None,
                    "total_execucoes": t.total_execucoes,
                    "max_execucoes": t.max_execucoes,
                }
            }

        elif acao == "cancelar":
            tid = argumentos["tarefa_id"]
            ok = AgendamentoService.cancelar(db, tid)
            return {"sucesso": ok, "mensagem": "Tarefa cancelada" if ok else "Tarefa não encontrada"}

        elif acao == "deletar":
            tid = argumentos["tarefa_id"]
            ok = AgendamentoService.deletar(db, tid)
            return {"sucesso": ok, "mensagem": "Tarefa removida" if ok else "Tarefa não encontrada"}

        else:
            return {"erro": f"Ação '{acao}' inválida. Use: criar, listar, obter, cancelar, deletar"}
    except Exception as e:
        return {"erro": str(e)}


# ── Registra handlers no NATIVE_REGISTRY ──────────────────────────
NATIVE_REGISTRY.update({
    "fluxi_ferramentas": _native_fluxi_ferramentas,
    "fluxi_skills":      _native_fluxi_skills,
    "fluxi_agentes":     _native_fluxi_agentes,
    "fluxi_mcp":         _native_fluxi_mcp,
    "fluxi_rag":         _native_fluxi_rag,
    "fluxi_agendamento": _native_fluxi_agendamento,
})
