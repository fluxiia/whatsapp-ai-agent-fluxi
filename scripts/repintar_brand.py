"""
Sweep nos templates substituindo as cores azul/indigo antigas pela paleta
roxo+magenta da marca. Hex literais e rgba() equivalentes.

NÃO toca em:
  - Cores semânticas (success #10b981, error #ef4444, warning #f59e0b)
  - Surface dark (#1e293b, #334155 — não são cor de marca)
  - Cores de syntax highlight ou exemplos de documentação

Rodar:
    python scripts/repintar_brand.py [--dry-run]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJETO = Path(__file__).resolve().parent.parent
TEMPLATES = PROJETO / "templates"

# (regex case-insensitive, substituição) — ordem importa
SUBSTITUICOES: list[tuple[str, str]] = [
    # Hex literais — variações de indigo/blue brand antigas → roxo Fluxi
    (r"#6366f1\b", "#6841A8"),
    (r"#6366F1\b", "#6841A8"),
    (r"#4f46e5\b", "#4B2B7E"),
    (r"#4F46E5\b", "#4B2B7E"),
    (r"#3b82f6\b", "#6841A8"),
    (r"#3B82F6\b", "#6841A8"),
    (r"#2563eb\b", "#4B2B7E"),
    (r"#2563EB\b", "#4B2B7E"),
    (r"#3730a3\b", "#4B2B7E"),  # indigo-800 → roxo escuro brand
    (r"#3730A3\b", "#4B2B7E"),
    (r"#1e40af\b", "#4B2B7E"),  # blue-800
    (r"#1E40AF\b", "#4B2B7E"),
    # Soft/light backgrounds que vinham de indigo
    (r"#eef2ff\b", "#F3EBFB"),  # indigo-50 → lavanda brand
    (r"#EEF2FF\b", "#F3EBFB"),
    (r"#c7d2fe\b", "#D9C8EE"),  # indigo-200 → roxo claro
    (r"#C7D2FE\b", "#D9C8EE"),
    (r"#dbeafe\b", "#F3EBFB"),  # blue-100
    (r"#DBEAFE\b", "#F3EBFB"),
    # RGBA com os mesmos valores RGB — preservar alpha
    (r"rgba\(\s*99\s*,\s*102\s*,\s*241\s*,", "rgba(104, 65, 168,"),
    (r"rgba\(\s*79\s*,\s*70\s*,\s*229\s*,", "rgba(75, 43, 126,"),
    (r"rgba\(\s*59\s*,\s*130\s*,\s*246\s*,", "rgba(104, 65, 168,"),
    (r"rgba\(\s*37\s*,\s*99\s*,\s*235\s*,", "rgba(75, 43, 126,"),
]


def aplicar_no_arquivo(arquivo: Path, dry_run: bool = False) -> int:
    original = arquivo.read_text(encoding="utf-8")
    modificado = original
    contador = 0
    for padrao, sub in SUBSTITUICOES:
        novo, n = re.subn(padrao, sub, modificado)
        if n:
            contador += n
            modificado = novo
    if contador and not dry_run:
        arquivo.write_text(modificado, encoding="utf-8")
    return contador


def main() -> None:
    dry = "--dry-run" in sys.argv
    print(f"{'DRY-RUN: ' if dry else ''}Sweep em templates/...\n")

    arquivos = sorted(TEMPLATES.rglob("*.html"))
    total_arquivos = 0
    total_subs = 0
    for arq in arquivos:
        n = aplicar_no_arquivo(arq, dry_run=dry)
        if n:
            total_arquivos += 1
            total_subs += n
            print(f"  {n:3d}  {arq.relative_to(PROJETO)}")

    # Também o CSS principal
    css = PROJETO / "static" / "css" / "modern.css"
    if css.exists():
        n = aplicar_no_arquivo(css, dry_run=dry)
        if n:
            total_arquivos += 1
            total_subs += n
            print(f"  {n:3d}  {css.relative_to(PROJETO)}")

    print(f"\n{total_subs} substituições em {total_arquivos} arquivos.")
    if dry:
        print("(dry-run — nenhum arquivo foi modificado)")


if __name__ == "__main__":
    main()
