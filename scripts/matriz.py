"""Genera la matriz de capacidades del README a partir de la descripción de cada red.

    uv run python scripts/matriz.py           # reescribe el bloque del README
    uv run python scripts/matriz.py --check   # falla si el README quedó viejo

Las redes se encuentran solas: cada paquete de `omnisocial.adapters.providers` con un `spec.SPEC`.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

from omnisocial.adapters import providers
from omnisocial.domain.provider import Capability
from omnisocial.domain.spec import NetworkSpec

README = Path(__file__).resolve().parent.parent / "README.md"
START = "<!-- matriz:inicio (generada por scripts/matriz.py, no editar a mano) -->"
END = "<!-- matriz:fin -->"

COLUMNS = {
    Capability.LOGIN: "Login",
    Capability.ASSETS: "Activos",
    Capability.CONTENT: "Publicaciones",
    Capability.COMMENTS: "Comentarios",
    Capability.MESSAGING: "Mensajes",
    Capability.INSIGHTS: "Métricas",
    Capability.WEBHOOKS: "Webhooks",
    Capability.PUBLIC_PROFILES: "Perfiles públicos",
}


def specs() -> list[NetworkSpec]:
    found = []
    for module in pkgutil.iter_modules(providers.__path__):
        if not module.ispkg:
            continue
        spec = importlib.import_module(f"{providers.__name__}.{module.name}.spec").SPEC
        if not isinstance(spec, NetworkSpec):
            raise TypeError(f"`{module.name}.spec.SPEC` no es un NetworkSpec.")
        found.append(spec)
    return sorted(found, key=lambda spec: spec.name.lower())


def _row(first: str, second: str, capabilities: frozenset[Capability]) -> str:
    marks = ["✓" if capability in capabilities else "" for capability in COLUMNS]
    return "| " + " | ".join([first, second, *marks]) + " |"


def render(networks: list[NetworkSpec]) -> str:
    missing = set(Capability) - set(COLUMNS)
    if missing:
        raise ValueError(f"Falta el título de columna de: {sorted(missing)}")
    header = ["Red", "Activo", *COLUMNS.values()]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for spec in networks:
        name = f"[**{spec.name}**]({spec.docs})" if spec.docs else f"**{spec.name}**"
        lines.append(_row(name, "", spec.capabilities))
        lines.extend(_row("", f"`{kind}`", spec.assets[kind]) for kind in sorted(spec.assets))
    return "\n".join(lines)


def updated(readme: str, table: str) -> str:
    try:
        before, rest = readme.split(START, 1)
        _, after = rest.split(END, 1)
    except ValueError:
        raise SystemExit(f"El README no tiene el bloque `{START}` … `{END}`.") from None
    return f"{before}{START}\n{table}\n{END}{after}"


def main(argv: list[str]) -> int:
    current = README.read_text(encoding="utf-8")
    wanted = updated(current, render(specs()))
    if "--check" in argv:
        if current != wanted:
            sys.stderr.write("La matriz del README quedó vieja: corré `uv run python scripts/matriz.py`.\n")
            return 1
        return 0
    README.write_text(wanted, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
