"""
Serviço de geração de mídia (imagem/vídeo) via OpenRouter.

OpenRouter suporta geração de imagem usando chat completions com:
  modalities: ["image", "text"]
  image_config: { aspect_ratio, image_size }

Geração de vídeo ainda é experimental e depende de modelos específicos.

STATUS: Aguardando definição do modelo pelo usuário para ativar.
"""
import logging
from typing import Optional, Dict, Any
import httpx
import json
import base64

logger = logging.getLogger(__name__)


class MediaGenerationService:
    """Serviço para gerar imagem/vídeo via OpenRouter."""

    OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

    @staticmethod
    async def gerar_imagem(
        api_key: str,
        prompt: str,
        modelo: str,
        aspect_ratio: str = "1:1",
        image_size: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gera uma imagem via OpenRouter usando chat completions.

        O endpoint usa modalities: ["image", "text"] com image_config.
        O modelo deve suportar geração de imagem (ex: image-generation models).

        Args:
            api_key: Chave de API do OpenRouter
            prompt: Descrição da imagem desejada
            modelo: ID do modelo (ex: "openai/dall-e-3")
            aspect_ratio: Proporção da imagem ("1:1", "16:9", "9:16", etc.)
            image_size: Tamanho opcional da imagem

        Returns:
            Dict com sucesso, image_base64 (ou erro)
        """
        payload = {
            "model": modelo,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "modalities": ["image", "text"],
            "image_config": {
                "aspect_ratio": aspect_ratio,
            }
        }

        if image_size:
            payload["image_config"]["image_size"] = image_size

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    MediaGenerationService.OPENROUTER_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://fluxi.ai",
                        "X-Title": "Fluxi WhatsApp AI Agent"
                    },
                    json=payload
                )

                if response.status_code != 200:
                    return {
                        "sucesso": False,
                        "erro": f"Erro na API OpenRouter ({response.status_code}): {response.text}"
                    }

                data = response.json()
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})

                # A resposta pode conter imagens no formato base64
                # Formato OpenRouter: message.images = [{"url": "data:image/png;base64,..."}]
                # Ou message.content com texto descritivo
                images = message.get("images", [])
                content = message.get("content", "")

                result = {
                    "sucesso": True,
                    "modelo": data.get("model", modelo),
                    "texto": content,
                }

                if images:
                    # Extrair imagens base64
                    result["imagens"] = []
                    for img in images:
                        url = img.get("url", "")
                        if url.startswith("data:"):
                            # data:image/png;base64,XXXXX
                            result["imagens"].append({
                                "base64": url.split(",", 1)[1] if "," in url else "",
                                "mime_type": url.split(";")[0].split(":")[1] if ":" in url else "image/png"
                            })
                        else:
                            result["imagens"].append({"url": url})

                return result

        except httpx.TimeoutException:
            return {"sucesso": False, "erro": "Timeout ao gerar imagem (120s)"}
        except Exception as e:
            logger.exception("Erro ao gerar imagem: %s", e)
            return {"sucesso": False, "erro": str(e)}

    @staticmethod
    async def gerar_video(
        api_key: str,
        prompt: str,
        modelo: str,
    ) -> Dict[str, Any]:
        """
        Gera um vídeo via OpenRouter.

        STATUS: Pendente definição do modelo e parâmetros específicos.
        A API de vídeo do OpenRouter pode variar conforme o modelo.

        Args:
            api_key: Chave de API do OpenRouter
            prompt: Descrição do vídeo desejado
            modelo: ID do modelo de vídeo

        Returns:
            Dict com sucesso, video_url (ou erro)
        """
        # TODO: Implementar quando modelo for definido
        return {
            "sucesso": False,
            "erro": "Geração de vídeo pendente — aguardando definição do modelo"
        }
