from datetime import UTC, datetime, timedelta

import pytest

from omnisocial.domain.window import TimeWindow

D1 = datetime(2026, 1, 1, tzinfo=UTC)
D10 = datetime(2026, 1, 10, tzinfo=UTC)


def test_contiene_los_extremos_y_lo_sin_fecha() -> None:
    window = TimeWindow(D1, D10)
    assert window.contains(D1)
    assert window.contains(D10)
    assert window.contains(None)
    assert not window.contains(D10 + timedelta(seconds=1))
    assert not window.contains(D1 - timedelta(seconds=1))


def test_sabe_si_algo_quedo_antes() -> None:
    assert TimeWindow(D1).is_before(D1 - timedelta(days=1))
    assert not TimeWindow().is_before(D1)
    assert not TimeWindow(D1).is_before(None)


def test_rechaza_una_ventana_invertida() -> None:
    with pytest.raises(ValueError, match="empieza"):
        TimeWindow(D10, D1)


def test_parte_en_tramos() -> None:
    chunks = TimeWindow(D1, D10).chunks(timedelta(days=4))
    assert [(c.since, c.until) for c in chunks] == [
        (D1, D1 + timedelta(days=4)),
        (D1 + timedelta(days=4), D1 + timedelta(days=8)),
        (D1 + timedelta(days=8), D10),
    ]


def test_una_ventana_vacia_es_un_solo_tramo() -> None:
    assert TimeWindow(D1, D1).chunks(timedelta(days=1)) == (TimeWindow(D1, D1),)


def test_partir_necesita_los_dos_extremos_y_un_tramo_positivo() -> None:
    with pytest.raises(ValueError, match="extremos"):
        TimeWindow(D1).chunks(timedelta(days=1))
    with pytest.raises(ValueError, match="positivo"):
        TimeWindow(D1, D10).chunks(timedelta(0))
