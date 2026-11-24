"""Las versiones de API contra las que está escrito cada adaptador, y cuáles conviene revisar.

    uv run python scripts/versiones.py           # la tabla
    uv run python scripts/versiones.py --check   # falla si alguna vence pronto o hace mucho que no se mira

Una red retira una versión con meses de aviso. Lo que este script vigila es que alguien mire ese aviso:
marca las versiones con fecha de retiro cercana y las que nadie comparó con la documentación en mucho
tiempo. Lo corre una tarea programada, que abre un issue con lo que encuentra.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from matriz import specs

from omnisocial.domain.spec import NetworkSpec

SUNSET_WARNING = timedelta(days=120)
"""Con cuánta anticipación avisar de un retiro."""
REVIEW_EVERY = timedelta(days=180)
"""Cada cuánto conviene volver a comparar el adaptador con la documentación."""


@dataclass(frozen=True, slots=True)
class Finding:
    network: str
    problem: str


def findings(networks: list[NetworkSpec], today: date) -> list[Finding]:
    found: list[Finding] = []
    for spec in networks:
        pin = spec.api
        if pin is None:
            continue
        where = f" Ver {pin.changelog}." if pin.changelog else ""
        if pin.sunset is not None and pin.sunset <= today:
            found.append(Finding(spec.name, f"La versión {pin.version} se retiró el {pin.sunset}.{where}"))
        elif pin.sunset is not None and pin.sunset - today <= SUNSET_WARNING:
            days = (pin.sunset - today).days
            found.append(
                Finding(
                    spec.name, f"La versión {pin.version} se retira el {pin.sunset} ({days} días).{where}"
                )
            )
        elif today - pin.reviewed > REVIEW_EVERY:
            stale = f"Nadie compara el adaptador con la versión {pin.version} desde el {pin.reviewed}."
            found.append(Finding(spec.name, f"{stale}{where}"))
    return found


def table(networks: list[NetworkSpec]) -> str:
    lines = ["| Red | Versión | Revisada | Se retira |", "|---|---|---|---|"]
    for spec in networks:
        pin = spec.api
        if pin is None:
            lines.append(f"| {spec.name} | la elige quien configura | | |")
        else:
            lines.append(f"| {spec.name} | {pin.version} | {pin.reviewed} | {pin.sunset or 'sin fecha'} |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    networks = specs()
    if "--check" not in argv:
        sys.stdout.write(table(networks) + "\n")
        return 0
    today = datetime.now(UTC).date()  # noqa: TID251  # un script de mantenimiento sí mira el calendario
    found = findings(networks, today)
    for finding in found:
        sys.stdout.write(f"- **{finding.network}**: {finding.problem}\n")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
