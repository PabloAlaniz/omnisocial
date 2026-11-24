"""El ritmo que una red tolera: pedidos separados y un tope de simultáneos."""

from __future__ import annotations

import asyncio

import pytest

from omnisocial.adapters.http.pacing import PacedTransport, paced
from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.domain.spec import Pace
from omnisocial.testing import FakeTransport


class Time:
    """Un reloj que solo avanza cuando alguien espera."""

    def __init__(self) -> None:
        self.now = 100.0
        self.waited: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.waited.append(seconds)
        self.now += seconds


async def test_los_pedidos_salen_separados() -> None:
    inner, time = FakeTransport(), Time()
    inner.on("GET", "https://red.ejemplo.com/a", {}, {}, {})
    transport = PacedTransport(inner, Pace(min_interval=1.0), sleep=time.sleep, now=time)
    await asyncio.gather(*(transport.request("GET", "https://red.ejemplo.com/a") for _ in range(3)))
    # El primero sale enseguida; cada uno de los otros espera su turno.
    assert time.waited == [1.0, 1.0]
    time.now += 5
    inner.on("GET", "https://red.ejemplo.com/a", {})
    await transport.request("GET", "https://red.ejemplo.com/a")
    assert time.waited == [1.0, 1.0]


async def test_no_pasan_mas_pedidos_a_la_vez_que_el_tope() -> None:
    running = 0
    peak = 0

    class Slow:
        async def request(self, method: str, url: str, **_: object) -> HttpResponse:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0)
            running -= 1
            return HttpResponse(200, {})

    transport = PacedTransport(Slow(), Pace(max_concurrent=2))
    await asyncio.gather(*(transport.request("GET", "https://red.ejemplo.com/a") for _ in range(6)))
    assert peak == 2


async def test_sin_ritmo_declarado_el_transporte_es_el_mismo() -> None:
    inner = FakeTransport()
    assert paced(inner, None) is inner
    assert isinstance(paced(inner, Pace(max_concurrent=1)), PacedTransport)
    inner.on("POST", "https://red.ejemplo.com/a", {"ok": True})
    response = await paced(inner, Pace()).request("POST", "https://red.ejemplo.com/a", json={"a": 1})
    assert response.data == {"ok": True}
    assert inner.calls[0].json == {"a": 1}


@pytest.mark.parametrize("pace", [{"max_concurrent": 0}, {"min_interval": -1.0}])
def test_un_ritmo_imposible_no_se_declara(pace: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="pedido"):
        Pace(**pace)  # type: ignore[arg-type]
