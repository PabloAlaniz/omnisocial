"""Quien instala omnisocial y no usa una red no la carga (ADR 0006)."""

from __future__ import annotations

import json
import subprocess
import sys

OPTIONAL = ("httpx", "cryptography", "psycopg", "psycopg_pool", "starlette")


def _loaded_after(statement: str) -> set[str]:
    code = f"import sys, json\n{statement}\nprint(json.dumps(sorted(sys.modules)))"
    output = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    ).stdout
    return set(json.loads(output))


def test_el_paquete_raiz_no_carga_redes_ni_opcionales() -> None:
    loaded = _loaded_after("import omnisocial")
    providers = sorted(m for m in loaded if m.startswith("omnisocial.adapters.providers."))
    optional = sorted(m for m in loaded if m.split(".")[0] in OPTIONAL)
    assert providers == []
    assert optional == []


def test_una_red_no_carga_a_las_otras() -> None:
    meta = _loaded_after("import omnisocial.meta")
    tiktok = _loaded_after("import omnisocial.tiktok")
    assert not any(m.startswith("omnisocial.adapters.providers.tiktok") for m in meta)
    assert not any(m.startswith("omnisocial.adapters.providers.meta") for m in tiktok)
