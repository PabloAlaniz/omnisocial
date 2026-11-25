"""Avisos de salud de las conexiones y renovación anticipada."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from omnisocial.adapters.http.transport import TransportError
from omnisocial.application.results import AuthorizationStarted, Connected, Done, Refused
from omnisocial.application.use_cases.refreshing import RefreshReport
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.connection import ConnectionChange, ConnectionStatus
from omnisocial.domain.errors import ProviderError, TokenRejected
from omnisocial.domain.identity import Identity
from omnisocial.domain.provider import ProviderId
from tests.application.conftest import World, build_world
from tests.fakes import FAKE, FakeNetwork, FakeOAuth


class Seen:
    def __init__(self) -> None:
        self.changes: list[ConnectionChange] = []

    async def __call__(self, change: ConnectionChange) -> None:
        self.changes.append(change)

    def summary(self) -> list[tuple[str, str, bool, bool]]:
        return [(c.previous.value, c.connection.status.value, c.lost, c.recovered) for c in self.changes]


async def _connect(world: World, owner: str = "c") -> Connected:
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.CONNECT, owner=owner)
    assert isinstance(started, AuthorizationStarted)
    result = await world.social.complete_authorization.execute(state=started.state, code="abc")
    assert isinstance(result, Connected)
    return result


# ── Avisos ──────────────────────────────────────────────────────────────────────────────────────


async def test_se_avisa_cuando_la_red_rechaza_el_token_y_cuando_alguien_reconecta() -> None:
    seen = Seen()
    world = build_world(on_connection_change=seen)
    connected = await _connect(world)
    # Conectar por primera vez no es un cambio de estado: la app ya recibe `Connected`.
    assert seen.changes == []
    page = connected.assets[0]

    world.network.comments.fail_with = TokenRejected(FAKE, "la persona quitó el acceso")
    assert isinstance(await world.social.list_comments.execute(page.id, object_id="post-1"), Refused)
    # Las operaciones siguientes se niegan sin llamar a la red: no hay otro aviso.
    assert isinstance(await world.social.list_posts.execute(page.id), Refused)
    assert seen.summary() == [("active", "invalid", True, False)]
    assert seen.changes[0].connection.status_reason == "la persona quitó el acceso"

    # Reconectar la recupera, con el mismo id de conexión y los mismos ids de activos.
    world.network.comments.fail_with = None
    again = await _connect(world)
    assert again.reconnected
    assert again.connection.id == connected.connection.id
    assert [a.id for a in again.assets] == [a.id for a in connected.assets]
    assert seen.summary()[1] == ("invalid", "active", False, True)
    assert isinstance(await world.social.list_posts.execute(page.id), Done)


async def test_se_avisa_cuando_vence_y_cuando_se_desconecta() -> None:
    seen = Seen()
    world = build_world(FakeNetwork(oauth=FakeOAuth(refreshable=False)), on_connection_change=seen)
    connected = await _connect(world)
    world.network.clock.advance(timedelta(hours=2))
    assert isinstance(await world.social.get_valid_token.execute(connected.connection.id), Refused)
    assert seen.summary() == [("active", "expired", True, False)]

    other = build_world(on_connection_change=seen)
    fresh = await _connect(other)
    # Reconectar una conexión sana no es un cambio de estado.
    await _connect(other)
    assert len(seen.changes) == 1
    await other.social.disconnect.execute(fresh.connection.id)
    assert seen.summary()[1] == ("active", "revoked", True, False)


async def test_renovar_un_token_no_es_un_cambio_de_estado() -> None:
    seen = Seen()
    world = build_world(on_connection_change=seen)
    connected = await _connect(world)
    world.network.clock.advance(timedelta(minutes=58))
    await world.social.get_valid_token.execute(connected.connection.id)
    assert world.network.oauth.refreshed == 1
    assert seen.changes == []


# ── Renovación anticipada ───────────────────────────────────────────────────────────────────────


async def test_renueva_lo_que_esta_por_vencer_aunque_nadie_lo_use(world: World) -> None:
    connected = await _connect(world)
    # El token dura una hora. Dentro de 30 minutos no vence nada: no hay nada que hacer.
    assert await world.social.refresh_expiring.execute(within=timedelta(minutes=30)) == RefreshReport()
    report = await world.social.refresh_expiring.execute(within=timedelta(hours=2))
    assert report == RefreshReport(refreshed=(connected.connection.id,))
    stored = await world.connections.get(connected.connection.id)
    assert stored is not None
    assert stored.token.access_token == "renovado1"
    assert world.network.oauth.refreshed == 1


async def test_el_informe_separa_lo_que_se_perdio_lo_que_no_se_puede_y_lo_que_fallo() -> None:
    seen = Seen()
    world = build_world(on_connection_change=seen)
    ids = []
    for number in range(4):
        world.network.oauth.subject = Identity(FAKE, f"persona-{number}")
        ids.append((await _connect(world, owner=f"dueño-{number}")).connection.id)
    lost, plain, errored, unknown = ids

    # Una conexión de una red que ya no está registrada, y una cuyo token no trae cómo renovarse.
    orphan = await world.connections.get(unknown)
    assert orphan is not None
    moved = replace(orphan, provider=ProviderId("otra"), version=orphan.version + 1)
    await world.connections.save(moved, expected_version=orphan.version)
    bare = await world.connections.get(plain)
    assert bare is not None
    no_refresh = bare.token.__class__(bare.token.kind, "sin-renovar", expires_at=bare.token.expires_at)
    await world.connections.save(bare.with_token(no_refresh, bare.updated_at), expected_version=bare.version)

    calls = 0
    original = world.network.oauth.refresh

    async def refresh(token: object) -> object:
        nonlocal calls
        calls += 1
        if token.refresh_token == "r-tok-abc" and calls == 1:  # type: ignore[attr-defined]
            raise TokenRejected(FAKE, "revocado")
        if calls == 2:
            raise ProviderError(FAKE, "se cayó", status=500)
        return await original(token)  # type: ignore[arg-type]

    world.network.oauth.refresh = refresh  # type: ignore[method-assign,assignment]
    report = await world.social.refresh_expiring.execute(within=timedelta(hours=2))
    assert (report.refreshed, report.lost, report.errored) == ((), (lost,), (errored,))
    assert set(report.not_refreshable) == {plain, unknown}
    # La que se perdió avisó; la que falló sigue como estaba y se reintenta en la próxima corrida.
    assert seen.summary() == [("active", "invalid", True, False)]
    assert getattr(await world.connections.get(errored), "status", None) is ConnectionStatus.ACTIVE


async def test_un_corte_de_red_no_frena_a_las_demas(world: World) -> None:
    connected = await _connect(world)

    async def refresh(token: object) -> object:
        raise TransportError("sin red")

    world.network.oauth.refresh = refresh  # type: ignore[method-assign,assignment]
    report = await world.social.refresh_expiring.execute(within=timedelta(hours=2))
    assert report == RefreshReport(errored=(connected.connection.id,))
