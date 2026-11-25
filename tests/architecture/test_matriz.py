"""La matriz de capacidades del README sale de la descripción de las redes y no se desactualiza."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_la_matriz_del_readme_esta_al_dia() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "scripts" / "matriz.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
