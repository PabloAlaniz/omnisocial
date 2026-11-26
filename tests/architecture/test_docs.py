"""El sitio de documentación: completo, al día y con la misma estructura en cada red."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from omnisocial import Refusal

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT / "scripts"))
import matriz  # noqa: E402  # los scripts viven fuera del paquete
import sitio  # noqa: E402

NETWORK_PAGES = sorted({spec.docs for spec in matriz.specs() if spec.docs})


def test_la_portada_que_sale_del_readme_esta_al_dia() -> None:
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
        "[PyPI](https://pypi.org/project/omnisocial/) [arriba](#instalacion) "
        "[Bluesky](https://pabloalaniz.github.io/omnisocial/bluesky/) "
        "[Paso](https://pabloalaniz.github.io/omnisocial/primeros-pasos/#2-crear) "
        "[Inicio](https://pabloalaniz.github.io/omnisocial/)"
    )
    assert sitio.relink(text) == (
        "[Meta](meta.md) [ADR](adr/0001-arquitectura-en-capas.md) "
        "[Contribuir](https://github.com/PabloAlaniz/omnisocial/blob/main/CONTRIBUTING.md) "
        "[PyPI](https://pypi.org/project/omnisocial/) [arriba](#instalacion) "
        "[Bluesky](bluesky.md) [Paso](primeros-pasos.md#2-crear) [Inicio](index.md)"
    )
    assert sitio.site_page("meta.md") == "https://pabloalaniz.github.io/omnisocial/meta/"
    made = sitio.pages("# omnisocial\n\nPresentación.\n\n## Instalación\n\npip\n")
    assert made == {"index.md": f"{sitio.NOTE}\n\n# omnisocial\n\nPresentación.\n"}
    with pytest.raises(SystemExit, match="no tiene la sección"):
        sitio.pages("# sin secciones\n")


def test_los_links_del_readme_van_al_sitio_publicado() -> None:
    """El README también es la página de PyPI, donde un link relativo a `docs/` no lleva a ningún lado."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.findall(r"\]\((docs/[^)]+)\)", readme) == []


def test_toda_negativa_esta_explicada() -> None:
    text = (DOCS / "referencia" / "negativas.md").read_text(encoding="utf-8")
    missing = [reason.name for reason in Refusal if f"`{reason.name}`" not in text]
    assert missing == [], f"Faltan en docs/referencia/negativas.md: {missing}"


def _python_blocks() -> list[tuple[str, str]]:
    blocks = []
    for path in [ROOT / "README.md", *sorted(DOCS.rglob("*.md"))]:
        text = path.read_text(encoding="utf-8")
        for number, code in enumerate(re.findall(r"^```python\n(.*?)^```", text, re.DOTALL | re.MULTILINE)):
            blocks.append((f"{path.relative_to(ROOT)}#{number + 1}", textwrap.dedent(code)))
    return blocks


@pytest.mark.parametrize(("where", "code"), _python_blocks(), ids=[where for where, _ in _python_blocks()])
def test_los_ejemplos_de_codigo_son_python_valido(where: str, code: str) -> None:
    # Los ejemplos usan `await` suelto, como en un REPL asíncrono.
    compile(code, where, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT, dont_inherit=True)


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
