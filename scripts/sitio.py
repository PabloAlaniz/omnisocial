"""Genera las dos páginas del sitio de documentación que salen del README.

    uv run python scripts/sitio.py           # reescribe docs/index.md y docs/guia.md
    uv run python scripts/sitio.py --check   # falla si quedaron viejas

El README es la fuente: la portada del sitio es su presentación con la matriz de redes, y la guía, sus
secciones de uso. Así no hay dos textos que mantener. Los links se ajustan, porque el README vive en la
raíz y las páginas, en `docs/`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DOCS = ROOT / "docs"
REPOSITORY = "https://github.com/PabloAlaniz/omnisocial/blob/main"
NOTE = "<!-- Generada por scripts/sitio.py a partir del README. No editar a mano. -->"

GUIDE_STARTS = "## Instalación"
GUIDE_ENDS = "## Documentación"

_LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)]+)\)")


def _target(target: str) -> str:
    """A dónde apunta, visto desde `docs/`, un link escrito en el README."""
    if target.startswith("docs/"):
        return target.removeprefix("docs/")
    # Lo que está fuera de `docs/` no es parte del sitio: va al repositorio.
    return f"{REPOSITORY}/{target}"


def relink(text: str) -> str:
    return _LINK.sub(lambda found: f"]({_target(found.group(1))})", text)


def pages(readme: str) -> dict[str, str]:
    """El contenido de cada página generada, por su nombre de archivo."""
    try:
        intro, rest = readme.split(f"\n{GUIDE_STARTS}\n", 1)
        guide, _ = rest.split(f"\n{GUIDE_ENDS}\n", 1)
    except ValueError:
        raise SystemExit(f"El README no tiene las secciones `{GUIDE_STARTS}` y `{GUIDE_ENDS}`.") from None
    index = f"{NOTE}\n\n{relink(intro).strip()}\n"
    body = f"{GUIDE_STARTS}\n{guide}"
    return {
        "index.md": index,
        "guia.md": f"{NOTE}\n\n# Guía de uso\n\n{relink(body).strip()}\n",
    }


def main(argv: list[str]) -> int:
    wanted = pages(README.read_text(encoding="utf-8"))
    stale = [
        name
        for name, content in wanted.items()
        if not (DOCS / name).exists() or (DOCS / name).read_text(encoding="utf-8") != content
    ]
    if "--check" in argv:
        if stale:
            names = ", ".join(stale)
            sys.stderr.write(f"Quedaron viejas: {names}. Corré `uv run python scripts/sitio.py`.\n")
            return 1
        return 0
    for name in stale:
        (DOCS / name).write_text(wanted[name], encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
