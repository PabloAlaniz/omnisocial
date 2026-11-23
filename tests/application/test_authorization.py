from __future__ import annotations

from datetime import timedelta

import pytest

from omnisocial.application.results import (
    AuthorizationStarted,
    Connected,
    Done,
    LoggedIn,
    Refusal,
    Refused,
)
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.connection import ConnectionStatus
from omnisocial.domain.errors import CapabilityNotSupported, UnknownProvider
from omnisocial.domain.identity import Identity
from omnisocial.domain.provider import Capability
from omnisocial.domain.token import Token, TokenKind
from tests.application.conftest import World, build_world
from tests.fakes import FAKE, FakeNetwork, FakeOAuth


async def _connect(world: World, owner: str = "cliente-1", code: str = "abc") -> Connected:
    started = await world.social.start_authorization.execute(
        "falsa", purpose=Purpose.CONNECT, owner=owner, return_url="https://app.ejemplo.com/listo"
    )
    assert isinstance(started, AuthorizationStarted)
    result = await world.social.complete_authorization.execute(state=started.state, code=code)
    assert isinstance(result, Connected)
    return result


async def test_iniciar_arma_la_url_con_state_scopes_y_pkce(world: World) -> None:
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.LOGIN)
    assert isinstance(started, AuthorizationStarted)
    assert f"state={started.state}" in started.url
    assert "scopes=perfil&" in started.url
    assert "challenge=None" not in started.url


async def test_sin_pkce_no_manda_challenge() -> None:
    world = build_world(FakeNetwork(oauth=FakeOAuth(supports_pkce=False)))
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.LOGIN, scopes=["x"])
    assert isinstance(started, AuthorizationStarted)
    assert "challenge=None" in started.url
    assert "scopes=x&" in started.url


async def test_conectar_exige_dueño_y_return_url_permitida(world: World) -> None:
    assert await world.social.start_authorization.execute("falsa", purpose=Purpose.CONNECT) == Refused(
        Refusal.OWNER_REQUIRED
    )
    refused = await world.social.start_authorization.execute(
        "falsa", purpose=Purpose.LOGIN, return_url="https://malo.com/"
    )
    assert refused == Refused(Refusal.RETURN_URL_NOT_ALLOWED)


async def test_una_red_desconocida_o_sin_login_falla_fuerte() -> None:
    world = build_world(only=frozenset({Capability.CONTENT}))
    with pytest.raises(UnknownProvider):
        await world.social.start_authorization.execute("otra", purpose=Purpose.LOGIN)
    with pytest.raises(CapabilityNotSupported):
        await world.social.start_authorization.execute("falsa", purpose=Purpose.LOGIN)


async def test_login_devuelve_la_identidad_sin_guardar_nada(world: World) -> None:
    started = await world.social.start_authorization.execute(
        "falsa", purpose=Purpose.LOGIN, return_url="https://app.ejemplo.com/hola"
    )
    assert isinstance(started, AuthorizationStarted)
    result = await world.social.complete_authorization.execute(state=started.state, code="c1")
    assert isinstance(result, LoggedIn)
    assert result.identity.external_id == "persona-1"
    assert result.return_url == "https://app.ejemplo.com/hola"
    assert await world.connections.list_by_owner("cliente-1") == []
    code, redirect_uri, verifier = world.network.oauth.exchanged[0]
    assert (code, redirect_uri) == ("c1", "https://api.ejemplo.com/oauth/falsa/callback")
    assert verifier is not None


async def test_conectar_guarda_la_conexion_y_descubre_activos(world: World) -> None:
    result = await _connect(world)
    assert result.connection.owner == "cliente-1"
    assert result.connection.status is ConnectionStatus.ACTIVE
    assert result.return_url == "https://app.ejemplo.com/listo"
    assert not result.reconnected
    assert [a.external_id for a in result.assets] == ["pag-1", "cta-1"]
    assert [a.external_id for a in await world.assets.list_by_owner("cliente-1")] == ["pag-1", "cta-1"]


async def test_reconectar_reusa_la_conexion_y_los_ids_de_activos(world: World) -> None:
    first = await _connect(world)
    second = await _connect(world, code="otro")
    assert second.reconnected
    assert second.connection.id == first.connection.id
    assert second.connection.version == first.connection.version + 1
    assert second.connection.token.access_token == "tok-otro"
    assert [a.id for a in second.assets] == [a.id for a in first.assets]


async def test_otro_dueño_conecta_la_misma_cuenta_sin_pisar(world: World) -> None:
    first = await _connect(world, owner="cliente-1")
    second = await _connect(world, owner="cliente-2")
    assert first.connection.id != second.connection.id
    routed = await world.assets.find_by_external_id(FAKE, "pag-1")
    assert {a.owner for a in routed} == {"cliente-1", "cliente-2"}


async def test_el_state_sirve_una_sola_vez(world: World) -> None:
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.LOGIN)
    assert isinstance(started, AuthorizationStarted)
    await world.social.complete_authorization.execute(state=started.state, code="c")
    again = await world.social.complete_authorization.execute(state=started.state, code="c")
    assert again == Refused(Refusal.UNKNOWN_STATE)


async def test_el_state_vencido_se_rechaza(world: World) -> None:
    started = await world.social.start_authorization.execute(
        "falsa", purpose=Purpose.LOGIN, return_url="https://app.ejemplo.com/"
    )
    assert isinstance(started, AuthorizationStarted)
    world.network.clock.advance(timedelta(minutes=11))
    result = await world.social.complete_authorization.execute(state=started.state, code="c")
    assert result == Refused(Refusal.EXPIRED_STATE, return_url="https://app.ejemplo.com/")


async def test_si_la_persona_cancela_no_se_llama_a_la_red(world: World) -> None:
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.LOGIN)
    assert isinstance(started, AuthorizationStarted)
    result = await world.social.complete_authorization.execute(
        state=started.state, code=None, error="access_denied"
    )
    assert result == Refused(Refusal.PROVIDER_DENIED, detail="access_denied")
    assert world.network.oauth.exchanged == []


async def test_registrar_un_usuario_de_sistema(world: World) -> None:
    token = Token(TokenKind.SYSTEM, "tok-sistema")
    result = await world.social.register_system_connection.execute("falsa", owner="agencia", token=token)
    assert result.connection.token.kind is TokenKind.SYSTEM
    assert len(result.assets) == 2


async def test_una_red_sin_activos_conecta_igual() -> None:
    world = build_world(only=frozenset({Capability.LOGIN}))
    result = await world.social.register_system_connection.execute(
        "falsa", owner="x", token=Token(TokenKind.SYSTEM, "t")
    )
    assert result.assets == ()


async def test_desconectar_revoca_y_borra_activos(world: World) -> None:
    connected = await _connect(world)
    result = await world.social.disconnect.execute(connected.connection.id)
    assert isinstance(result, Done)
    assert result.value.status is ConnectionStatus.REVOKED
    assert world.network.oauth.revoked == ["tok-abc"]
    assert await world.assets.list_by_connection(connected.connection.id) == []


async def test_desconectar_tolera_un_token_ya_muerto_y_conexiones_inexistentes() -> None:
    world = build_world(FakeNetwork(oauth=FakeOAuth(reject_revoke=True)))
    connected = await _connect(world)
    assert isinstance(await world.social.disconnect.execute(connected.connection.id), Done)
    assert await world.social.disconnect.execute("nada") == Refused(Refusal.NOT_FOUND)


async def test_desconectar_sin_revocar_en_la_red(world: World) -> None:
    connected = await _connect(world)
    await world.social.disconnect.execute(connected.connection.id, revoke_remote=False)
    assert world.network.oauth.revoked == []


async def test_reconectar_si_otro_proceso_cambio_la_conexion(world: World) -> None:
    connected = await _connect(world)
    conn = connected.connection
    # Otro proceso guarda una versión nueva entre el find y el save de la reconexión.
    original_find = world.connections.find

    async def racy_find(**kwargs: object) -> object:
        found = await original_find(**kwargs)  # type: ignore[arg-type]
        if found is not None:
            bumped = found.with_token(Token(TokenKind.USER, "de-otro"), world.network.clock.now())
            await world.connections.save(bumped, expected_version=found.version)
            world.connections.find = original_find  # type: ignore[method-assign]
        return found

    world.connections.find = racy_find  # type: ignore[method-assign, assignment]
    again = await _connect(world, code="final")
    assert again.connection.id == conn.id
    stored = await world.connections.get(conn.id)
    assert stored is not None
    assert stored.token.access_token == "tok-final"
    assert stored.subject == Identity(FAKE, "persona-1", name="Persona")
