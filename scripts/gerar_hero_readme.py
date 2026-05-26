"""
Gera o hero banner do README via openrouter-image-generation.

Saída: data/hero_dashboard.png (1920x1080, 16:9)

Substitui o antigo data/screenshot01.png que não existe mais.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJETO = Path(__file__).resolve().parent.parent
LOGO = PROJETO / "data" / "logo_fluxi.png"
OUT = PROJETO / "data" / "hero_dashboard.png"

SKILL_SCRIPT = (
    Path.home()
    / "AppData/Roaming/Claude/local-agent-mode-sessions/skills-plugin"
    / "126bab21-52fa-4ae0-be24-58603906ba48"
    / "d5fdf5db-92ef-4ed3-bd46-ff42cac508c6"
    / "skills/openrouter-image-generation/scripts/generate_image.py"
)

PROMPT = """
Create a premium hero banner image for the README of an open-source AI agent
platform called Fluxi.IA. This is the FIRST thing visitors see on the GitHub
page, so it must feel polished, modern, and inviting — the kind of hero you'd
see on the homepage of Linear, Vercel, Stripe, or a high-end SaaS landing page.

VISUAL CONCEPT
A centered, soft 3D scene showing a glowing AI "core" — a slightly rounded,
luminous sphere/orb in the brand purple — emitting smooth gradient rays
outward to three abstract communication endpoints arranged around it: (1) a
chat speech bubble suggesting WhatsApp-style messaging on the bottom-left,
(2) a paper plane silhouette suggesting Telegram on the upper-right, and (3)
a tiny browser window with a "</>" chat indicator suggesting the web chat on
the bottom-right. The three endpoints are connected to the core by gentle
flowing gradient lines that hint at continuous bidirectional conversation
flow. Small floating particles and subtle bokeh in the background give the
scene depth without clutter.

STYLE
Soft 3D, slightly volumetric, chunky rounded shapes with smooth glossy
surfaces and gentle top-light highlights. Modern editorial SaaS illustration
mood. Cohesive with a family of 3D icons that already exist in the project
(soft purple-magenta gradient family — DO NOT depart from this palette). No
sharp edges, no metallic feel, no neon glow.

COLOR
Use the EXACT brand palette from the attached Fluxi logo: vivid purple
#6841A8 transitioning to pink-magenta #B83A99, with darker accents around
#4B2B7E for shadow depth. Background is a very soft cream-to-lavender wash
(roughly #FAF7FF at top fading to #F3EBFB at bottom) — light and inviting,
NOT dark. The "WhatsApp" bubble can have a tiny green accent dot and the
"Telegram" plane a tiny blue accent dot just to hint at the brands without
using their real logos.

COMPOSITION
The AI core sits slightly LEFT OF CENTER. The right third of the canvas
stays visually calmer to allow text overlay later if needed. Generous
breathing room on all sides. The whole scene reads as one cohesive
composition, not a montage.

ABSOLUTELY NO
- No text, no headlines, no logos of WhatsApp/Telegram/browser brands, no
  wordmarks, no watermarks. We will add typography separately.
- No skeuomorphic clutter.
- No dark or moody background — keep it light and welcoming.
- No people, no faces, no robot characters in this banner (different from
  the icon family).

VIBE
The kind of hero that makes a developer pause and think "oh, this project
has taste". Premium, editorial, calm, confident.
""".strip()


def main() -> None:
    if not SKILL_SCRIPT.exists():
        sys.exit(f"Script da skill não encontrado: {SKILL_SCRIPT}")
    print(f"Gerando hero banner → {OUT}")
    cmd = [
        sys.executable, str(SKILL_SCRIPT),
        "--prompt", PROMPT,
        "--logo", str(LOGO),
        "--preset", "hero",      # 16:9 @ 2K
        "--output", str(OUT),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Erro:\n{res.stderr}")
        sys.exit(1)
    print(f"  ✓ salvo em {OUT}")


if __name__ == "__main__":
    main()
