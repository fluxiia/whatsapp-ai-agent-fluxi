"""
Serviço de lógica de negócio para provedores LLM.
"""
import logging
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
import httpx
import json
import time
from datetime import datetime
from llm_providers.llm_providers_model import ProvedorLLM, EstatisticasProvedor, ModeloProvedor, StatusProvedorEnum
from llm_providers.llm_providers_schema import (
    ProvedorLLMCriar,
    ProvedorLLMAtualizar,
    TesteConexaoResposta,
    ModeloLLM,
    RequisicaoLLM,
    RespostaLLM,
    ConfiguracaoProvedor,
    EstatisticasProvedor as EstatisticasProvedorSchema
)

logger = logging.getLogger(__name__)


class ProvedorLLMService:
    """Serviço para gerenciar provedores LLM."""

    @staticmethod
    def listar_todos(db: Session) -> List[ProvedorLLM]:
        """Lista todos os provedores."""
        return db.query(ProvedorLLM).all()

    @staticmethod
    def listar_ativos(db: Session) -> List[ProvedorLLM]:
        """Lista apenas provedores ativos."""
        return db.query(ProvedorLLM).filter(ProvedorLLM.ativo == True).all()

    @staticmethod
    def obter_por_id(db: Session, provedor_id: int) -> Optional[ProvedorLLM]:
        """Obtém um provedor por ID."""
        return db.query(ProvedorLLM).filter(ProvedorLLM.id == provedor_id).first()


    @staticmethod
    def criar(db: Session, provedor: ProvedorLLMCriar) -> ProvedorLLM:
        """Cria um novo provedor."""
        # Converter dados para formato compatível com SQLAlchemy
        dados = provedor.model_dump()
        dados['base_url'] = str(dados['base_url'])  # Converter HttpUrl para string
        
        db_provedor = ProvedorLLM(**dados)
        db.add(db_provedor)
        db.commit()
        db.refresh(db_provedor)
        
        # Criar estatísticas iniciais
        stats = EstatisticasProvedor(provedor_id=db_provedor.id)
        db.add(stats)
        db.commit()
        
        return db_provedor

    @staticmethod
    def atualizar(db: Session, provedor_id: int, provedor: ProvedorLLMAtualizar) -> Optional[ProvedorLLM]:
        """Atualiza um provedor existente."""
        db_provedor = ProvedorLLMService.obter_por_id(db, provedor_id)
        if not db_provedor:
            return None

        update_data = provedor.model_dump(exclude_unset=True)
        
        # Converter dados para formato compatível com SQLAlchemy
        for campo, valor in update_data.items():
            if campo == 'base_url' and hasattr(valor, '__str__'):
                valor = str(valor)
            setattr(db_provedor, campo, valor)

        db.commit()
        db.refresh(db_provedor)
        return db_provedor

    @staticmethod
    def deletar(db: Session, provedor_id: int) -> bool:
        """Deleta um provedor."""
        db_provedor = ProvedorLLMService.obter_por_id(db, provedor_id)
        if not db_provedor:
            return False

        # Verificar se há agentes vinculados a este provedor
        from agente.agente_model import Agente
        agentes_vinculados = db.query(Agente).filter(Agente.modelo_llm.contains(db_provedor.nome)).count()
        
        if agentes_vinculados > 0:
            raise ValueError(f"Não é possível remover o provedor '{db_provedor.nome}' pois ele está sendo usado por {agentes_vinculados} agente(s). Remova os vínculos primeiro.")

        # Deletar estatísticas relacionadas
        db.query(EstatisticasProvedor).filter(EstatisticasProvedor.provedor_id == provedor_id).delete()
        db.query(ModeloProvedor).filter(ModeloProvedor.provedor_id == provedor_id).delete()
        
        db.delete(db_provedor)
        db.commit()
        return True

    @staticmethod
    async def buscar_modelos_api(provedor: ProvedorLLM) -> List[str]:
        """Busca modelos disponíveis na API do provedor."""
        import httpx
        
        try:
            headers = {}
            if provedor.api_key:
                headers["Authorization"] = f"Bearer {provedor.api_key}"
            
            base_url = str(provedor.base_url).rstrip('/')
            # Verificar se base_url já contém /v1 para evitar duplicação
            if base_url.endswith('/v1') or '/v1/' in base_url:
                models_url = f"{base_url}/models"
            else:
                models_url = f"{base_url}/v1/models"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    models_url,
                    headers=headers
                )
                response.raise_for_status()
                
                data = response.json()
                modelos = []
                
                if "data" in data:
                    for model in data["data"]:
                        if "id" in model:
                            modelos.append(model["id"])
                
                return modelos
                
        except Exception as e:
            logger.warning("Erro ao buscar modelos: %s", e)
            return []

    @staticmethod
    async def testar_conexao(db: Session, provedor_id: int) -> TesteConexaoResposta:
        """Testa a conexão com um provedor e busca modelos disponíveis."""
        provedor = ProvedorLLMService.obter_por_id(db, provedor_id)
        if not provedor:
            return TesteConexaoResposta(
                sucesso=False,
                mensagem="Provedor não encontrado"
            )

        inicio_teste = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Construir URL base
                base_url = str(provedor.base_url).rstrip('/')
                headers = {"Content-Type": "application/json"}
                if provedor.api_key:
                    headers["Authorization"] = f"Bearer {provedor.api_key}"
                
                # Tentar detectar tipo de provedor automaticamente
                # Primeiro tenta OpenAI-compatível (LM Studio, llama.cpp, etc.)
                # Verificar se base_url já contém os caminhos para evitar duplicação
                if base_url.endswith('/v1') or '/v1/' in base_url:
                    url_openai = f"{base_url}/models"
                else:
                    url_openai = f"{base_url}/v1/models"
                
                if base_url.endswith('/api') or '/api/' in base_url:
                    url_ollama = f"{base_url}/tags"
                else:
                    url_ollama = f"{base_url}/api/tags"
                
                response = None
                tipo_detectado = None
                
                # Tenta endpoint OpenAI primeiro
                try:
                    response = await client.get(url_openai, headers=headers)
                    if response.status_code == 200:
                        tipo_detectado = "openai"
                except:
                    pass
                
                # Se falhou, tenta endpoint Ollama
                if not response or response.status_code != 200:
                    try:
                        response = await client.get(url_ollama, headers=headers)
                        if response.status_code == 200:
                            tipo_detectado = "ollama"
                    except:
                        pass
                
                tempo_resposta = (time.time() - inicio_teste) * 1000

                if response and response.status_code == 200:
                    data = response.json()
                    modelos = []

                    if tipo_detectado == "ollama":
                        # Ollama retorna estrutura diferente
                        for modelo_data in data.get("models", []):
                            modelo = ModeloLLM(
                                id=modelo_data.get("name", ""),
                                nome=modelo_data.get("name", ""),
                                contexto=modelo_data.get("details", {}).get("parameter_size"),
                                suporta_imagens="llava" in modelo_data.get("name", "").lower() or 
                                              "bakllava" in modelo_data.get("name", "").lower(),
                                suporta_ferramentas=False,  # Ollama não suporta nativamente
                                tamanho=modelo_data.get("size"),
                                quantizacao=modelo_data.get("details", {}).get("quantization_level")
                            )
                            modelos.append(modelo)
                    else:
                        # LM Studio e llama.cpp usam formato OpenAI
                        for modelo_data in data.get("data", []):
                            modelo = ModeloLLM(
                                id=modelo_data.get("id", ""),
                                nome=modelo_data.get("id", ""),
                                contexto=modelo_data.get("context_length"),
                                suporta_imagens="vision" in modelo_data.get("id", "").lower(),
                                suporta_ferramentas="tools" in str(modelo_data.get("capabilities", [])),
                                tamanho=None,
                                quantizacao=None
                            )
                            modelos.append(modelo)

                    # Atualizar status do provedor
                    provedor.status = StatusProvedorEnum.ATIVO
                    provedor.ultimo_teste = datetime.now()
                    db.commit()

                    # Salvar/cachear modelos
                    ProvedorLLMService._salvar_modelos(db, provedor_id, modelos)

                    return TesteConexaoResposta(
                        sucesso=True,
                        mensagem=f"Conexão bem-sucedida ({tipo_detectado}). {len(modelos)} modelos encontrados",
                        modelos=modelos,
                        tempo_resposta_ms=tempo_resposta
                    )
                else:
                    provedor.status = StatusProvedorEnum.ERRO
                    provedor.ultimo_teste = datetime.now()
                    db.commit()
                    
                    erro_msg = response.text if response else "Nenhuma resposta do servidor"
                    status_code = response.status_code if response else "N/A"
                    
                    return TesteConexaoResposta(
                        sucesso=False,
                        mensagem=f"Erro HTTP {status_code}: {erro_msg}",
                        tempo_resposta_ms=tempo_resposta
                    )

        except httpx.TimeoutException:
            provedor.status = StatusProvedorEnum.ERRO
            provedor.ultimo_teste = datetime.now()
            db.commit()
            
            return TesteConexaoResposta(
                sucesso=False,
                mensagem="Timeout ao conectar com o provedor"
            )
        except Exception as e:
            provedor.status = StatusProvedorEnum.ERRO
            provedor.ultimo_teste = datetime.now()
            db.commit()
            
            return TesteConexaoResposta(
                sucesso=False,
                mensagem=f"Erro: {str(e)}"
            )

    @staticmethod
    def _salvar_modelos(db: Session, provedor_id: int, modelos: List[ModeloLLM]):
        """Salva modelos no cache do banco."""
        # Limpar modelos antigos
        db.query(ModeloProvedor).filter(ModeloProvedor.provedor_id == provedor_id).delete()
        
        # Salvar novos modelos
        for modelo in modelos:
            db_modelo = ModeloProvedor(
                provedor_id=provedor_id,
                modelo_id=modelo.id,
                nome=modelo.nome,
                contexto=modelo.contexto,
                suporta_imagens=modelo.suporta_imagens,
                suporta_ferramentas=modelo.suporta_ferramentas,
                tamanho=modelo.tamanho,
                quantizacao=modelo.quantizacao
            )
            db.add(db_modelo)
        
        db.commit()

    @staticmethod
    def obter_modelos(db: Session, provedor_id: int) -> List[ModeloProvedor]:
        """Obtém modelos disponíveis para um provedor."""
        return db.query(ModeloProvedor).filter(
            ModeloProvedor.provedor_id == provedor_id,
            ModeloProvedor.ativo == True
        ).all()

    @staticmethod
    async def enviar_requisicao(db: Session, provedor_id: int, requisicao: RequisicaoLLM) -> RespostaLLM:
        """Envia uma requisição para um provedor LLM."""
        provedor = ProvedorLLMService.obter_por_id(db, provedor_id)
        if not provedor:
            raise ValueError("Provedor não encontrado")

        if not provedor.ativo:
            raise ValueError("Provedor não está ativo")

        inicio_requisicao = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                base_url = str(provedor.base_url).rstrip('/')
                headers = {"Content-Type": "application/json"}
                if provedor.api_key:
                    headers["Authorization"] = f"Bearer {provedor.api_key}"
                
                # Tentar detectar tipo automaticamente pelo URL ou tentar ambos
                tipo_detectado = None
                response = None
                
                # Primeiro tenta endpoint OpenAI-compatível
                # Verificar se base_url já contém /v1 para evitar duplicação
                if base_url.endswith('/v1') or '/v1/' in base_url:
                    url_openai = f"{base_url}/chat/completions"
                else:
                    url_openai = f"{base_url}/v1/chat/completions"
                payload_openai = {
                    "model": requisicao.modelo,
                    "messages": requisicao.mensagens,
                    "stream": requisicao.stream
                }

                
                # Adicionar tools se disponíveis
                if requisicao.tools:
                    payload_openai["tools"] = requisicao.tools
                    logger.info(
                        "[PROVEDOR_LOCAL] Enviando %d tools para API OpenAI-compatível",
                        len(requisicao.tools),
                    )
                
                if requisicao.configuracao:
                    payload_openai.update({
                        "temperature": requisicao.configuracao.temperatura,
                        "max_tokens": requisicao.configuracao.max_tokens,
                        "top_p": requisicao.configuracao.top_p,
                        "stop": requisicao.configuracao.stop
                    })
             
                try:
                    response = await client.post(url_openai, json=payload_openai, headers=headers)
                    if response.status_code == 200:
                        tipo_detectado = "openai"
                except Exception as _openai_err:
                    logger.warning(
                        "[PROVEDOR_LOCAL] OpenAI endpoint falhou: %s: %s",
                        type(_openai_err).__name__,
                        _openai_err,
                    )
                
                # Se falhou, tenta endpoint Ollama
                if not response or response.status_code != 200:
                    url_ollama = f"{base_url}/api/chat"
                    payload_ollama = {
                        "model": requisicao.modelo,
                        "messages": requisicao.mensagens,
                        "stream": requisicao.stream
                    }
                    
                    # Adicionar tools para Ollama
                    if requisicao.tools:
                        payload_ollama["tools"] = requisicao.tools
                        logger.info(
                            "[PROVEDOR_LOCAL] Enviando %d tools para API Ollama",
                            len(requisicao.tools),
                        )
                    
                    if requisicao.configuracao:
                        payload_ollama["options"] = {
                            "temperature": requisicao.configuracao.temperatura,
                            "num_predict": requisicao.configuracao.max_tokens,
                            "top_p": requisicao.configuracao.top_p,
                            "top_k": requisicao.configuracao.top_k,
                            "repeat_penalty": requisicao.configuracao.repeat_penalty,
                            "stop": requisicao.configuracao.stop
                        }
                    
                    try:
                        response = await client.post(url_ollama, json=payload_ollama, headers=headers)
                        if response.status_code == 200:
                            tipo_detectado = "ollama"
                    except Exception as _ollama_err:
                        logger.warning(
                            "[PROVEDOR_LOCAL] Ollama endpoint falhou: %s: %s",
                            type(_ollama_err).__name__,
                            _ollama_err,
                        )

                tempo_geracao = (time.time() - inicio_requisicao) * 1000

                if response and response.status_code == 200:
                    data = response.json()
                    
                    # Extrair resposta baseado no tipo
                    tool_calls = None
                    finish_reason = None
                    print(data)
                    if tipo_detectado == "ollama":
                        message = data.get("message", {})
                        conteudo = message.get("content", "")
                        tokens_usados = data.get("eval_count")
                        tool_calls = message.get("tool_calls")
                        finish_reason = data.get("done_reason")
                    else:
                        # OpenAI-compatível
                        choice = data.get("choices", [{}])[0]
                        message = choice.get("message", {})
                        conteudo = message.get("content", "")
                        tokens_usados = data.get("usage", {}).get("total_tokens")
                        tool_calls = message.get("tool_calls")
                        finish_reason = choice.get("finish_reason")
                    
                    if tool_calls:
                        logger.info(
                            "[PROVEDOR_LOCAL] Resposta contém %d tool_calls",
                            len(tool_calls),
                        )

                    # Atualizar estatísticas
                    ProvedorLLMService._atualizar_estatisticas(db, provedor_id, True, tempo_geracao)

                    return RespostaLLM(
                        conteudo=conteudo or "",
                        modelo=requisicao.modelo,
                        tokens_usados=tokens_usados,
                        tempo_geracao_ms=tempo_geracao,
                        tool_calls=tool_calls,
                        finish_reason=finish_reason
                    )
                else:
                    ProvedorLLMService._atualizar_estatisticas(db, provedor_id, False, tempo_geracao)
                    erro_msg = response.text if response else "Nenhuma resposta do servidor"
                    status_code = response.status_code if response else "N/A"
                    raise Exception(f"Erro HTTP {status_code}: {erro_msg}")

        except Exception as e:
            ProvedorLLMService._atualizar_estatisticas(db, provedor_id, False, 0)
            raise e

    @staticmethod
    def _atualizar_estatisticas(db: Session, provedor_id: int, sucesso: bool, tempo_ms: float):
        """Atualiza estatísticas do provedor."""
        stats = db.query(EstatisticasProvedor).filter(
            EstatisticasProvedor.provedor_id == provedor_id
        ).first()
        
        if not stats:
            stats = EstatisticasProvedor(provedor_id=provedor_id)
            db.add(stats)
        
        stats.total_requisicoes += 1
        if sucesso:
            stats.requisicoes_sucesso += 1
        else:
            stats.requisicoes_erro += 1
        
        # Calcular tempo médio
        if stats.tempo_medio_ms == 0:
            stats.tempo_medio_ms = tempo_ms
        else:
            stats.tempo_medio_ms = (stats.tempo_medio_ms + tempo_ms) / 2
        
        stats.ultima_requisicao = datetime.now()
        db.commit()

    @staticmethod
    def obter_estatisticas(db: Session, provedor_id: int) -> Optional[EstatisticasProvedorSchema]:
        """Obtém estatísticas de um provedor."""
        stats = db.query(EstatisticasProvedor).filter(
            EstatisticasProvedor.provedor_id == provedor_id
        ).first()
        
        if not stats:
            return None
        
        return EstatisticasProvedorSchema(
            total_requisicoes=stats.total_requisicoes,
            requisicoes_sucesso=stats.requisicoes_sucesso,
            requisicoes_erro=stats.requisicoes_erro,
            tempo_medio_ms=stats.tempo_medio_ms,
            ultima_requisicao=stats.ultima_requisicao,
            modelos_carregados=stats.modelos_carregados or []
        )
