"""
Serviço de integração LLM que gerencia a escolha do provedor correto.
"""
import logging
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List, Callable, Awaitable
import httpx
import json
import time
from config.config_service import ConfiguracaoService
from llm_providers.llm_providers_service import ProvedorLLMService
from llm_providers.llm_providers_schema import RequisicaoLLM, ConfiguracaoProvedor
from log.log_service import fluxi_log

logger = logging.getLogger(__name__)


class LLMIntegrationService:
    """Serviço para integrar diferentes provedores LLM de forma transparente."""

    @staticmethod
    async def processar_mensagem_com_llm(
        db: Session,
        messages: List[Dict[str, Any]],
        modelo: str,
        agente_id: Optional[int] = None,
        temperatura: float = 0.7,
        max_tokens: int = 2000,
        top_p: float = 1.0,
        frequency_penalty: float = 0.0,
        presence_penalty: float = 0.0,
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
        on_text_delta: Optional[Callable[[str], Awaitable[None]]] = None,
        reasoning: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Processa mensagem usando o provedor LLM apropriado.

        Args:
            db: Sessão do banco
            messages: Lista de mensagens no formato OpenAI
            modelo: Nome do modelo a usar
            agente_id: ID do agente (para configurações específicas)
            temperatura: Temperatura para geração
            max_tokens: Máximo de tokens
            top_p: Top P para amostragem
            frequency_penalty: Penalidade de frequência (-2.0 a 2.0)
            presence_penalty: Penalidade de presença (-2.0 a 2.0)
            tools: Lista de ferramentas disponíveis
            stream: Se deve usar streaming
            on_text_delta: Callback para streaming de texto
            reasoning: Configuração de reasoning tokens (OpenRouter).
                       Ex: {"effort": "high"} ou {"max_tokens": 4000}

        Returns:
            Dict com resposta do LLM (inclui "reasoning" se disponível)
        """
        inicio = time.time()

        # 1. Determinar qual provedor usar
        provedor_info = await LLMIntegrationService._determinar_provedor(
            db, modelo, agente_id
        )

        n_tools = len(tools) if tools else 0
        fluxi_log.info("llm", "request", "Iniciando chamada LLM", extra={
            "provedor": provedor_info["tipo"],
            "modelo": modelo,
            "n_mensagens": len(messages),
            "n_tools": n_tools,
            "max_tokens": max_tokens,
            "stream": bool(on_text_delta) or stream,
        })

        # 2. Fazer a requisição usando o provedor apropriado
        try:
            if provedor_info["tipo"] == "local":
                # Streaming de tokens só no OpenRouter por enquanto
                if on_text_delta:
                    stream = False
                resultado = await LLMIntegrationService._usar_provedor_local(
                    db, provedor_info, messages, modelo, temperatura,
                    max_tokens, top_p, frequency_penalty, presence_penalty, tools, stream
                )
            elif provedor_info["tipo"] == "openrouter":
                resultado = await LLMIntegrationService._usar_openrouter(
                    db, messages, modelo, temperatura, max_tokens, top_p,
                    frequency_penalty, presence_penalty, tools, stream, on_text_delta,
                    reasoning=reasoning,
                )
            else:
                raise ValueError(f"Tipo de provedor não suportado: {provedor_info['tipo']}")
            
            # 3. Adicionar metadados
            resultado["provedor_usado"] = provedor_info["tipo"]
            resultado["provedor_id"] = provedor_info.get("id")
            resultado["tempo_total_ms"] = (time.time() - inicio) * 1000

            fluxi_log.info("llm", "response", "Resposta LLM recebida", extra={
                "provedor": provedor_info["tipo"],
                "modelo": resultado.get("modelo", modelo),
                "tokens_in": resultado.get("tokens_input", 0),
                "tokens_out": resultado.get("tokens_output", 0),
                "finish_reason": resultado.get("finish_reason"),
                "n_tool_calls": len(resultado.get("tool_calls") or []),
                "tempo_ms": int(resultado["tempo_total_ms"]),
            })

            return resultado
            
        except Exception as e:
            tempo_ate_erro = int((time.time() - inicio) * 1000)
            fluxi_log.error("llm", "request", "Erro na chamada LLM", exc_info=True, extra={
                "provedor": provedor_info["tipo"],
                "modelo": modelo,
                "tempo_ms": tempo_ate_erro,
                "erro_tipo": type(e).__name__,
            })

            # 4. Fallback para OpenRouter se configurado E disponível
            fallback_habilitado = ConfiguracaoService.obter_valor(
                db, "llm_fallback_openrouter", True
            )
            openrouter_disponivel = LLMIntegrationService._openrouter_disponivel(db)

            if (provedor_info["tipo"] != "openrouter" and
                fallback_habilitado and
                openrouter_disponivel):
                fluxi_log.warning("llm", "fallback", "Tentando fallback para OpenRouter", extra={
                    "provedor_original": provedor_info["tipo"],
                    "erro_original": str(e)[:200],
                })
                logger.warning(
                    "Erro com provedor %s, tentando OpenRouter: %s",
                    provedor_info["tipo"],
                    e,
                )
                try:
                    resultado = await LLMIntegrationService._usar_openrouter(
                        db, messages, modelo, temperatura, max_tokens, top_p,
                        frequency_penalty, presence_penalty, tools, stream, on_text_delta,
                        reasoning=reasoning,
                    )
                    resultado["provedor_usado"] = "openrouter_fallback"
                    resultado["erro_original"] = str(e)
                    resultado["tempo_total_ms"] = (time.time() - inicio) * 1000
                    return resultado
                except Exception as fallback_error:
                    raise Exception(f"Erro no provedor principal e no fallback: {e} | {fallback_error}")
            else:
                raise e

    @staticmethod
    async def _determinar_provedor(
        db: Session, 
        modelo: str, 
        agente_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Determina qual provedor usar baseado no modelo e configurações."""
        
        # 1. Verificar configuração global primeiro
        provedor_padrao = ConfiguracaoService.obter_valor(db, "llm_provedor_padrao", "auto")
        
        # 2. Se configurado para local, tentar usar provedor local específico
        if provedor_padrao == "local":
            provedor_local_id = ConfiguracaoService.obter_valor(db, "llm_provedor_local_id")
            if provedor_local_id:
                provedor = ProvedorLLMService.obter_por_id(db, int(provedor_local_id))
                if provedor and provedor.ativo:
                    return {
                        "tipo": "local",
                        "id": provedor.id,
                        "provedor": provedor,
                        "motivo": "configuracao_local"
                    }
        
        # 3. Se configurado para OpenRouter E tem chave, usar
        if provedor_padrao == "openrouter" and LLMIntegrationService._openrouter_disponivel(db):
            return {"tipo": "openrouter", "motivo": "configuracao_openrouter"}
        
        # 4. Tentar encontrar qualquer provedor disponível (modo auto ou fallback)
        # 4.1 Primeiro verificar provedores locais ativos
        provedores_ativos = ProvedorLLMService.listar_ativos(db)
        if provedores_ativos:
            provedor = provedores_ativos[0]  # Usar primeiro provedor ativo
            logger.info(
                "Usando provedor local: %s (%s)", provedor.nome, provedor.base_url
            )
            return {
                "tipo": "local",
                "id": provedor.id,
                "provedor": provedor,
                "motivo": "auto_local"
            }
        
        # 4.2 Verificar se modelo é específico do OpenRouter (Gemini, Claude, etc.)
        modelos_openrouter = [
            "google/gemini", "anthropic/claude", "openai/gpt", 
            "mistralai/mistral", "cohere/command"
        ]
        
        if any(modelo.startswith(prefix) for prefix in modelos_openrouter):
            if LLMIntegrationService._openrouter_disponivel(db):
                return {"tipo": "openrouter", "motivo": "modelo_especifico_openrouter"}
            else:
                raise ValueError(
                    f"Modelo '{modelo}' requer OpenRouter, mas a API Key não está configurada. "
                    "Configure a chave em Configurações ou use um modelo local."
                )
        
        # 4.3 Fallback para OpenRouter se disponível
        if LLMIntegrationService._openrouter_disponivel(db):
            return {"tipo": "openrouter", "motivo": "fallback_padrao"}
        
        # 5. Nenhum provedor disponível
        raise ValueError(
            "Nenhum provedor LLM disponível. "
            "Configure um provedor local em 'Provedores LLM' ou adicione sua chave de API do OpenRouter em 'Configurações'."
        )

    @staticmethod
    def _openrouter_disponivel(db: Session) -> bool:
        """Verifica se o OpenRouter está disponível (tem chave configurada)."""
        api_key = ConfiguracaoService.obter_valor(db, "openrouter_api_key")
        return api_key is not None and api_key.strip() != ""
    
    @staticmethod
    async def _usar_provedor_local(
        db: Session,
        provedor_info: Dict[str, Any],
        messages: List[Dict[str, Any]],
        modelo: str,
        temperatura: float,
        max_tokens: int,
        top_p: float,
        frequency_penalty: float,
        presence_penalty: float,
        tools: Optional[List[Dict]],
        stream: bool
    ) -> Dict[str, Any]:
        """Usa um provedor local via llm_providers."""
        
        # Log de debug para tools
        if tools:
            logger.info("[LLM_LOCAL] Passando %d tools para o provedor local", len(tools))
        
        # Preparar requisição
        requisicao = RequisicaoLLM(
            mensagens=messages,
            modelo=modelo,
            configuracao=ConfiguracaoProvedor(
                temperatura=temperatura,
                max_tokens=max_tokens,
                top_p=top_p,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty
            ),
            tools=tools,  # Passar tools para o provedor local
            stream=stream
        )
        
        # Enviar requisição
        resposta = await ProvedorLLMService.enviar_requisicao(
            db, provedor_info["id"], requisicao
        )
        
        # Log de debug
        if resposta.tool_calls:
            logger.info(
                "[LLM_LOCAL] Resposta contém %d tool_calls", len(resposta.tool_calls)
            )
        
        # Converter para formato padrão
        return {
            "conteudo": resposta.conteudo,
            "modelo": resposta.modelo,
            "tokens_input": None,  # Provedores locais podem não retornar
            "tokens_output": resposta.tokens_usados,
            "tempo_geracao_ms": resposta.tempo_geracao_ms,
            "tool_calls": resposta.tool_calls,
            "finish_reason": resposta.finish_reason,
            "finalizado": resposta.finalizado
        }

    @staticmethod
    async def _usar_openrouter(
        db: Session,
        messages: List[Dict[str, Any]],
        modelo: str,
        temperatura: float,
        max_tokens: int,
        top_p: float,
        frequency_penalty: float,
        presence_penalty: float,
        tools: Optional[List[Dict]],
        stream: bool,
        on_text_delta: Optional[Callable[[str], Awaitable[None]]] = None,
        reasoning: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Usa OpenRouter diretamente."""

        if on_text_delta:
            return await LLMIntegrationService._usar_openrouter_stream(
                db,
                messages,
                modelo,
                temperatura,
                max_tokens,
                top_p,
                frequency_penalty,
                presence_penalty,
                tools,
                on_text_delta,
                reasoning=reasoning,
            )

        # Buscar API key do OpenRouter
        api_key = ConfiguracaoService.obter_valor(db, "openrouter_api_key")
        if not api_key:
            raise ValueError("API Key do OpenRouter não configurada")

        # Preparar payload
        payload = {
            "model": modelo,
            "messages": messages,
            "temperature": temperatura,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
            "stream": stream,
        }

        if tools:
            payload["tools"] = tools
            logger.info("[OPENROUTER] Enviando %d tools para API", len(tools))

        # Reasoning tokens (OpenRouter unified API)
        if reasoning:
            payload["reasoning"] = reasoning
            logger.info("[OPENROUTER] Reasoning habilitado: %s", reasoning)

        # Fazer requisição
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://fluxi.ai",
                    "X-Title": "Fluxi WhatsApp AI Agent",
                },
                json=payload,
                timeout=180.0,  # Reasoning pode demorar mais
            )

            if response.status_code != 200:
                raise ValueError(f"Erro na API OpenRouter: {response.status_code} - {response.text}")

            data = response.json()

            # Extrair resposta
            choice = data.get("choices", [{}])[0]
            message_response = choice.get("message", {})

            # ── DEBUG: Log raw message keys e reasoning fields ──
            _msg_keys = list(message_response.keys())
            _reasoning_related = {k: type(message_response[k]).__name__
                                  for k in _msg_keys if "reason" in k.lower()}
            logger.info("[OPENROUTER] Raw message keys: %s | reasoning fields: %s",
                        _msg_keys, _reasoning_related)

            # Extrair uso de tokens
            usage = data.get("usage", {})

            # Extrair reasoning (pode vir como string ou array de blocos)
            reasoning_content = message_response.get("reasoning") or None
            reasoning_details = message_response.get("reasoning_details") or None

            # ── DEBUG: Dump detalhado da estrutura de reasoning ──
            if reasoning_content is not None:
                logger.info("[OPENROUTER] reasoning field: type=%s len=%d sample=%s",
                            type(reasoning_content).__name__,
                            len(reasoning_content) if isinstance(reasoning_content, str) else -1,
                            repr(str(reasoning_content)[:200]))
            if reasoning_details is not None:
                logger.info("[OPENROUTER] reasoning_details field: type=%s count=%s",
                            type(reasoning_details).__name__,
                            len(reasoning_details) if isinstance(reasoning_details, list) else "?")
                if isinstance(reasoning_details, list):
                    for _idx, _det in enumerate(reasoning_details[:3]):
                        if isinstance(_det, dict):
                            _det_content = _det.get("content", "")
                            logger.info("[OPENROUTER]   detail[%d]: keys=%s type=%s content_len=%d content_sample=%s",
                                        _idx, list(_det.keys()), _det.get("type", "?"),
                                        len(_det_content) if isinstance(_det_content, str) else -1,
                                        repr(str(_det_content)[:150]))
                        else:
                            logger.info("[OPENROUTER]   detail[%d]: raw_type=%s raw=%s",
                                        _idx, type(_det).__name__, repr(str(_det)[:150]))

            result = {
                "conteudo": message_response.get("content", ""),
                "modelo": data.get("model", modelo),
                "tokens_input": usage.get("prompt_tokens", 0),
                "tokens_output": usage.get("completion_tokens", 0),
                "tool_calls": message_response.get("tool_calls"),
                "finish_reason": choice.get("finish_reason"),
                "finalizado": True,
            }

            # Inclui reasoning no resultado se presente
            if reasoning_content:
                result["reasoning"] = reasoning_content
            if reasoning_details:
                result["reasoning_details"] = reasoning_details

            if reasoning_content or reasoning_details:
                r_len = len(reasoning_content) if reasoning_content else sum(
                    len(b.get("content", "")) for b in reasoning_details if isinstance(b, dict)
                )
                logger.info("[OPENROUTER] Reasoning recebido: %d chars", r_len)
            else:
                logger.info("[OPENROUTER] Reasoning NÃO presente na resposta")

            return result

    @staticmethod
    async def _usar_openrouter_stream(
        db: Session,
        messages: List[Dict[str, Any]],
        modelo: str,
        temperatura: float,
        max_tokens: int,
        top_p: float,
        frequency_penalty: float,
        presence_penalty: float,
        tools: Optional[List[Dict]],
        on_text_delta: Callable[[str], Awaitable[None]],
        reasoning: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """OpenRouter com SSE; envia cada delta de texto via on_text_delta.

        Proteções contra travamento:
        - Timeout de inatividade: se nenhuma linha chega em _STREAM_IDLE_TIMEOUT segundos, aborta
        - Callback protegido: on_text_delta tem timeout de 5s para não bloquear o stream
        - Cancellation-safe: asyncio.CancelledError propaga corretamente
        """
        import asyncio as _aio

        _STREAM_IDLE_TIMEOUT = 120.0 if reasoning else 90.0  # reasoning pode gerar pausa mais longa
        _CALLBACK_TIMEOUT = 5.0       # segundos máx para on_text_delta

        api_key = ConfiguracaoService.obter_valor(db, "openrouter_api_key")
        if not api_key:
            raise ValueError("API Key do OpenRouter não configurada")

        payload: Dict[str, Any] = {
            "model": modelo,
            "messages": messages,
            "temperature": temperatura,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            logger.info(
                "[OPENROUTER] Enviando %d tools (stream) para API", len(tools)
            )

        # Reasoning tokens (OpenRouter unified API)
        if reasoning:
            payload["reasoning"] = reasoning
            logger.info("[OPENROUTER] Reasoning habilitado (stream): %s", reasoning)

        conteudo_acumulado = ""
        reasoning_acumulado = ""  # Acumula reasoning_details do stream
        reasoning_details_list: List[Dict[str, Any]] = []
        tool_calls_merge: Dict[int, Dict[str, Any]] = {}
        finish_reason: Optional[str] = None
        modelo_resp = modelo
        tokens_in = 0
        tokens_out = 0
        n_chunks = 0

        fluxi_log.info("llm", "stream", "Iniciando stream SSE", extra={
            "modelo": modelo, "n_tools": len(tools) if tools else 0,
        })

        timeout = httpx.Timeout(300.0, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://fluxi.ai",
                    "X-Title": "Fluxi WhatsApp AI Agent",
                },
                json=payload,
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    fluxi_log.error("llm", "stream", f"Erro HTTP {response.status_code} no stream", extra={
                        "modelo": modelo, "status": response.status_code,
                        "body": body.decode()[:500],
                    })
                    raise ValueError(
                        f"Erro na API OpenRouter: {response.status_code} - {body.decode()[:800]}"
                    )

                fluxi_log.debug("llm", "stream", "Conexao SSE aberta, lendo chunks...", extra={"modelo": modelo})

                # Wrapper com timeout de inatividade: se nenhuma linha chega
                # em _STREAM_IDLE_TIMEOUT segundos, levantamos TimeoutError
                line_iter = response.aiter_lines().__aiter__()
                while True:
                    try:
                        line = await _aio.wait_for(
                            line_iter.__anext__(),
                            timeout=_STREAM_IDLE_TIMEOUT,
                        )
                    except StopAsyncIteration:
                        # Stream terminou normalmente (sem [DONE])
                        fluxi_log.warning("llm", "stream", "Stream terminou sem [DONE]", extra={
                            "modelo": modelo, "n_chunks": n_chunks,
                        })
                        break
                    except _aio.TimeoutError:
                        fluxi_log.error("llm", "stream", f"Stream inativo por {_STREAM_IDLE_TIMEOUT}s — abortando", extra={
                            "modelo": modelo, "n_chunks": n_chunks,
                            "texto_ate_agora": len(conteudo_acumulado),
                            "idle_timeout_s": _STREAM_IDLE_TIMEOUT,
                        })
                        raise ValueError(
                            f"Stream SSE inativo por {_STREAM_IDLE_TIMEOUT:.0f}s sem dados. "
                            f"Recebidos {n_chunks} chunks até o momento. Modelo: {modelo}"
                        )
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        raw = line[6:].strip()
                    else:
                        continue
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    n_chunks += 1

                    if chunk.get("model"):
                        modelo_resp = chunk["model"]

                    # Verificar se veio erro inline do OpenRouter
                    if chunk.get("error"):
                        err_msg = chunk["error"]
                        if isinstance(err_msg, dict):
                            err_msg = err_msg.get("message", str(err_msg))
                        fluxi_log.error("llm", "stream", f"Erro inline do OpenRouter: {err_msg}", extra={
                            "modelo": modelo, "chunk_error": str(err_msg)[:300],
                        })
                        raise ValueError(f"Erro do OpenRouter durante stream: {err_msg}")

                    u = chunk.get("usage")
                    if isinstance(u, dict):
                        tokens_in = u.get("prompt_tokens") or tokens_in
                        tokens_out = u.get("completion_tokens") or tokens_out

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    ch = choices[0]
                    if ch.get("finish_reason"):
                        finish_reason = ch["finish_reason"]
                    delta = ch.get("delta") or {}

                    dc = delta.get("content")
                    if dc:
                        conteudo_acumulado += dc
                        # Callback protegido — nunca bloqueia o stream
                        try:
                            await _aio.wait_for(on_text_delta(dc), timeout=_CALLBACK_TIMEOUT)
                        except _aio.TimeoutError:
                            fluxi_log.warning("llm", "stream", "on_text_delta timeout — callback ignorado", extra={
                                "modelo": modelo, "timeout_s": _CALLBACK_TIMEOUT,
                            })
                        except Exception as cb_err:
                            # Callback falhou mas o stream continua — dados não se perdem
                            fluxi_log.warning("llm", "stream", f"on_text_delta erro: {cb_err}", extra={
                                "modelo": modelo, "erro": str(cb_err)[:200],
                            })

                    # Acumula reasoning_details do stream (delta.reasoning_details[])
                    for rd in delta.get("reasoning_details") or []:
                        if isinstance(rd, dict):
                            rd_content = rd.get("content", "")
                            if rd_content:
                                reasoning_acumulado += rd_content
                            reasoning_details_list.append(rd)

                    # Reasoning como string simples (delta.reasoning)
                    dr = delta.get("reasoning")
                    if dr:
                        reasoning_acumulado += dr

                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_merge:
                            tool_calls_merge[idx] = {
                                "id": None,
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.get("id"):
                            tool_calls_merge[idx]["id"] = tc["id"]
                        if tc.get("type"):
                            tool_calls_merge[idx]["type"] = tc["type"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            tool_calls_merge[idx]["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tool_calls_merge[idx]["function"]["arguments"] = (
                                tool_calls_merge[idx]["function"]["arguments"] or ""
                            ) + fn["arguments"]

        fluxi_log.info("llm", "stream", "Stream SSE concluido", extra={
            "modelo": modelo_resp, "n_chunks": n_chunks,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "finish_reason": finish_reason,
            "texto_chars": len(conteudo_acumulado),
            "n_tool_calls": len(tool_calls_merge),
        })

        tool_calls_list: Optional[List[Dict[str, Any]]] = None
        if tool_calls_merge:
            tool_calls_list = [
                tool_calls_merge[i] for i in sorted(tool_calls_merge.keys())
            ]

        result = {
            "conteudo": conteudo_acumulado,
            "modelo": modelo_resp,
            "tokens_input": tokens_in,
            "tokens_output": tokens_out,
            "tool_calls": tool_calls_list,
            "finish_reason": finish_reason or "stop",
            "finalizado": True,
        }

        # Inclui reasoning no resultado se acumulado durante stream
        if reasoning_acumulado:
            result["reasoning"] = reasoning_acumulado
        if reasoning_details_list:
            result["reasoning_details"] = reasoning_details_list
        if reasoning_acumulado:
            logger.info("[OPENROUTER] Reasoning recebido (stream): %d chars", len(reasoning_acumulado))

        return result

    @staticmethod
    async def obter_modelos_disponiveis(db: Session) -> Dict[str, List[str]]:
        """Obtém lista de modelos disponíveis por provedor."""
        import httpx

        modelos = {
            "openrouter": [],
            "local": []
        }

        # Buscar modelos do OpenRouter dinamicamente via API
        api_key = ConfiguracaoService.obter_valor(db, "openrouter_api_key")
        if api_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://openrouter.ai/api/v1/models",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json"
                        }
                    )
                    if response.status_code == 200:
                        data = response.json()
                        for modelo_data in data.get("data", []):
                            modelo_id = modelo_data.get("id", "")
                            if modelo_id:
                                modelos["openrouter"].append(modelo_id)
            except Exception as e:
                logger.warning("Erro ao buscar modelos do OpenRouter: %s", e)

        # Modelos locais (buscar dos provedores ativos)
        provedores_locais = ProvedorLLMService.listar_ativos(db)
        for provedor in provedores_locais:
            modelos_provedor = ProvedorLLMService.obter_modelos(db, provedor.id)
            for modelo in modelos_provedor:
                modelos["local"].append(f"{provedor.nome}:{modelo.nome}")

        return modelos

    @staticmethod
    def configurar_provedor_padrao(db: Session, tipo: str, provedor_id: Optional[int] = None):
        """
        Configura o provedor padrão do sistema.
        
        Args:
            tipo: "auto", "local" ou "openrouter"
            provedor_id: ID do provedor local (obrigatório se tipo == "local")
        """
        if tipo not in ["auto", "local", "openrouter"]:
            raise ValueError(f"Tipo de provedor inválido: {tipo}. Use 'auto', 'local' ou 'openrouter'.")
        
        ConfiguracaoService.definir_valor(db, "llm_provedor_padrao", tipo)
        
        if tipo == "local" and provedor_id:
            ConfiguracaoService.definir_valor(db, "llm_provedor_local_id", str(provedor_id))
        elif tipo in ["openrouter", "auto"]:
            ConfiguracaoService.definir_valor(db, "llm_provedor_local_id", None)
