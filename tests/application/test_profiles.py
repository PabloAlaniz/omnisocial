from __future__ import annotations

import pytest

from omnisocial.application.results import AuthorizationStarted, Connected, Done, Refusal, Refused
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import PermissionMissing, TokenRejected
from omnisocial.domain.handles import Network
from omnisocial.domain.provider import Capability, ProviderId
from tests.application.conftest import World, build_world

FAKE = ProviderId("falsa")


async def _connect(world: World) -> dict[str, str]:
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.CONNECT, owner="c")
    assert isinstance(started, AuthorizationStarted)
    result = await world.social.complete_authorization.execute(state=started.state, code="abc")
    assert isinstance(result, Connected)
    return {asset.kind: asset.id for asset in result.assets}


async def test_una_red_que_no_necesita_mirador(world: World) -> None:
    result = await world.social.lookup_profile.execute("falsa", network="x", handle="https://x.com/Otra")
    assert isinstance(result, Done)
    assert (result.value.external_id, result.value.followers) == ("44196397", 10)
    assert world.network.profiles.calls == [("otra", None, None)]


async def test_instagram_a_traves_de_una_cuenta_propia(world: World) -> None:
    assets = await _connect(world)
    result = await world.social.lookup_profile.execute(
        "falsa", network=Network.INSTAGRAM, handle="@Marca", viewer_asset_id=assets["cuenta"]
    )
    assert isinstance(result, Done)
    assert result.value.username == "marca"
    # La cuenta no tiene token propio: va el de la conexión.
    assert world.network.profiles.calls == [("marca", "cta-1", "tok-abc")]


async def test_sin_mirador_o_con_uno_que_no_sirve(world: World) -> None:
    assets = await _connect(world)
    missing = await world.social.lookup_profile.execute("falsa", network="instagram", handle="marca")
    wrong = await world.social.lookup_profile.execute(
        "falsa", network="instagram", handle="marca", viewer_asset_id=assets["pagina"]
    )
    gone = await world.social.lookup_profile.execute(
        "falsa", network="instagram", handle="marca", viewer_asset_id="no-existe"
    )
    assert missing == Refused(Refusal.VIEWER_REQUIRED, detail="cuenta")
    assert wrong == Refused(Refusal.VIEWER_REQUIRED, detail="cuenta")
    assert gone == Refused(Refusal.NOT_FOUND)
    assert world.network.profiles.calls == []


async def test_nombre_invalido_cuenta_inexistente_y_red_no_cubierta(world: World) -> None:
    invalid = await world.social.lookup_profile.execute("falsa", network="x", handle="no vale")
    unknown = await world.social.lookup_profile.execute("falsa", network="x", handle="nadie")
    uncovered = await world.social.lookup_profile.execute("falsa", network="tiktok", handle="@marca")
    assert invalid == Refused(Refusal.INVALID_HANDLE, detail="no vale")
    assert unknown == Refused(Refusal.PROFILE_NOT_FOUND, detail="nadie")
    assert uncovered == Refused(Refusal.NOT_SUPPORTED, detail="tiktok", capability=Capability.PUBLIC_PROFILES)


async def test_una_red_sin_perfiles_publicos() -> None:
    world = build_world(only=frozenset({Capability.LOGIN}))
    result = await world.social.lookup_profile.execute("falsa", network="x", handle="otra")
    assert isinstance(result, Refused)
    assert result.reason is Refusal.NOT_SUPPORTED


async def test_errores_de_la_red(world: World) -> None:
    assets = await _connect(world)
    world.network.profiles.fail_with = PermissionMissing(FAKE, "falta instagram_basic")
    missing = await world.social.lookup_profile.execute(
        "falsa", network="instagram", handle="marca", viewer_asset_id=assets["cuenta"]
    )
    assert isinstance(missing, Refused)
    assert missing.reason is Refusal.MISSING_PERMISSION

    world.network.profiles.fail_with = TokenRejected(FAKE, "revocado")
    rejected = await world.social.lookup_profile.execute(
        "falsa", network="instagram", handle="marca", viewer_asset_id=assets["cuenta"]
    )
    assert rejected == Refused(Refusal.CONNECTION_INVALID, detail="revocado")

    # Sin mirador no hay conexión que marcar: el error sube.
    with pytest.raises(TokenRejected):
        await world.social.lookup_profile.execute("falsa", network="x", handle="otra")
