"""El sitio de documentación: completo, al día y con la misma estructura en cada red."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT / "scripts"))
import matriz  # noqa: E402  # los scripts viven fuera del paquete
import sitio  # noqa: E402

NETWORK_PAGES = sorted({spec.docs for spec in matriz.specs() if spec.docs})


def test_las_paginas_que_salen_del_readme_estan_al_dia() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "scripts" / "sitio.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_los_links_del_readme_se_ajustan_al_sitio() -> None:
    text = (
        "[Meta](docs/meta.md) [ADR](docs/adr/0001-arquitectura-en-capas.md) [Contribuir](CONTRIBUTING.md) "
        "[PyPI](https://pypi.org/project/omnisocial/) [arriba](#instalacion)"
    )
    assert sitio.relink(text) == (
        "[Meta](meta.md) [ADR](adr/0001-arquitectura-en-capas.md) "
        "[Contribuir](https://github.com/PabloAlaniz/omnisocial/blob/main/CONTRIBUTING.md) "
        "[PyPI](https://pypi.org/project/omnisocial/) [arriba](#instalacion)"
    )
    made = sitio.pages(
        "# omnisocial\n\nPresentación.\n\n## Instalación\n\npip\n\n## Documentación\n\n- lista\n"
    )
    assert made["index.md"].endswith("# omnisocial\n\nPresentación.\n")
    assert made["guia.md"].endswith("# Guía de uso\n\n## Instalación\n\npip\n")
    assert "lista" not in "".join(made.values())
    with pytest.raises(SystemExit, match="no tiene las secciones"):
        sitio.pages("# sin secciones\n")


def test_toda_pagina_esta_en_el_indice_del_sitio() -> None:
    nav = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    listed = set(re.findall(r":\s+([\w./-]+\.md)\s*$", nav, flags=re.MULTILINE))
    present = {str(path.relative_to(DOCS)) for path in DOCS.rglob("*.md")}
    assert present - listed == set(), "Hay páginas que no están en el índice de `mkdocs.yml`."
    assert listed - present == set(), "El índice nombra páginas que no existen."


@pytest.mark.parametrize("page", NETWORK_PAGES)
def test_cada_red_tiene_su_pagina_con_la_misma_estructura(page: str) -> None:
    text = (ROOT / page).read_text(encoding="utf-8")
    sections = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert text.startswith("# "), f"{page} no empieza con su título."
    assert sections[0] == "Qué cubre", f"{page}: la primera sección es qué cubre la red."
    assert sections[-1] == "Lo que conviene saber", f"{page}: la última sección es lo que conviene saber."
    assert re.search(r"^###? Armado$", text, flags=re.MULTILINE), f"{page}: falta cómo se arma."
    # Qué tan probada está no se repite en cada página: se enlaza, para que no quede vieja.
    assert "niveles-de-soporte.md" in text, f"{page} no enlaza a los niveles de soporte."
