"""
Pipeline pós-geração dos ícones do menu.

Para cada PNG em static/icons/menu/raw/:
  1. Roda rembg (remove o fundo branco) → PNG com transparência
  2. Crop nos bounds não-transparentes pra eliminar margem branca
  3. Coloca dentro de canvas quadrado transparente
  4. Resize pra 256x256 (LANCZOS) — espaço de cores final
  5. Salva como WebP comprimido (qualidade 90, modo lossy)

Saída: static/icons/menu/NN_slug.webp
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from rembg import remove

PROJETO = Path(__file__).resolve().parent.parent
# Default: menu/raw -> menu/. Sobrescrevível via argv: python script <subdir>
# Ex.: `python processar_icones.py topbar` processa static/icons/topbar/raw/
import sys as _sys
_subdir = _sys.argv[1] if len(_sys.argv) > 1 else "menu"
RAW_DIR = PROJETO / "static" / "icons" / _subdir / "raw"
OUT_DIR = PROJETO / "static" / "icons" / _subdir
OUT_DIR.mkdir(parents=True, exist_ok=True)

TAMANHO_FINAL = 256  # px — bom pra @2x até 128px de display
MARGEM = 0.04  # margem interna após crop (% do lado)


def remover_fundo(png_bytes: bytes) -> Image.Image:
    """rembg → Image RGBA."""
    out_bytes = remove(png_bytes)
    return Image.open(io.BytesIO(out_bytes)).convert("RGBA")


def crop_para_bbox(img: Image.Image) -> Image.Image:
    """Recorta nos limites do alpha não-zero."""
    bbox = img.split()[-1].getbbox()  # alpha channel
    if bbox is None:
        return img
    return img.crop(bbox)


def canvas_quadrado(img: Image.Image, margem_pct: float) -> Image.Image:
    """Coloca img dentro de um quadrado transparente com margem."""
    w, h = img.size
    lado_conteudo = max(w, h)
    lado_total = int(lado_conteudo * (1 + 2 * margem_pct))
    canvas = Image.new("RGBA", (lado_total, lado_total), (255, 255, 255, 0))
    canvas.paste(
        img,
        ((lado_total - w) // 2, (lado_total - h) // 2),
        img,
    )
    return canvas


def processar(arquivo_raw: Path) -> Path:
    slug = arquivo_raw.stem  # ex.: '01_overview'
    print(f"  → {slug}")
    png_bytes = arquivo_raw.read_bytes()
    sem_fundo = remover_fundo(png_bytes)
    centralizado = canvas_quadrado(crop_para_bbox(sem_fundo), MARGEM)
    final = centralizado.resize((TAMANHO_FINAL, TAMANHO_FINAL), Image.LANCZOS)
    saida = OUT_DIR / f"{slug}.webp"
    final.save(saida, "WEBP", quality=90, method=6)
    print(f"     ✓ {saida.name} ({saida.stat().st_size // 1024} KB)")
    return saida


def main() -> None:
    if not RAW_DIR.exists():
        raise SystemExit(f"Sem raw em {RAW_DIR}")
    arquivos = sorted(RAW_DIR.glob("*.png"))
    if not arquivos:
        raise SystemExit(f"Nenhum PNG em {RAW_DIR}")
    print(f"Processando {len(arquivos)} ícones de {RAW_DIR}")
    for arq in arquivos:
        try:
            processar(arq)
        except Exception as e:
            print(f"     ✗ falha em {arq.name}: {type(e).__name__}: {e}")
    print(f"\nPronto. Saída em {OUT_DIR}")


if __name__ == "__main__":
    main()
