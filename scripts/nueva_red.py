"""Crea el esqueleto de una red nueva: adaptador, prueba de contrato y página de documentación.

    uv run python scripts/nueva_red.py youtube --nombre YouTube

El esqueleto es una red de solo login que ya pasa el contrato común. Lo que hay que completar está marcado
con PENDIENTE. Cómo se sigue: docs/nueva-red.md.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "plantillas"
_ID = re.compile(r"[a-z][a-z0-9_]*")

# Plantilla → destino, relativo a la raíz del repositorio.
FILES = {
    "adaptador__init__.py.tmpl": "src/omnisocial/adapters/providers/$id/__init__.py",
    "config.py.tmpl": "src/omnisocial/adapters/providers/$id/config.py",
    "spec.py.tmpl": "src/omnisocial/adapters/providers/$id/spec.py",
    "client.py.tmpl": "src/omnisocial/adapters/providers/$id/client.py",
    "oauth.py.tmpl": "src/omnisocial/adapters/providers/$id/oauth.py",
    "provider.py.tmpl": "src/omnisocial/adapters/providers/$id/provider.py",
    "publico.py.tmpl": "src/omnisocial/$id.py",
    "test_contract.py.tmpl": "tests/adapters/$id/test_contract.py",
    "docs.md.tmpl": "docs/$id.md",
}
EMPTY = ("tests/adapters/$id/__init__.py",)

NEXT_STEPS = """
Lo que sigue:
  1. Completar lo marcado con PENDIENTE (buscar: grep -rn PENDIENTE src tests docs).
  2. uv run ruff check --fix . && uv run ruff format . && uv run mypy && uv run lint-imports
  3. uv run pytest tests/adapters/$id
  4. Sumar docs/$id.md a la sección Redes de mkdocs.yml y la red a la lista de
     .github/ISSUE_TEMPLATE/error-en-una-red.yml.
  5. uv run python scripts/matriz.py && uv run python scripts/sitio.py   # la matriz y la portada
  6. uv run pytest   # la suite completa recién pasa después de los pasos 4 y 5
"""


def scaffold(network_id: str, name: str, root: Path = ROOT) -> list[Path]:
    if not _ID.fullmatch(network_id):
        raise SystemExit(f"'{network_id}' no sirve de id: minúsculas, números y _ (se guarda en la base).")
    values = {
        "id": network_id,
        "nombre": name,
        "clase": re.sub(r"\W", "", name),
        "const": network_id.upper(),
    }
    if not values["clase"].isidentifier():
        raise SystemExit(f"'{name}' no sirve de nombre: de ahí salen los nombres de las clases.")
    targets = {root / Template(target).substitute(values): source for source, target in FILES.items()}
    existing = sorted(str(path.relative_to(root)) for path in targets if path.exists())
    if existing:
        raise SystemExit("Ya existe: " + ", ".join(existing))
    for path, source in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        template = Template((TEMPLATES / source).read_text(encoding="utf-8"))
        path.write_text(template.substitute(values), encoding="utf-8")
    empty = [root / Template(target).substitute(values) for target in EMPTY]
    for path in empty:
        path.touch()
    return [*targets, *empty]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Crea el esqueleto de una red nueva.")
    parser.add_argument("id", help="Identificador estable de la red: youtube, linkedin…")
    parser.add_argument("--nombre", required=True, help="Como se la nombra en la documentación: YouTube.")
    args = parser.parse_args(argv)
    created = scaffold(args.id, args.nombre)
    lines = [f"  {path.relative_to(ROOT)}" for path in sorted(created)]
    sys.stdout.write("Creado:\n" + "\n".join(lines) + "\n")
    sys.stdout.write(Template(NEXT_STEPS).substitute(id=args.id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
