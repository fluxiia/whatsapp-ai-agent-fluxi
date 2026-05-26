"""Camada de mídias: tracking de arquivos no FS com `media_id` estável + TTL.

O agente/LLM nunca vê bytes — só `media_id` (string). Storage real fica em
`{upload_base}/midias/{sessao_id}/{ts}_{rand}.{ext}` por N dias (config).

Inspirado em Brisa_Zap (app/midias + app/core/storage) — adaptado pra
arquitetura multi-canal do Fluxi (sessao_id em vez de usuario_id).
"""
