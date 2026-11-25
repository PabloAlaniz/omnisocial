import importlib
import pkgutil

import pytest

import omnisocial
from omnisocial.adapters import providers
from omnisocial.domain.spec import NetworkSpec

NETWORKS = sorted(module.name for module in pkgutil.iter_modules(providers.__path__) if module.ispkg)


@pytest.mark.parametrize(
    "module", [*NETWORKS, "httpx", "crypto", "starlette", "postgres", "network", "testing", "otel"]
)
def test_los_modulos_publicos_exportan_lo_que_declaran(module: str) -> None:
    loaded = importlib.import_module(f"omnisocial.{module}")
    for name in loaded.__all__:
        assert hasattr(loaded, name), name


@pytest.mark.parametrize("network", NETWORKS)
def test_cada_red_tiene_su_modulo_publico_con_la_descripcion_y_la_fabrica(network: str) -> None:
    public = importlib.import_module(f"omnisocial.{network}")
    assert isinstance(public.SPEC, NetworkSpec)
    assert public.SPEC.id == network
    assert callable(getattr(public, f"{network}_provider"))


def test_el_paquete_exporta_lo_que_declara() -> None:
    for name in omnisocial.__all__:
        assert hasattr(omnisocial, name), name
