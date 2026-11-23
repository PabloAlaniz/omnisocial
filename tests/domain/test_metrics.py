import pytest

from omnisocial.domain.metrics import (
    CanonicalMetric,
    CatalogEntry,
    MetricCatalog,
    parse_version,
    select_metrics,
)

CATALOG = MetricCatalog(
    (
        CatalogEntry("cuenta", CanonicalMetric.IMPRESSIONS, "impresiones", until="v22.0"),
        CatalogEntry("cuenta", CanonicalMetric.VIEWS, "vistas", since="v22.0"),
        CatalogEntry("cuenta", CanonicalMetric.REACH, "alcance"),
        CatalogEntry("pagina", CanonicalMetric.REACH, "alcance_pagina"),
    )
)


def test_versiones() -> None:
    assert parse_version("v21.0") == (21, 0)
    assert parse_version("22") == (22, 0)
    with pytest.raises(ValueError, match="inválida"):
        parse_version("latest")


def test_el_catalogo_respeta_el_rango_de_versiones() -> None:
    assert CATALOG.native_for("cuenta", CanonicalMetric.IMPRESSIONS, "v21.0") == "impresiones"
    assert CATALOG.native_for("cuenta", CanonicalMetric.IMPRESSIONS, "v22.0") is None
    assert CATALOG.native_for("cuenta", CanonicalMetric.VIEWS, "v21.0") is None
    assert CATALOG.native_for("cuenta", CanonicalMetric.VIEWS, "v23.0") == "vistas"


def test_el_catalogo_distingue_el_tipo_de_activo() -> None:
    assert CATALOG.native_for("pagina", CanonicalMetric.REACH, "v1") == "alcance_pagina"
    assert CATALOG.canonical_for("pagina", "alcance_pagina", "v1") is CanonicalMetric.REACH
    assert CATALOG.canonical_for("cuenta", "alcance_pagina", "v1") is None


def test_seleccion_traduce_deja_pasar_y_no_repite() -> None:
    selection = select_metrics(
        [CanonicalMetric.REACH, "alcance", "propia", CanonicalMetric.IMPRESSIONS],
        catalog=CATALOG,
        asset_kind="cuenta",
        version="v24.0",
    )
    assert selection.native == ("alcance", "propia")
    assert selection.unresolved == (CanonicalMetric.IMPRESSIONS,)
