"""Meta sin app: solo con un token de usuario de sistema cargado a mano."""

from __future__ import annotations

import pytest
from omniwebhook import AsyncMemoryIdempotencyStore

from omnisocial.adapters.providers.meta.config import FACEBOOK_PAGE, INSTAGRAM_ACCOUNT, MetaConfig
from omnisocial.adapters.providers.meta.deletion import MetaDeletionRequests
from omnisocial.adapters.providers.meta.graph import GraphClient
from omnisocial.adapters.providers.meta.oauth import MetaOAuth
from omnisocial.adapters.providers.meta.provider import meta_provider
from omnisocial.adapters.providers.meta.webhooks import MetaWebhookParser
from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
)
from omnisocial.application.results import Connected, Refusal, Refused
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import CapabilityNotSupported
from omnisocial.domain.provider import Capability
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.domain.token import Token, TokenKind
from omnisocial.entrypoints.hub import Omnisocial
from tests.adapters.meta.conftest import FakeGraph
from tests.fakes import FakeClock, FakeSecrets, SequentialIds

TOKEN_ONLY = MetaConfig(api_version="v24.0")


def _social(fake: FakeGraph, clock: FakeClock) -> Omnisocial:
    return Omnisocial.build(
        providers=[meta_provider(TOKEN_ONLY, fake, clock=clock)],
        connections=InMemoryConnectionRepository(),
        assets=InMemoryAssetRepository(),
        states=InMemoryAuthorizationStateStore(clock),
        webhook_events=AsyncMemoryIdempotencyStore(),
        redirect_uri_for=lambda provider: f"https://api.ejemplo.com/oauth/{provider}/callback",
        return_urls=ReturnUrlPolicy.of("https://app.ejemplo.com"),
        clock=clock,
        ids=SequentialIds(),
        secrets=FakeSecrets(),
    )


def test_sin_app_no_hay_oauth_ni_webhooks(fake: FakeGraph) -> None:
    provider = meta_provider(TOKEN_ONLY, fake)
    assert Capability.LOGIN not in provider.capabilities
    assert Capability.WEBHOOKS not in provider.capabilities
    assert {Capability.ASSETS, Capability.CONTENT, Capability.INSIGHTS} <= provider.capabilities
    for needs_app in (
        lambda: MetaOAuth(GraphClient(TOKEN_ONLY, fake), FakeClock()),
        lambda: MetaWebhookParser(TOKEN_ONLY),
        lambda: MetaDeletionRequests(TOKEN_ONLY),
    ):
        with pytest.raises(ValueError, match="modo token"):
            needs_app()


async def test_registrar_un_token_de_usuario_de_sistema(fake: FakeGraph, clock: FakeClock) -> None:
    fake.on(
        "GET",
        "me/accounts",
        {
            "data": [
                {
                    "id": "p1",
                    "name": "Página",
                    "access_token": "tok-p1",
                    "instagram_business_account": {"id": "ig1"},
                }
            ]
        },
    )
    fake.on("GET", "me", {"id": "sistema-1", "name": "Usuario de sistema"})
    social = _social(fake, clock)
    result = await social.register_system_connection.execute(
        "meta", owner="ci-project:20", token=Token(TokenKind.SYSTEM, "tok-sistema")
    )
    assert isinstance(result, Connected)
    assert result.connection.subject.name == "Usuario de sistema"
    assert {a.kind for a in result.assets} == {FACEBOOK_PAGE, INSTAGRAM_ACCOUNT}
    me = next(c for c in fake.calls if c.path == "me")
    assert me.params["fields"] == "id,name"
    assert all("appsecret_proof" not in c.params for c in fake.calls)
    # Los activos se descubren una sola vez.
    assert [c.path for c in fake.calls].count("me/accounts") == 1

    with pytest.raises(CapabilityNotSupported):
        await social.start_authorization.execute("meta", purpose=Purpose.CONNECT, owner="x")
    assert len(await social.list_assets.execute("ci-project:20", provider="meta")) == 2


async def test_un_token_sin_paginas_no_se_guarda(fake: FakeGraph, clock: FakeClock) -> None:
    fake.on("GET", "me/accounts", {"data": []})
    social = _social(fake, clock)
    result = await social.register_system_connection.execute(
        "meta", owner="ci-project:20", token=Token(TokenKind.SYSTEM, "tok")
    )
    assert result == Refused(Refusal.NO_ASSETS)
