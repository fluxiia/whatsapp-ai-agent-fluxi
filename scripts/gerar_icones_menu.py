"""
Gera os 10 ícones do menu lateral via openrouter-image-generation skill.

Cada ícone é gerado em 1024x1024 com fundo branco puro e a logo da Fluxi
passada como referência pra manter a paleta (roxo + magenta). Depois roda
rembg pra remover o fundo e converte pra WebP comprimido em scripts/
processar_icones.py.

Saída: static/icons/menu/raw/NN_nome.png
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJETO = Path(__file__).resolve().parent.parent
LOGO = PROJETO / "data" / "logo_fluxi.png"
OUT_DIR = PROJETO / "static" / "icons" / "menu" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Script CLI da skill (instalada pelo plugin de skills do Claude Code).
SKILL_SCRIPT = (
    Path.home()
    / "AppData/Roaming/Claude/local-agent-mode-sessions/skills-plugin"
    / "126bab21-52fa-4ae0-be24-58603906ba48"
    / "d5fdf5db-92ef-4ed3-bd46-ff42cac508c6"
    / "skills/openrouter-image-generation/scripts/generate_image.py"
)

# Brief unificado que vai em TODOS os prompts pra família visual coesa.
BRIEF_UNIFICADO = """
Create a single sidebar menu icon for a modern SaaS web application called
Fluxi.IA. Treat this as part of a coherent family of 10 sidebar icons —
they must look like siblings.

STYLE — soft 3D, slightly volumetric, chunky rounded shapes with smooth
edges. Subtle top-light highlight gives a clean dimensional look without
being skeuomorphic or shiny-toy. Think modern fintech / SaaS dashboard
icon family (Stripe, Linear, Notion-style polish), but with personality.

COLOR — vivid purple #6841A8 blending into pink-magenta #B83A99 on a
diagonal gradient. Use the exact brand palette from the attached Fluxi
logo. Allow a darker inner shadow tone (around #4B2B7E) for depth where
shapes overlap. No other hues.

COMPOSITION — ONE single iconic symbol, centered, with comfortable
breathing room (around 15 percent margin on every side). The symbol must
fill the visual weight cleanly and remain legible at small sizes (24px
to 64px when shrunk later).

BACKGROUND — pure flat white #FFFFFF, completely empty. No drop shadow,
no platform, no surface, no glow, no extra decoration, no text, no
letters, no numbers, no badge, no person.

WHAT TO ILLUSTRATE — """.strip()

# Cada item: (slug, prompt específico que completa o brief)
ICONES: list[tuple[str, str]] = [
    (
        "01_overview",
        "A circular dashboard gauge meter, viewed from the front with subtle "
        "3D depth. A clean modern speedometer with minimal tick marks and a "
        "single needle pointing slightly past the midpoint to the upper-right, "
        "suggesting healthy steady performance. The bezel is rendered in the "
        "purple-magenta gradient. Calm, professional, dashboard-like.",
    ),
    (
        "02_conexoes_agentes",
        "A friendly minimalist 3D robot head, front view, centered. Slightly "
        "rounded square head with two large simple round eyes (no pupils), a "
        "small flat smile line, and a tiny antenna with a soft glowing tip. "
        "The robot conveys a conversational AI assistant. The body of the "
        "head is solid in the purple-magenta gradient.",
    ),
    (
        "03_conhecimento",
        "Three thick hardcover books stacked horizontally side-by-side like "
        "on a shelf, viewed slightly from the front-top angle for 3D depth. "
        "The middle book is open with a tiny bookmark ribbon visible. "
        "Rounded chunky spines in the purple-magenta gradient. Evokes a "
        "knowledge base / library.",
    ),
    (
        "04_ferramentas",
        "A wrench and a screwdriver crossed in an X, viewed flat from the "
        "front with subtle 3D extrusion thickness. Both tools are chunky "
        "and rounded, rendered fully in the purple-magenta gradient (not "
        "metallic). The crossing point is at the geometric center of the icon.",
    ),
    (
        "05_mcp",
        "A two-prong electrical plug and a socket facing each other, about "
        "to connect, with the plug on the left and socket on the right, "
        "rendered in the purple-magenta gradient with soft 3D depth. There "
        "is a small spark or connection indicator between them. Symbolizes "
        "integration and plug-and-play protocol.",
    ),
    (
        "06_skills",
        "A stylized 3D brain with smooth rounded contours and gentle gyri, "
        "not anatomically realistic. The brain is rendered in the purple-"
        "magenta brand gradient with a subtle inner glow at the top hinting "
        "at cognitive activity. Front-three-quarter view, centered, with a "
        "soft pleasing silhouette.",
    ),
    (
        "07_agendamentos",
        "A round 3D analog clock face viewed from the front, showing the "
        "hands at 10:10 (the classic 'happy clock' position). Minimal hour "
        "marks only at 12, 3, 6, and 9. The bezel is a thick rounded ring "
        "in the purple-magenta gradient. Friendly, modern, time-management "
        "feel.",
    ),
    (
        "08_coding_agent",
        "The classic code symbol </> — a left angle bracket, a forward slash, "
        "and a right angle bracket arranged horizontally as one cohesive "
        "iconic mark. Each character is extruded with chunky 3D depth and "
        "rendered in the purple-magenta gradient. Centered, balanced, "
        "developer-friendly.",
    ),
    (
        "09_sandbox",
        "A small command-line terminal window viewed from the front with "
        "subtle 3D depth. The window has rounded corners, a top header bar "
        "with three small dots on the left (classic macOS-style traffic "
        "lights), and inside the window body there is a chevron prompt > "
        "and a blinking-style cursor block. The window frame is in the "
        "purple-magenta gradient; the inner area is soft cream/white.",
    ),
    (
        "10_logs",
        "A small unrolled scroll/parchment with three horizontal lines on "
        "its surface representing log entries (short, medium, short). The "
        "two ends of the scroll are slightly rolled, giving a clean 3D "
        "cylindrical feel. Whole scroll rendered in the purple-magenta "
        "gradient, with subtle inner shading on the rolls. Centered, "
        "balanced.",
    ),
]


def gerar_um(slug: str, prompt_especifico: str) -> Path | None:
    out_path = OUT_DIR / f"{slug}.png"
    if out_path.exists():
        print(f"  - {slug}: já existe, pulando (delete pra regenerar)")
        return out_path
    prompt = f"{BRIEF_UNIFICADO} {prompt_especifico}"
    print(f"  → {slug}: gerando...")
    cmd = [
        sys.executable,
        str(SKILL_SCRIPT),
        "--prompt", prompt,
        "--logo", str(LOGO),
        "--preset", "square",
        "--output", str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"     ✗ erro: {res.stderr.strip()[:400]}")
        return None
    print(f"     ✓ salvo em {out_path.name}")
    return out_path


def main() -> None:
    if not SKILL_SCRIPT.exists():
        print(f"Script da skill não encontrado em {SKILL_SCRIPT}")
        sys.exit(1)
    if not LOGO.exists():
        print(f"Logo não encontrada em {LOGO}")
        sys.exit(1)

    print(f"Gerando {len(ICONES)} ícones em {OUT_DIR}")
    sucesso = 0
    for slug, prompt in ICONES:
        if gerar_um(slug, prompt) is not None:
            sucesso += 1
    print(f"\n{sucesso}/{len(ICONES)} ícones gerados.")


if __name__ == "__main__":
    main()
