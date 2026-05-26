"""
Gera favicons a partir da logo oficial.

A logo (data/logo_fluxi.png) tem o símbolo das bolhas de chat na parte de
cima e o texto "fluxi.IA" embaixo. Pra favicon queremos só o símbolo —
texto fica ilegível em 16/32px.

Saída:
    static/favicon-16x16.png
    static/favicon-32x32.png
    static/apple-touch-icon.png  (180x180)
    static/favicon.ico            (multi-size)
    static/logo_icon.png          (256x256, símbolo isolado — pode ser útil)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

PROJETO = Path(__file__).resolve().parent.parent
ORIGEM = PROJETO / "data" / "logo_fluxi.png"
DESTINO = PROJETO / "static"


def recortar_simbolo(img: Image.Image) -> Image.Image:
    """Pega só a parte superior da logo (o ícone das bolhas + asa do "F").

    A logo é ~1321x925:
      - Símbolo (bolhas + F com asa) ocupa do topo até ~y=570
      - Texto "fluxi.IA" começa em ~y=580 e vai até o fundo
      - Horizontalmente o símbolo é centralizado, mas a asa do F estende
        bastante pra direita — não dá pra usar crop quadrado central.
    Pegamos a faixa horizontal completa do topo e deixamos o canvas final
    cuidar de centralizar.
    """
    w, h = img.size
    top = int(h * 0.02)
    bottom = int(h * 0.54)
    # Crop horizontal: deixa só uma margem mínima dos dois lados pra evitar
    # cortar a asa do F (direita).
    margem_h = int(w * 0.18)
    left = margem_h
    right = w - margem_h
    return img.crop((left, top, right, bottom))


def garantir_quadrado_transparente(img: Image.Image) -> Image.Image:
    """Coloca a imagem dentro de um canvas quadrado RGBA transparente."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    w, h = img.size
    lado = max(w, h)
    canvas = Image.new("RGBA", (lado, lado), (255, 255, 255, 0))
    canvas.paste(img, ((lado - w) // 2, (lado - h) // 2), img)
    return canvas


def main() -> None:
    if not ORIGEM.exists():
        raise SystemExit(f"Logo não encontrada em {ORIGEM}")
    DESTINO.mkdir(parents=True, exist_ok=True)

    logo = Image.open(ORIGEM).convert("RGBA")
    simbolo = recortar_simbolo(logo)
    simbolo_quadrado = garantir_quadrado_transparente(simbolo)

    # Símbolo isolado, alta resolução (uso geral — ex.: open graph, header mobile)
    simbolo_quadrado.resize((512, 512), Image.LANCZOS).save(
        DESTINO / "logo_icon.png", "PNG", optimize=True
    )

    # Favicons PNG
    for tamanho, nome in [
        (16, "favicon-16x16.png"),
        (32, "favicon-32x32.png"),
        (180, "apple-touch-icon.png"),
        (192, "android-chrome-192x192.png"),
        (512, "android-chrome-512x512.png"),
    ]:
        resized = simbolo_quadrado.resize((tamanho, tamanho), Image.LANCZOS)
        resized.save(DESTINO / nome, "PNG", optimize=True)
        print(f"  ✓ {nome} ({tamanho}x{tamanho})")

    # .ico clássico — multi-resolução pra browsers antigos
    ico_path = DESTINO / "favicon.ico"
    simbolo_quadrado.save(
        ico_path, "ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64)],
    )
    print(f"  ✓ favicon.ico (multi-size)")

    print("\nPronto. Arquivos em", DESTINO)


if __name__ == "__main__":
    main()
