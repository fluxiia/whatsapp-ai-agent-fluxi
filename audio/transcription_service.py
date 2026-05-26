"""
Serviço de transcrição de áudio.
Suporta Groq, OpenAI e OpenRouter como provedores de transcrição.
"""
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List
import asyncio
import httpx
import base64
import io
import logging
import tempfile
import os
from pathlib import Path
from config.config_service import ConfiguracaoService
from log.log_service import fluxi_log

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Serviço para transcrição de áudio usando Whisper (Groq/OpenAI) ou Chat Completions (OpenRouter)."""

    # Endpoints
    GROQ_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
    OPENAI_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
    OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

    # Modelos disponíveis por provedor
    MODELOS = {
        "groq": [
            {"id": "whisper-large-v3-turbo", "nome": "Whisper Large V3 Turbo", "custo_hora": 0.04},
            {"id": "whisper-large-v3", "nome": "Whisper Large V3", "custo_hora": 0.111},
        ],
        "openai": [
            {"id": "whisper-1", "nome": "Whisper 1", "custo_hora": 0.006},
            {"id": "gpt-4o-transcribe", "nome": "GPT-4o Transcribe", "custo_hora": None},
            {"id": "gpt-4o-mini-transcribe", "nome": "GPT-4o Mini Transcribe", "custo_hora": None},
        ],
        "openrouter": [
            {"id": "google/gemini-3.1-flash-lite-preview", "nome": "Gemini 2.0 Flash", "custo_hora": None},
            {"id": "google/gemini-2.5-flash-preview", "nome": "Gemini 2.5 Flash", "custo_hora": None},
            {"id": "openai/gpt-4o-mini", "nome": "GPT-4o Mini", "custo_hora": None},
            {"id": "openai/gpt-4o", "nome": "GPT-4o", "custo_hora": None},
        ]
    }
    
    @staticmethod
    def obter_configuracao(db: Session) -> Dict[str, Any]:
        """Obtém configuração de transcrição do banco."""
        return {
            "habilitado": ConfiguracaoService.obter_valor(db, "audio_transcricao_habilitado", True),
            "provedor": ConfiguracaoService.obter_valor(db, "audio_transcricao_provedor", "groq"),
            "modelo": ConfiguracaoService.obter_valor(db, "audio_transcricao_modelo", "whisper-large-v3-turbo"),
            "idioma": ConfiguracaoService.obter_valor(db, "audio_transcricao_idioma", "pt"),
            "temperatura": ConfiguracaoService.obter_valor(db, "audio_transcricao_temperatura", 0.0),
            "prompt": ConfiguracaoService.obter_valor(db, "audio_transcricao_prompt", ""),
            "response_format": ConfiguracaoService.obter_valor(db, "audio_transcricao_formato", "text"),
            "responder_audio": ConfiguracaoService.obter_valor(db, "audio_responder_habilitado", True),
        }
    
    @staticmethod
    def obter_api_key(db: Session, provedor: str) -> Optional[str]:
        """Obtém a API key do provedor."""
        if provedor == "groq":
            return ConfiguracaoService.obter_valor(db, "groq_api_key")
        elif provedor == "openai":
            return ConfiguracaoService.obter_valor(db, "openai_api_key")
        elif provedor == "openrouter":
            return ConfiguracaoService.obter_valor(db, "openrouter_api_key")
        return None

    @staticmethod
    async def _converter_para_mp3(audio_bytes: bytes) -> bytes:
        """Converte áudio para MP3 usando FFmpeg."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_in:
            temp_in.write(audio_bytes)
            temp_in_path = temp_in.name

        temp_out_path = temp_in_path.replace(".ogg", ".mp3")

        try:
            # asyncio.create_subprocess_exec não bloqueia o event loop —
            # ffmpeg em sync trava o neonize/PTB e outras tarefas async.
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", temp_in_path,
                "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
                temp_out_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg saiu com código {proc.returncode}: {stderr.decode(errors='ignore')[:500]}"
                )

            with open(temp_out_path, "rb") as f:
                mp3_bytes = f.read()

            return mp3_bytes
        except Exception as e:
            logger.error(f"Falha na conversão de áudio: {e}")
            return audio_bytes
        finally:
            # Limpar arquivos temporários
            if os.path.exists(temp_in_path):
                os.remove(temp_in_path)
            if os.path.exists(temp_out_path):
                os.remove(temp_out_path)
    
    @staticmethod
    async def transcrever(
        db: Session,
        audio_bytes: bytes,
        filename: str = "audio.ogg",
        mime_type: str = "audio/ogg"
    ) -> Dict[str, Any]:
        """
        Transcreve áudio para texto.
        """
        config = TranscriptionService.obter_configuracao(db)
        
        # Verificar se transcrição está habilitada
        if not config["habilitado"]:
            return {
                "sucesso": False,
                "texto": None,
                "erro": "Transcrição de áudio desabilitada"
            }
        
        provedor = config["provedor"]
        api_key = TranscriptionService.obter_api_key(db, provedor)

        if not api_key:
            return {
                "sucesso": False,
                "texto": None,
                "erro": f"API Key do {provedor} não configurada"
            }

        # Determinar endpoint
        if provedor == "groq":
            endpoint = TranscriptionService.GROQ_ENDPOINT
        elif provedor == "openai":
            endpoint = TranscriptionService.OPENAI_ENDPOINT
        elif provedor == "openrouter":
            endpoint = TranscriptionService.OPENROUTER_ENDPOINT
        else:
            return {
                "sucesso": False,
                "texto": None,
                "erro": f"Provedor '{provedor}' não suportado"
            }
        
        try:
            # ── OpenRouter: usa chat completions com input_audio ──
            if provedor == "openrouter":
                return await TranscriptionService._transcrever_openrouter(
                    db, api_key, config, audio_bytes, filename, mime_type
                )

            # ── Groq / OpenAI: usa endpoint de transcrição Whisper ──
            mime_base = mime_type.split(";")[0].strip()
            
            if ";" in filename:
                parts = filename.rsplit(".", 1)
                if len(parts) == 2:
                    ext_limpa = parts[1].split(";")[0].strip()
                    filename = f"{parts[0]}.{ext_limpa}"
            
            # Preparar form data
            files = {
                "file": (filename, audio_bytes, mime_base)
            }
            
            data = {
                "model": config["modelo"],
                "response_format": config["response_format"],
            }
            
            if config["idioma"]:
                data["language"] = config["idioma"]
            
            if config["temperatura"] is not None:
                data["temperature"] = float(config["temperatura"])
            
            if config["prompt"]:
                data["prompt"] = config["prompt"]
            
            if provedor == "groq" and config["response_format"] == "verbose_json":
                data["timestamp_granularities[]"] = "segment"
            
            # Fazer requisição
            timeout = ConfiguracaoService.obter_valor(db, "audio_transcricao_timeout", 60)
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {api_key}"
                    },
                    files=files,
                    data=data,
                    timeout=float(timeout)
                )
                
                if response.status_code != 200:
                    return {
                        "sucesso": False,
                        "texto": None,
                        "erro": f"Erro na API ({response.status_code}): {response.text}"
                    }
                
                # Processar resposta
                if config["response_format"] == "text":
                    texto = response.text
                    return {
                        "sucesso": True,
                        "texto": texto.strip(),
                        "idioma": config["idioma"],
                        "duracao": None,
                        "provedor": provedor,
                        "modelo": config["modelo"]
                    }
                else:
                    # JSON response
                    result = response.json()
                    return {
                        "sucesso": True,
                        "texto": result.get("text", "").strip(),
                        "idioma": result.get("language", config["idioma"]),
                        "duracao": result.get("duration"),
                        "segmentos": result.get("segments"),
                        "provedor": provedor,
                        "modelo": config["modelo"]
                    }
                    
        except httpx.TimeoutException:
            return {
                "sucesso": False,
                "texto": None,
                "erro": f"Timeout ao transcrever áudio ({timeout}s)"
            }
        except Exception as e:
            return {
                "sucesso": False,
                "texto": None,
                "erro": f"Erro ao transcrever: {str(e)}"
            }
    
    @staticmethod
    def listar_modelos(provedor: str = None) -> Dict[str, list]:
        """Lista modelos disponíveis por provedor (estáticos)."""
        if provedor:
            return {provedor: TranscriptionService.MODELOS.get(provedor, [])}
        return TranscriptionService.MODELOS

    @staticmethod
    async def listar_modelos_openrouter_audio() -> List[Dict[str, Any]]:
        """Busca modelos do OpenRouter que suportam áudio dinamicamente via API."""
        url = "https://openrouter.ai/api/v1/models?output_modalities=audio"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    modelos = []
                    for m in data.get("data", []):
                        modelos.append({
                            "id": m.get("id"),
                            "nome": m.get("name") or m.get("id"),
                            "custo_hora": None
                        })
                    return modelos
                else:
                    logger.error(f"Erro OpenRouter API ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Erro ao buscar modelos audio OpenRouter: {e}")
        
        # Fallback para os modelos estáticos se a API falhar
        return TranscriptionService.MODELOS.get("openrouter", [])
    
    @staticmethod
    async def testar_conexao(db: Session) -> Dict[str, Any]:
        """Testa conexão com o provedor de transcrição."""
        config = TranscriptionService.obter_configuracao(db)
        provedor = config["provedor"]
        api_key = TranscriptionService.obter_api_key(db, provedor)

        if not api_key:
            return {
                "sucesso": False,
                "mensagem": f"API Key do {provedor} não configurada"
            }

        return {
            "sucesso": True,
            "mensagem": f"API Key do {provedor} configurada",
            "provedor": provedor,
            "modelo": config["modelo"]
        }

    @staticmethod
    async def _transcrever_openrouter(
        db: Session,
        api_key: str,
        config: Dict[str, Any],
        audio_bytes: bytes,
        filename: str,
        mime_type: str
    ) -> Dict[str, Any]:
        """
        Transcreve áudio via OpenRouter usando chat completions com input_audio.
        """
        modelo = config["modelo"]
        idioma = config.get("idioma", "pt")

        # OpenRouter/OpenAI multimodal audio suporta apenas mp3 e wav.
        # WhatsApp envia ogg/opus. Precisamos converter.
        ext_original = Path(filename).suffix.lstrip(".").lower()
        
        if ext_original not in ["mp3", "wav"]:
            try:
                fluxi_log.info("mensagem", "audio", "Convertendo audio para mp3", extra={"formato_original": ext_original})
                audio_bytes = await TranscriptionService._converter_para_mp3(audio_bytes)
                audio_format = "mp3"
            except Exception as e:
                fluxi_log.error("mensagem", "audio", "Erro na conversao de audio", exc_info=True)
                audio_format = "mp3"
        else:
            audio_format = ext_original

        # Codificar áudio em base64
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        # Montar prompt de sistema para transcrição
        system_prompt = (
            "Transcreva o áudio a seguir em texto. "
            "Retorne APENAS a transcrição, sem comentários adicionais."
        )
        if idioma:
            system_prompt += f" O idioma principal é {idioma}."

        user_content = [
            {
                "type": "input_audio",
                "input_audio": {
                    "data": audio_b64,
                    "format": audio_format
                }
            }
        ]

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        payload = {
            "model": modelo,
            "messages": messages,
            "temperature": float(config.get("temperatura", 0.0)),
            "max_tokens": 4096,
        }

        timeout = ConfiguracaoService.obter_valor(db, "audio_transcricao_timeout", 60)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                TranscriptionService.OPENROUTER_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://fluxi.ai",
                    "X-Title": "Fluxi WhatsApp AI Agent"
                },
                json=payload,
                timeout=float(timeout)
            )

            if response.status_code != 200:
                return {
                    "sucesso": False,
                    "texto": None,
                    "erro": f"Erro na API OpenRouter ({response.status_code}): {response.text}"
                }

            data = response.json()
            choice = data.get("choices", [{}])[0]
            texto = choice.get("message", {}).get("content", "").strip()

            # Extrair uso de tokens se disponível
            usage = data.get("usage", {})

            return {
                "sucesso": True,
                "texto": texto,
                "idioma": idioma,
                "duracao": None,
                "provedor": "openrouter",
                "modelo": modelo,
                "tokens_input": usage.get("prompt_tokens"),
                "tokens_output": usage.get("completion_tokens"),
            }
