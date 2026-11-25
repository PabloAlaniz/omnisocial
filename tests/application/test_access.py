from __future__ import annotations

from datetime import timedelta

from omnisocial.application.results import AuthorizationStarted, Connected, Refusal, Refused, ValidToken
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.connection import ConnectionStatus
from omnisocial.domain.token import Token, TokenKind
from tests.application.conftest import World, build_world
from tests.fakes import FakeNetwork, FakeOAuth


async def _connect(world: World) -> Connected:
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.CONNECT, owner="c")
    assert isinstance(started, AuthorizationStarted)
    result = await world.social.complete_authorization.execute(state=started.state, code="abc")
    assert isinstance(result, Connected)
    return result


async def test_un_token_vigente_se_devuelve_tal_cual(world: World) -> None:
    connected = await _connect(world)
    result = await world.social.get_valid_token.execute(connected.connection.id)
    assert isinstance(result, ValidToken)
    assert result.token.access_token == "tok-abc"
    assert world.network.oauth.refreshed == 0


async def test_cerca_de_vencer_se_renueva_y_se_guarda(world: World) -> None:
    connected = await _connect(world)
    world.network.clock.advance(timedelta(minutes=56))
    result = await world.social.get_valid_token.execute(connected.connection.id)
    assert isinstance(result, ValidToken)
    assert result.token.access_token == "renovado1"
    stored = await world.connections.get(connected.connection.id)
    assert stored is not None
    assert stored.token.access_token == "renovado1"
    assert stored.version == connected.connection.version + 1


async def test_si_la_red_rechaza_la_renovacion_queda_invalida() -> None:
    world = build_world(FakeNetwork(oauth=FakeOAuth(reject_refresh=True)))
    connected = await _connect(world)
    world.network.clock.advance(timedelta(hours=2))
    result = await world.social.get_valid_token.execute(connected.connection.id)
    assert result == Refused(Refusal.CONNECTION_INVALID, detail="revocado por la persona")
    # No se vuelve a intentar.
    assert await world.social.get_valid_token.execute(connected.connection.id) == result
    assert world.network.oauth.refreshed == 1


async def test_sin_renovacion_posible_se_usa_hasta_que_vence() -> None:
    world = build_world(FakeNetwork(oauth=FakeOAuth(refreshable=False)))
    connected = await _connect(world)
    world.network.clock.advance(timedelta(minutes=58))
    assert isinstance(await world.social.get_valid_token.execute(connected.connection.id), ValidToken)
    world.network.clock.advance(timedelta(minutes=3))
    result = await world.social.get_valid_token.execute(connected.connection.id)
    assert isinstance(result, Refused)
    assert result.reason is Refusal.CONNECTION_EXPIRED
    stored = await world.connections.get(connected.connection.id)
    assert stored is not None
    assert stored.status is ConnectionStatus.EXPIRED


async def test_una_conexion_inexistente(world: World) -> None:
    assert await world.social.get_valid_token.execute("nada") == Refused(Refusal.NOT_FOUND)


async def test_si_otro_proceso_renovo_primero_se_usa_su_token(world: World) -> None:
    connected = await _connect(world)
    world.network.clock.advance(timedelta(minutes=56))
    conn_id = connected.connection.id
    original_save = world.connections.save
    raced = False

    async def racy_save(connection: object, *, expected_version: int) -> bool:
        nonlocal raced
        if not raced:
            raced = True
            current = await world.connections.get(conn_id)
            assert current is not None
            other = current.with_token(
                current.token.__class__(
                    current.token.kind,
                    "del-otro",
                    expires_at=world.network.clock.now() + timedelta(hours=1),
                ),
                world.network.clock.now(),
            )
            await original_save(other, expected_version=current.version)
        return await original_save(connection, expected_version=expected_version)  # type: ignore[arg-type]

    world.connections.save = racy_save  # type: ignore[method-assign]
    result = await world.social.get_valid_token.execute(conn_id)
    assert isinstance(result, ValidToken)
    assert result.token.access_token == "del-otro"


async def test_el_activo_usa_su_propio_token(world: World) -> None:
    connected = await _connect(world)
    page, account = connected.assets
    page_access = await world.social.resolve_asset_access.execute(page.id)
    account_access = await world.social.resolve_asset_access.execute(account.id)
    assert not isinstance(page_access, Refused)
    assert not isinstance(account_access, Refused)
    assert page_access.token.access_token == "tok-pagina"
    assert account_access.token.access_token == "tok-abc"


async def test_un_activo_de_una_conexion_revocada_no_se_usa(world: World) -> None:
    connected = await _connect(world)
    page_id = connected.assets[0].id
    await world.social.disconnect.execute(connected.connection.id)
    assert await world.social.resolve_asset_access.execute(page_id) == Refused(Refusal.NOT_FOUND)
    assert await world.social.resolve_asset_access.execute("nada") == Refused(Refusal.NOT_FOUND)


async def test_un_activo_de_una_conexion_invalida_no_se_usa() -> None:
    world = build_world(FakeNetwork(oauth=FakeOAuth(reject_refresh=True)))
    connected = await _connect(world)
    world.network.clock.advance(timedelta(hours=2))
    result = await world.social.resolve_asset_access.execute(connected.assets[0].id)
    assert isinstance(result, Refused)
    assert result.reason is Refusal.CONNECTION_INVALID


async def test_sincronizar_activos(world: World) -> None:
    connected = await _connect(world)
    world.network.assets.items = world.network.assets.items[:1]
    synced = await world.social.sync_assets.execute(connected.connection.id)
    assert not isinstance(synced, Refused)
    assert [a.external_id for a in synced.value] == ["pag-1"]
    assert synced.value[0].id == connected.assets[0].id
    assert [a.external_id for a in await world.social.list_assets.execute("c", provider="falsa")] == ["pag-1"]
    assert await world.social.list_assets.execute("c", provider="otra") == []
    assert await world.social.sync_assets.execute("nada") == Refused(Refusal.NOT_FOUND)


async def test_perder_la_carrera_con_un_token_de_renovacion_que_rota_no_invalida_la_conexion() -> None:
    """Dos procesos renuevan a la vez con el mismo token de renovación. La red acepta al primero y le
    responde `invalid_grant` al segundo, porque ese token ya se usó. El segundo no tiene que marcar la
    conexión como inválida: relee y usa el token que guardó el primero."""
    world = build_world(FakeNetwork(oauth=FakeOAuth(reject_refresh=True)))
    connected = await _connect(world)
    world.network.clock.advance(timedelta(minutes=56))
    conn_id = connected.connection.id
    original_save = world.connections.save
    raced = False

    async def racy_save(connection: object, *, expected_version: int) -> bool:
        nonlocal raced
        if not raced:
            raced = True
            current = await world.connections.get(conn_id)
            assert current is not None
            now = world.network.clock.now()
            winner = Token(
                TokenKind.USER, "del-otro", refresh_token="r-nuevo", expires_at=now + timedelta(hours=2)
            )
            await original_save(current.with_token(winner, now), expected_version=current.version)
        return await original_save(connection, expected_version=expected_version)  # type: ignore[arg-type]

    world.connections.save = racy_save  # type: ignore[method-assign]
    result = await world.social.get_valid_token.execute(conn_id)
    assert isinstance(result, ValidToken)
    assert (result.token.access_token, result.token.refresh_token) == ("del-otro", "r-nuevo")
    stored = await world.connections.get(conn_id)
    assert stored is not None
    assert stored.status is ConnectionStatus.ACTIVE
