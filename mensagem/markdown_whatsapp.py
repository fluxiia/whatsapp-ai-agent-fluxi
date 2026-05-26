"""
Converte formatação Markdown padrão (usada por LLMs) para formatação WhatsApp.

Mapeamento:
  Markdown              →  WhatsApp
  **texto** / __texto__ →  *texto*      (negrito)
  *texto* / _texto_     →  _texto_      (itálico)
  ***texto***           →  *_texto_*    (negrito+itálico)
  ~~texto~~             →  ~texto~      (tachado)
  # Título              →  *Título*     (negrito)
  [texto](url)          →  texto (url)  (link)
  ![alt](url)           →  alt - url    (imagem)
  ---                   →  ─────────    (linha)
  ```código```          →  ```código``` (mantido)
  `código`              →  `código`     (mantido)
"""
import re


def markdown_para_whatsapp(texto: str) -> str:
    """Converte formatação Markdown para formatação WhatsApp."""
    if not texto:
        return texto

    # 1. Proteger blocos de código (``` ... ```)
    blocos_codigo = []

    def _salvar_bloco(m):
        blocos_codigo.append(m.group(0))
        return f"\x00CODEBLOCK{len(blocos_codigo) - 1}\x00"

    texto = re.sub(r"```[\s\S]*?```", _salvar_bloco, texto)

    # 2. Proteger código inline (` ... `)
    codigos_inline = []

    def _salvar_inline(m):
        codigos_inline.append(m.group(0))
        return f"\x00INLINE{len(codigos_inline) - 1}\x00"

    texto = re.sub(r"`[^`\n]+`", _salvar_inline, texto)

    # 3. Headers → negrito WhatsApp
    texto = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", texto, flags=re.MULTILINE)

    # 4. Negrito+Itálico: ***texto*** → *_texto_*
    texto = re.sub(r"\*\*\*(.+?)\*\*\*", r"*_\1_*", texto)

    # 5. Negrito: **texto** → *texto*
    texto = re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto)

    # 6. Negrito: __texto__ → *texto*
    texto = re.sub(r"__(.+?)__", r"*\1*", texto)

    # 7. Itálico: *texto* (não precedido/seguido de *) → _texto_
    #    Após a etapa 5, os ** já foram convertidos; restam apenas * simples (itálico MD)
    texto = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"_\1_", texto)

    # 8. Tachado: ~~texto~~ → ~texto~
    texto = re.sub(r"~~(.+?)~~", r"~\1~", texto)

    # 9. Imagens: ![alt](url) → alt - url
    texto = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1 - \2", texto)

    # 10. Links: [texto](url) → texto (url)
    texto = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", texto)

    # 11. Linhas horizontais: --- / *** / ___ → linha visual
    texto = re.sub(r"^[-*_]{3,}\s*$", "─────────────────", texto, flags=re.MULTILINE)

    # 12. Restaurar código inline
    for i, codigo in enumerate(codigos_inline):
        texto = texto.replace(f"\x00INLINE{i}\x00", codigo)

    # 13. Restaurar blocos de código
    for i, bloco in enumerate(blocos_codigo):
        texto = texto.replace(f"\x00CODEBLOCK{i}\x00", bloco)

    return texto
