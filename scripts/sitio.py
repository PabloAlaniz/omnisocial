"""Genera la portada del sitio de documentación a partir del README.

    uv run python scripts/sitio.py           # reescribe docs/index.md
    uv run python scripts/sitio.py --check   # falla si quedó vieja

La portada es la presentación del README con la matriz de redes: todo lo que está antes de
`## Instalación`. Así la matriz se mantiene en un solo lugar. El resto del sitio se escribe en `docs/`.

Los links se ajustan, porque el README se lee en GitHub y en PyPI y la portada vive en `docs/`:

- Un link al sitio publicado (`https://pabloalaniz.github.io/omnisocial/meta/`) pasa a ser relativo
  (`meta.md`), para que el armado en modo estricto lo compruebe.
- Un link relativo a `docs/` pierde el prefijo; uno a otro archivo del repositorio va a GitHub.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DOCS = ROOT / "docs"
SITE = "https://pabloalaniz.github.io/omnisocial/"
REPOSITORY = "https://github.com/PabloAlaniz/omnisocial/blob/main"
NOTE = "<!-- Generada por scripts/sitio.py a partir del README. No editar a mano. -->"

INTRO_ENDS = "## Instalación"

_LINK = re.compile(r"\]\(([^)]+)\)")


def site_page(page: str) -> str:
    """La URL publicada de una página de `docs/` (`meta.md` → `.../meta/`)."""
    if page == "index.md":
        return SITE
    path, _, anchor = page.partition("#")
    url = SITE + path.removesuffix(".md") + "/"
    return f"{url}#{anchor}" if anchor else url


def _target(target: str) -> str:
    """A dónde apunta, visto desde `docs/`, un link escrito en el README."""
    if target.startswith(SITE):
        path, _, anchor = target.removeprefix(SITE).partition("#")
        page = path.rstrip("/") + ".md" if path else "index.md"
        return f"{page}#{anchor}" if anchor else page
    if re.match(r"https?://|#|mailto:", target):
        return target
    if target.startswith("docs/"):
        return target.removeprefix("docs/")
    # Lo que está fuera de `docs/` no es parte del sitio: va al repositorio.
    return f"{REPOSITORY}/{target}"


def relink(text: str) -> str:
    return _LINK.sub(lambda found: f"]({_target(found.group(1))})", text)


def pages(readme: str) -> dict[str, str]:
    """El contenido de cada página generada, por su nombre de archivo."""
    if f"\n{INTRO_ENDS}\n" not in readme:
        raise SystemExit(f"El README no tiene la sección `{INTRO_ENDS}`.")
    intro = readme.split(f"\n{INTRO_ENDS}\n", 1)[0]
    return {"index.md": f"{NOTE}\n\n{relink(intro).strip()}\n"}


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
            sys.stderr.write(f"Quedó vieja: {names}. Corré `uv run python scripts/sitio.py`.\n")
            return 1
        return 0
    for name in stale:
        (DOCS / name).write_text(wanted[name], encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
