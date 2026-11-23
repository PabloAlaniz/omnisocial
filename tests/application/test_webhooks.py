from __future__ import annotations

from collections.abc import Sequence

import pytest

from omnisocial.application.results import AuthorizationStarted, Connected
from omnisocial.application.use_cases.webhooks import RoutedEvent
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import CapabilityNotSupported
from omnisocial.domain.provider import Capability
from tests.application.conftest import World, build_world
from tests.fakes import FakeNetwork, FakeWebhooks, incoming, sign


class Collector:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.calls: list[Sequence[RoutedEvent]] = []
        self._fail_times = fail_times

    async def __call__(self, events: Sequence[RoutedEvent]) -> None:
        if self._fail_times:
            self._fail_times -= 1
            raise RuntimeError("la cola no responde")
        self.calls.append(events)


async def _connect(world: World) -> None:
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.CONNECT, owner="c")
    assert isinstance(started, AuthorizationStarted)
    assert isinstance(
        await world.social.complete_authorization.execute(state=started.state, code="x"), Connected
    )


async def test_un_aviso_firmado_llega_a_sus_duenos(world: World) -> None:
    await _connect(world)
    collector = Collector()
    result = await world.social.handle_webhook.execute(
        "falsa", request=incoming(b"pag-1", sign(b"pag-1")), on_events=collector
    )
    assert (result.outcome, result.status) == ("ok", 200)
    [routed] = result.events
    assert routed.event.object_external_id == "com-9"
    assert [a.owner for a in routed.assets] == ["c"]
    assert [tuple(c) for c in collector.calls] == [result.events]


async def test_un_aviso_repetido_no_se_procesa_dos_veces(world: World) -> None:
    collector = Collector()
    first = await world.social.handle_webhook.execute(
        "falsa", request=incoming(b"a", sign(b"a")), on_events=collector
    )
    again = await world.social.handle_webhook.execute(
        "falsa", request=incoming(b"a", sign(b"a")), on_events=collector
    )
    assert (first.outcome, again.outcome, again.status) == ("ok", "duplicate", 200)
    assert again.events == ()
    assert len(collector.calls) == 1


async def test_si_procesar_falla_el_reintento_entra(world: World) -> None:
    collector = Collector(fail_times=1)
    failed = await world.social.handle_webhook.execute(
        "falsa", request=incoming(b"a", sign(b"a")), on_events=collector
    )
    assert (failed.outcome, failed.status, failed.events) == ("failed", 500, ())
    assert isinstance(failed.error, RuntimeError)
    retried = await world.social.handle_webhook.execute(
        "falsa", request=incoming(b"a", sign(b"a")), on_events=collector
    )
    assert retried.outcome == "ok"
    assert len(collector.calls) == 1


@pytest.mark.parametrize(
    ("headers", "outcome"),
    [({"x-firma": "0" * 64}, "invalid"), ({}, "missing"), ({"x-firma": "no-es-hex"}, "invalid")],
)
async def test_sin_firma_valida_no_se_traduce(world: World, headers: dict[str, str], outcome: str) -> None:
    collector = Collector()
    result = await world.social.handle_webhook.execute(
        "falsa", request=incoming(b"a", headers), on_events=collector
    )
    assert (result.outcome, result.status) == (outcome, 401)
    assert collector.calls == []


async def test_sin_secreto_configurado_se_rechaza_todo() -> None:
    world = build_world(FakeNetwork(webhooks=FakeWebhooks(secrets=[])))
    collector = Collector()
    result = await world.social.handle_webhook.execute(
        "falsa", request=incoming(b"a", sign(b"a")), on_events=collector
    )
    assert (result.outcome, result.status) == ("unconfigured", 500)
    assert collector.calls == []


async def test_una_red_sin_webhooks() -> None:
    world = build_world(only=frozenset({Capability.LOGIN}))
    with pytest.raises(CapabilityNotSupported):
        await world.social.handle_webhook.execute("falsa", request=incoming(b"a", {}), on_events=Collector())
