"""Cada llamada a una red avisa: cuál, a qué operación, cómo salió y cuánto tardó."""

from __future__ import annotations

import contextlib

import pytest

from omnisocial.application.observing import Observation, Result, error_name, observed
from omnisocial.application.results import AuthorizationStarted, Connected, Done, Refusal, Refused
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import (
    CapabilityNotSupported,
    ErrorKind,
    PermissionMissing,
    ProviderError,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import Draft
from tests.application.conftest import build_world
from tests.fakes import FAKE, FakeComments, FakeNetwork


class Recorder:
    def __init__(self) -> None:
        self.seen: list[Observation] = []

    def operation(self, observation: Observation) -> None:
        self.seen.append(observation)

    def names(self) -> list[tuple[str, str, str]]:
        return [(seen.port, seen.operation, str(seen.result)) for seen in self.seen]


class Ticks:
    """Un reloj que avanza medio segundo cada vez que se lo mira."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.5
        return self.now


async def _connect(world: object) -> str:
    social = world.social  # type: ignore[attr-defined]
    started = await social.start_authorization.execute("falsa", purpose=Purpose.CONNECT, owner="c")
    assert isinstance(started, AuthorizationStarted)
    connected = await social.complete_authorization.execute(state=started.state, code="abc")
    assert isinstance(connected, Connected)
    return connected.assets[0].id


async def test_conectar_y_usar_un_activo_deja_una_observacion_por_llamada() -> None:
    recorder = Recorder()
    world = build_world(observer=recorder)
    page = await _connect(world)
    assert recorder.names() == [
        ("oauth", "exchange_code", "ok"),
        ("oauth", "identity", "ok"),
        ("assets", "discover", "ok"),
    ]
    recorder.seen.clear()
    assert isinstance(await world.social.list_posts.execute(page), Done)
    assert isinstance(await world.social.publish.execute(page, Draft("hola")), Done)
    assert recorder.names() == [("content", "list_posts", "ok"), ("publisher", "publish", "ok")]
    assert {seen.provider for seen in recorder.seen} == {"falsa"}
    assert all(seen.duration >= 0 and seen.error is None for seen in recorder.seen)


async def test_lo_que_el_nucleo_niega_sin_llamar_a_la_red_no_se_observa() -> None:
    recorder = Recorder()
    world = build_world(observer=recorder)
    page = await _connect(world)
    recorder.seen.clear()
    refused = await world.social.publish.execute(page, Draft("x" * 500))
    assert isinstance(refused, Refused)
    assert refused.reason is Refusal.INVALID_DRAFT
    assert recorder.seen == []


@pytest.mark.parametrize(
    ("error", "name"),
    [
        (TokenRejected(FAKE, "token muerto: abc123"), "token_dead"),
        (PermissionMissing(FAKE, "falta pages_read"), "missing_permission"),
        (RateLimited(FAKE, "despacio"), "rate_limited"),
        (ProviderError(FAKE, "ups", kind=ErrorKind.TRANSIENT), "transient"),
    ],
)
async def test_un_error_se_cuenta_por_su_clase_y_nunca_por_su_mensaje(error: Exception, name: str) -> None:
    recorder = Recorder()
    world = build_world(FakeNetwork(comments=FakeComments(fail_with=error)), observer=recorder)
    page = await _connect(world)
    recorder.seen.clear()
    with contextlib.suppress(ProviderError):
        await world.social.list_comments.execute(page, object_id="post-1")
    [seen] = recorder.seen
    assert (seen.port, seen.operation, seen.result, seen.error) == (
        "comments",
        "list_comments",
        Result.ERROR,
        name,
    )
    assert str(error) not in repr(seen)


def test_los_errores_que_no_vienen_de_la_red() -> None:
    assert error_name(CapabilityNotSupported(FAKE, Capability.CONTENT)) == "CapabilityNotSupported"
    # El nombre de una excepción ajena podría decir algo de quien la lanzó: no se usa.
    assert error_name(ValueError("clave=abc")) == "unexpected"


async def test_la_duracion_sale_del_reloj_y_un_observador_roto_no_rompe_nada() -> None:
    network = FakeNetwork()
    recorder = Recorder()
    provider = observed(network.provider(), recorder, Ticks())
    assert provider.content is not None
    assert provider.spec is network.provider().spec
    # Lo que no es una llamada a la red pasa sin tocar ni avisar.
    assert provider.oauth is not None
    assert provider.oauth.default_scopes(Purpose.LOGIN) == network.oauth.default_scopes(Purpose.LOGIN)
    assert recorder.seen == []

    class Broken:
        def operation(self, observation: Observation) -> None:
            raise RuntimeError("el observador se rompió")

    world = build_world(observer=Broken())
    page = await _connect(world)
    assert isinstance(await world.social.list_posts.execute(page), Done)

    from omnisocial.domain.asset import Asset  # noqa: PLC0415
    from omnisocial.domain.token import Token, TokenKind  # noqa: PLC0415
    from omnisocial.domain.window import TimeWindow  # noqa: PLC0415
    from tests.fakes import NOW  # noqa: PLC0415

    asset = Asset("a", "c", FAKE, "dueño", "pagina", "pag-1")
    await provider.content.list_posts(
        asset, Token(TokenKind.USER, "t"), window=TimeWindow(None, NOW), limit=1
    )
    [seen] = recorder.seen
    assert seen.duration == 0.5
