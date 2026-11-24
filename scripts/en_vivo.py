"""El resumen de una corrida en vivo, a partir de lo que dejó anotado.

    uv run python scripts/en_vivo.py en-vivo.jsonl

Escribe una tabla en Markdown: qué se comprobó en cada red y cómo salió. El archivo trae solo nombres de
comprobaciones y motivos de negativa: nunca un token ni el contenido de una cuenta.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def summary(lines: list[str]) -> str:
    rows = ["| Red | Comprobación | Resultado |", "|---|---|---|"]
    for line in lines:
        run = json.loads(line)
        for check in run["checks"]:
            result = "bien" if check["ok"] else f"falló: {check['reason']}"
            rows.append(f"| {run['network']} | {check['check']} | {result} |")
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else None
    if path is None or not path.exists():
        sys.stdout.write("La corrida no dejó nada anotado.\n")
        return 0
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    sys.stdout.write(summary(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
