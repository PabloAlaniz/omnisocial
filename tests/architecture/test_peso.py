"""Quien instala omnisocial y no usa una red no la carga (ADR 0006)."""

from __future__ import annotations

import json
import pkgutil
import subprocess
import sys

import pytest

from omnisocial.adapters import providers

NETWORKS = sorted(module.name for module in pkgutil.iter_modules(providers.__path__) if module.ispkg)
OPTIONAL = ("httpx", "cryptography", "psycopg", "psycopg_pool", "starlette", "opentelemetry")


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


@pytest.mark.parametrize("network", NETWORKS)
def test_una_red_no_carga_a_las_otras(network: str) -> None:
    loaded = _loaded_after(f"import omnisocial.{network}")
    prefix = "omnisocial.adapters.providers."
    others = sorted(m for m in loaded if m.startswith(prefix) and m.split(".")[3] != network)
    assert others == []
