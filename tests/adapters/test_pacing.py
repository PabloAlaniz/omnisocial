"""El ritmo que una red tolera: pedidos separados, un tope de simultáneos y turnos compartidos."""

from __future__ import annotations

import asyncio

import pytest

from omnisocial.adapters.http.pacing import PacedTransport, SharedTurns, asked_to_wait, paced
from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.stores.memory import InMemoryRateLimitStore
from omnisocial.domain.spec import Pace
from omnisocial.testing import FakeTransport

URL = "https://red.ejemplo.com/a"


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
    inner.on("GET", URL, {})
    transport = PacedTransport(inner, Pace(min_interval=1.0), sleep=time.sleep, now=time)
    await asyncio.gather(*(transport.request("GET", URL) for _ in range(3)))
    # El primero sale enseguida; cada uno de los otros espera su turno.
    assert time.waited == [1.0, 1.0]
    time.now += 5
    await transport.request("GET", URL)
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
    await asyncio.gather(*(transport.request("GET", URL) for _ in range(6)))
    assert peak == 2


async def test_sin_ritmo_declarado_el_transporte_es_el_mismo() -> None:
    inner = FakeTransport()
    assert paced(inner, None) is inner
    assert isinstance(paced(inner, Pace(max_concurrent=1)), PacedTransport)
    inner.on("POST", URL, {"ok": True})
    response = await paced(inner, Pace()).request("POST", URL, json={"a": 1})
    assert response.data == {"ok": True}
    assert inner.calls[0].json == {"a": 1}


@pytest.mark.parametrize("pace", [{"max_concurrent": 0}, {"min_interval": -1.0}])
def test_un_ritmo_imposible_no_se_declara(pace: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="pedido"):
        Pace(**pace)  # type: ignore[arg-type]


# ── Turnos compartidos ──────────────────────────────────────────────────────────────────────────


def _process(store: InMemoryRateLimitStore, time: Time, pace: Pace) -> tuple[PacedTransport, FakeTransport]:
    inner = FakeTransport()
    shared = SharedTurns(store, "reddit")
    return PacedTransport(inner, pace, sleep=time.sleep, now=time, shared=shared), inner


async def test_dos_procesos_se_reparten_los_turnos() -> None:
    time = Time()
    store = InMemoryRateLimitStore(time)
    pace = Pace(min_interval=0.6)
    (one, first), (two, second) = _process(store, time, pace), _process(store, time, pace)
    for inner in (first, second):
        inner.on("GET", URL, {})
    await one.request("GET", URL)
    await two.request("GET", URL)
    # El segundo proceso espera el turno que le deja el primero.
    assert time.waited == [pytest.approx(0.6)]
    other, third = _process(InMemoryRateLimitStore(time), time, pace)
    third.on("GET", URL, {})
    await other.request("GET", URL)
    assert len(time.waited) == 1


async def test_cuando_la_red_pide_esperar_esperan_todos() -> None:
    time = Time()
    store = InMemoryRateLimitStore(time)
    (one, first), (two, second) = _process(store, time, Pace()), _process(store, time, Pace())
    first.on("GET", URL, HttpResponse(429, None, "", {"Retry-After": "120"}))
    second.on("GET", URL, {})
    assert (await one.request("GET", URL)).status == 429
    # El otro proceso no llega a pedir: se le responde acá, con lo que falta.
    held = await two.request("GET", URL)
    assert (held.status, held.retry_after(), second.calls) == (429, 120.0, [])
    assert time.waited == []
    time.now += 100
    # Cuando falta poco, espera y pide.
    assert (await two.request("GET", URL)).status == 200
    assert time.waited == [20.0]


async def test_una_espera_no_acorta_otra_mayor() -> None:
    time = Time()
    store = InMemoryRateLimitStore(time)
    await store.pause("x", 60)
    await store.pause("x", 5)
    assert await store.reserve("x", 0) == 60.0
    assert await store.reserve("otra", 1.5) == 0.0
    assert await store.reserve("otra", 1.5) == 1.5


@pytest.mark.parametrize(
    ("headers", "seconds"),
    [
        ({"Retry-After": "7"}, 7.0),
        ({"X-RateLimit-Reset-After": "1.5"}, 1.5),
        ({"x-ratelimit-reset": "45"}, 45.0),
        # Una fecha no son segundos a esperar.
        ({"x-ratelimit-reset": "1795000000"}, None),
        ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT", "x-ratelimit-reset": "30"}, 30.0),
        ({}, None),
    ],
)
def test_cuanto_pidio_esperar_la_red(headers: dict[str, str], seconds: float | None) -> None:
    assert asked_to_wait(HttpResponse(429, None, "", headers)) == seconds


async def test_un_limite_sin_decir_cuanto_no_frena_a_los_demas() -> None:
    time = Time()
    store = InMemoryRateLimitStore(time)
    transport, inner = _process(store, time, Pace())
    inner.on("GET", URL, HttpResponse(429, None, ""), {})
    assert (await transport.request("GET", URL)).status == 429
    assert (await transport.request("GET", URL)).status == 200
