"""
Gera os 5 ícones do topbar (canto superior direito) no mesmo estilo dos
ícones do menu lateral — soft 3D + paleta Fluxi.

Saída: static/icons/topbar/raw/NN_slug.png
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJETO = Path(__file__).resolve().parent.parent
LOGO = PROJETO / "data" / "logo_fluxi.png"
OUT_DIR = PROJETO / "static" / "icons" / "topbar" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SKILL_SCRIPT = (
    Path.home()
    / "AppData/Roaming/Claude/local-agent-mode-sessions/skills-plugin"
    / "126bab21-52fa-4ae0-be24-58603906ba48"
    / "d5fdf5db-92ef-4ed3-bd46-ff42cac508c6"
    / "skills/openrouter-image-generation/scripts/generate_image.py"
)

# Mesmo brief unificado dos ícones do menu lateral — pra família visual coesa.
# Mesma família, mas com ênfase em silhuetas claras pra leitura em ~18px.
BRIEF_UNIFICADO = """
Create a single icon for the top toolbar of a modern SaaS web application
called Fluxi.IA. This is part of the SAME visual family as the 10 sidebar
icons already generated — they must look like siblings (same style,
treatment, palette, mood).

STYLE — soft 3D, slightly volumetric, chunky rounded shapes with smooth
edges. Subtle top-light highlight gives a clean dimensional feel without
being skeuomorphic. Modern dashboard icon family vibe (Stripe, Linear,
Notion-style polish). The silhouette must be very readable because this
icon will appear small (around 18-22px) in the top toolbar.

COLOR — vivid purple #6841A8 blending into pink-magenta #B83A99 on a
diagonal gradient — the exact brand palette from the attached Fluxi logo.
Allow a darker inner shadow tone (around #4B2B7E) for depth where shapes
overlap. No other hues.

COMPOSITION — ONE single iconic symbol, centered, with comfortable
breathing room (about 15 percent margin on every side). Bold confident
silhouette that reads instantly at small sizes.

BACKGROUND — pure flat white #FFFFFF, completely empty. No drop shadow,
no platform, no surface, no glow, no extra decoration, no text, no
letters, no numbers, no badge.

WHAT TO ILLUSTRATE — """.strip()


ICONES: list[tuple[str, str]] = [
    (
        "01_onboarding",
        "A magic wand pointing diagonally upward to the upper right, with a "
        "small four-pointed sparkle/star at its tip emitting two or three "
        "tiny shimmer dots. The wand has a chunky 3D handle and a tapered "
        "tip. Conveys 'guided setup / wizard / let me help you start'.",
    ),
    (
        "02_provedores_llm",
        "A small stack of three horizontal server rack units (server "
        "blades) stacked on top of each other, each with two tiny status "
        "dots on the right side. Slight 3D perspective showing depth. The "
        "whole stack is in the purple-magenta gradient. Conveys 'compute "
        "infrastructure / model providers pool'.",
    ),
    (
        "03_metricas",
        "A bar chart with three vertical bars of growing height (short, "
        "medium, tall) sitting on a baseline, with rounded top corners. "
        "The whole chart is rendered with subtle 3D extrusion depth in "
        "the purple-magenta gradient. Conveys 'metrics / analytics / "
        "growth'.",
    ),
    (
        "04_configuracoes",
        "A single 3D gear/cog with 8 chunky rounded teeth and a small "
        "circular hub in the center. Subtle dimensional depth on the "
        "teeth, like an exploded mechanical part. Rendered fully in the "
        "purple-magenta gradient. Centered.",
    ),
    (
        "05_atualizacoes",
        "A soft puffy cloud with a downward-pointing arrow inside or just "
        "below it, indicating download/update. Cloud has rounded bumps "
        "and 3D dimensional volume. The arrow is bold and clearly readable. "
        "Both in the purple-magenta gradient.",
    ),
]


def gerar_um(slug: str, prompt_especifico: str) -> Path | None:
    out_path = OUT_DIR / f"{slug}.png"
    if out_path.exists():
        print(f"  - {slug}: já existe, pulando")
        return out_path
    prompt = f"{BRIEF_UNIFICADO} {prompt_especifico}"
    print(f"  → {slug}: gerando...")
    cmd = [
        sys.executable, str(SKILL_SCRIPT),
        "--prompt", prompt,
        "--logo", str(LOGO),
        "--preset", "square",
        "--output", str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"     ✗ erro: {res.stderr.strip()[:400]}")
        return None
    print(f"     ✓ {out_path.name}")
    return out_path


def main() -> None:
    print(f"Gerando {len(ICONES)} ícones do topbar em {OUT_DIR}")
    sucesso = 0
    for slug, prompt in ICONES:
        if gerar_um(slug, prompt) is not None:
            sucesso += 1
    print(f"\n{sucesso}/{len(ICONES)} gerados.")


if __name__ == "__main__":
    main()
