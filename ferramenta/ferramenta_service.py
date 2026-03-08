"""
Serviço de lógica de negócio para ferramentas.
"""
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
import json
import re
import httpx
from datetime import datetime
from ferramenta.ferramenta_model import Ferramenta, ToolType, ToolScope
from ferramenta.ferramenta_schema import FerramentaCriar, FerramentaAtualizar
from config.config_service import ConfiguracaoService


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
        Substitui variáveis no formato {variavel}, {var.CHAVE} ou {env.VARIAVEL}.
        
        Ordem de prioridade:
        1. {var.CHAVE} - Variáveis da ferramenta (do banco)
        2. {variavel} - Variáveis passadas como argumento
        3. {resultado.campo} - Variáveis aninhadas
        4. {env.VARIAVEL} - Variáveis de ambiente (fallback)
        """
        import os
        
        def replacer(match):
            var_name = match.group(1)
            
            # 1. Variável da ferramenta (do banco)
            if var_name.startswith("var."):
                var_key = var_name[4:]
                if variaveis_ferramenta and var_key in variaveis_ferramenta:
                    return variaveis_ferramenta[var_key]
                return match.group(0)  # Manter original se não encontrar
            
            # 2. Variável de ambiente (fallback)
            if var_name.startswith("env."):
                env_var = var_name[4:]
                return os.getenv(env_var, f"{{{var_name}}}")
            
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
                        return match.group(0)  # Manter original se não encontrar
                return str(valor) if not isinstance(valor, (dict, list)) else json.dumps(valor)
            
            return match.group(0)  # Manter original se não encontrar
        
        # Regex mais específico: captura apenas nomes de variáveis válidos (letras, números, _, .)
        # Isso evita capturar o JSON externo como {"q": ...}
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
        telefone_cliente: Optional[str] = None
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
        else:
            return {"erro": f"Tipo de ferramenta '{ferramenta.tool_type}' não suportado"}
        
        # Se há próxima ferramenta, executar em cadeia
        if ferramenta.next_tool and not resultado.get("erro"):
            # Mesclar resultado com argumentos para próxima ferramenta
            novos_argumentos = {**argumentos, "resultado": resultado}
            return await FerramentaService.executar_ferramenta(
                db, ferramenta.next_tool, novos_argumentos, sessao_id, telefone_cliente
            )
        
        # Processar output da ferramenta
        return await FerramentaService.processar_output_ferramenta(
            db, ferramenta, resultado, sessao_id, telefone_cliente
        )

    @staticmethod
    async def processar_output_ferramenta(
        db: Session,
        ferramenta: Ferramenta,
        resultado: Dict[str, Any],
        sessao_id: Optional[int] = None,
        telefone_cliente: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Processa o output da ferramenta de acordo com as configurações.
        Envia para LLM, usuário ou ambos.
        """
        from ferramenta.ferramenta_model import OutputDestination, ChannelType
        
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
                        db, ferramenta, resultado, sessao_id, telefone_cliente
                    )
                except Exception as e:
                    print(f"❌ Erro ao enviar para usuário: {e}")
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
        telefone_cliente: str
    ) -> bool:
        """
        Envia o resultado da ferramenta para o usuário via WhatsApp.
        Suporta diferentes tipos de canal (text, image, audio, video, document).
        """
        from sessao.sessao_service import gerenciador_sessoes
        from neonize.utils import build_jid
        from ferramenta.ferramenta_model import ChannelType
        
        # Obter cliente WhatsApp
        cliente = gerenciador_sessoes.obter_cliente(sessao_id)
        if not cliente:
            print(f"⚠️  Cliente WhatsApp não encontrado para sessão {sessao_id}")
            return False
        
        jid = build_jid(telefone_cliente)
        channel = ferramenta.channel or ChannelType.TEXT
        
        try:
            if channel == ChannelType.TEXT:
                # Enviar como texto
                texto = FerramentaService.formatar_resultado_texto(resultado, ferramenta)
                cliente.send_message(jid, message=texto)
                print(f"📤 Texto enviado para {telefone_cliente}")
                return True
                
            elif channel == ChannelType.IMAGE:
                # Enviar como imagem
                return await FerramentaService.enviar_imagem(
                    cliente, jid, resultado, ferramenta
                )
                
            elif channel == ChannelType.AUDIO:
                # Enviar como áudio
                return await FerramentaService.enviar_audio(
                    cliente, jid, resultado, ferramenta
                )
                
            elif channel == ChannelType.VIDEO:
                # Enviar como vídeo
                return await FerramentaService.enviar_video(
                    cliente, jid, resultado, ferramenta
                )
                
            elif channel == ChannelType.DOCUMENT:
                # Enviar como documento
                return await FerramentaService.enviar_documento(
                    cliente, jid, resultado, ferramenta
                )
            
            return False
            
        except Exception as e:
            print(f"❌ Erro ao enviar para usuário: {e}")
            import traceback
            traceback.print_exc()
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
                # Enviar imagem diretamente (suporta LID JIDs)
                cliente.send_image(jid, imagem_data, caption=caption)
                print(f"🖼️  Imagem enviada")
                return True
            
            return False
            
        except Exception as e:
            print(f"❌ Erro ao enviar imagem: {e}")
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
                # Enviar áudio
                cliente.send_audio(
                    jid,
                    audio_data,
                    ptt=resultado.get("ptt", False)  # Voice message
                )
                print(f"🎵 Áudio enviado")
                return True
            
            return False
            
        except Exception as e:
            print(f"❌ Erro ao enviar áudio: {e}")
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
                print(f"🎬 Vídeo enviado")
                return True
            
            return False
            
        except Exception as e:
            print(f"❌ Erro ao enviar vídeo: {e}")
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
                print(f"📄 Documento enviado")
                return True
            
            return False
            
        except Exception as e:
            print(f"❌ Erro ao enviar documento: {e}")
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
            {
                "nome": "obter_data_hora_atual",
                "descricao": "Obtém a data e hora atual no formato brasileiro",
                "tool_type": ToolType.CODE,
                "tool_scope": ToolScope.PRINCIPAL,
                "params": json.dumps({}),  # Sem parâmetros
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
    # Avaliar expressão de forma segura
    expressao = argumentos.get("expressao", "")
    # Permitir apenas operações matemáticas seguras
    allowed_chars = set("0123456789+-*/().** ")
    if all(c in allowed_chars for c in expressao):
        resultado_calculo = eval(expressao)
        resultado = {
            "expressao": expressao,
            "resultado": resultado_calculo
        }
    else:
        resultado = {"erro": "Expressão contém caracteres não permitidos"}
except Exception as e:
    resultado = {"erro": f"Erro ao calcular: {str(e)}"}
""",
                "substituir": False,
                "output": "llm",
                "ativa": True
            }
        ]
        
        for ferramenta_data in ferramentas_padrao:
            # Verificar se já existe
            existe = FerramentaService.obter_por_nome(db, ferramenta_data["nome"])
            if not existe:
                ferramenta = FerramentaCriar(**ferramenta_data)
                FerramentaService.criar(db, ferramenta)
