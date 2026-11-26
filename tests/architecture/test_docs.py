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


NETWORK_SECTIONS = (
    "Qué cubre",
    "Antes de empezar",
    "Crear la app",
    "Armado",
    "Conectar",
    "Permisos",
    "Tokens",
    "Publicar",
    None,  # acá van las secciones propias de cada red
    "Avisos",
    "Límites",
    "Errores",
    "Lo que conviene saber",
)
"""El orden de las secciones de una página de red (`scripts/plantillas/docs.md.tmpl`). Las que no aplican se
omiten; las propias de una red van entre "Publicar" y "Avisos"."""

NETWORK_SECTION_ALIASES = (
    "Webhooks",
    "Permisos y tokens",
    "Permisos y revisión",
    "Permisos y revisión de la app",
    "Antes de integrar",
    "La sesión",
    "Límites y cuotas",
    "Crear la app y sus productos",
)
"""Nombres que se usaron para una sección canónica: se escribe el canónico."""


def _rank(section: str) -> int:
    return NETWORK_SECTIONS.index(section if section in NETWORK_SECTIONS else None)


@pytest.mark.parametrize("page", NETWORK_PAGES)
def test_cada_red_tiene_su_pagina_con_la_misma_estructura(page: str) -> None:
    text = (ROOT / page).read_text(encoding="utf-8")
    sections = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert text.startswith("# "), f"{page} no empieza con su título."
    assert ":" not in text.splitlines()[0], f"{page}: el título es el nombre de la red, sin subtítulo."
    assert sections[0] == "Qué cubre", f"{page}: la primera sección es qué cubre la red."
    assert sections[-1] == "Lo que conviene saber", f"{page}: la última sección es lo que conviene saber."
    assert re.search(r"^###? Armado$", text, flags=re.MULTILINE), f"{page}: falta cómo se arma."
    aliases = [section for section in sections if section in NETWORK_SECTION_ALIASES]
    assert aliases == [], f"{page}: {aliases} tienen un nombre canónico en NETWORK_SECTIONS."
    ranks = [_rank(section) for section in sections]
    assert ranks == sorted(ranks), f"{page}: las secciones no siguen el orden de NETWORK_SECTIONS: {sections}"
    # Lo que falta probar va en un solo bloque, al final, con la misma forma en todas las redes.
    assert "Sin verificar:" not in text, (
        f'{page}: lo pendiente va en el bloque "A confirmar con la API real".'
    )
    # Qué tan probada está no se repite en cada página: se enlaza, para que no quede vieja.
    assert "niveles-de-soporte.md" in text, f"{page} no enlaza a los niveles de soporte."


ADRS = sorted((DOCS / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"))


@pytest.mark.parametrize("adr", ADRS, ids=[adr.name[:4] for adr in ADRS])
def test_cada_adr_tiene_su_encabezado_y_esta_en_el_indice(adr: Path) -> None:
    text = adr.read_text(encoding="utf-8")
    assert text.startswith(f"# {adr.name[:4]}. "), f"{adr.name} no empieza con su número y título."
    assert re.search(r"^- \*\*Estado:\*\* \S", text, flags=re.MULTILINE), f"{adr.name}: falta el estado."
    assert re.search(r"^- \*\*Fecha:\*\* \d{4}-\d{2}-\d{2}$", text, flags=re.MULTILINE), (
        f"{adr.name}: falta la fecha."
    )
    assert re.search(r"^- \*\*Relacionadas:\*\* ", text, flags=re.MULTILINE), (
        f"{adr.name}: faltan las relacionadas."
    )
    index = (DOCS / "adr" / "index.md").read_text(encoding="utf-8")
    assert f"]({adr.name})" in index, f"{adr.name} no está en docs/adr/index.md."
    assert "Nada se probó" not in text, f"{page}: qué tan probada está lo dicen los niveles de soporte."


def test_la_plantilla_de_una_red_sigue_la_misma_estructura() -> None:
    text = (ROOT / "scripts" / "plantillas" / "docs.md.tmpl").read_text(encoding="utf-8")
    sections = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert tuple(sections) == tuple(section for section in NETWORK_SECTIONS if section is not None)
