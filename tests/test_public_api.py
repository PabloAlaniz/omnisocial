import importlib

import pytest

import omnisocial


@pytest.mark.parametrize("module", ["meta", "tiktok", "httpx", "crypto", "starlette", "postgres"])
def test_los_modulos_publicos_exportan_lo_que_declaran(module: str) -> None:
    loaded = importlib.import_module(f"omnisocial.{module}")
    for name in loaded.__all__:
        assert hasattr(loaded, name), name


def test_el_paquete_exporta_lo_que_declara() -> None:
    for name in omnisocial.__all__:
        assert hasattr(omnisocial, name), name
