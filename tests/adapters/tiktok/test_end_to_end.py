"""Los casos de uso genéricos, de punta a punta, con el proveedor de TikTok y una API falsa."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from omniwebhook import AsyncMemoryIdempotencyStore

from omnisocial.adapters.providers.tiktok.provider import tiktok_provider
from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
)
from omnisocial.application.results import (
    AuthorizationStarted,
    Connected,
    Done,
    InsightsRead,
    Refusal,
    Refused,
)
from omnisocial.application.use_cases.webhooks import RoutedEvent
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.connection import ConnectionStatus
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.provider import Capability
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.domain.window import TimeWindow
from omnisocial.entrypoints.hub import Omnisocial
from tests.adapters.tiktok.conftest import FakeTikTok, config, failure, ok
from tests.adapters.tiktok.test_client_oauth import TOKENS
from tests.adapters.tiktok.test_content_insights_webhooks import REMOVED, signed, video
from tests.fakes import NOW, FakeClock, FakeSecrets, SequentialIds


def _social(fake: FakeTikTok, clock: FakeClock, connections: InMemoryConnectionRepository) -> Omnisocial:
    return Omnisocial.build(
        providers=[tiktok_provider(config(), fake, clock=clock)],
        connections=connections,
        assets=InMemoryAssetRepository(),
        states=InMemoryAuthorizationStateStore(clock),
        webhook_events=AsyncMemoryIdempotencyStore(),
        redirect_uri_for=lambda provider: f"https://api.ejemplo.com/oauth/{provider}/callback",
        return_urls=ReturnUrlPolicy.of("https://app.ejemplo.com"),
        clock=clock,
        ids=SequentialIds(),
        secrets=FakeSecrets(),
    )


async def _connect(social: Omnisocial, fake: FakeTikTok) -> Connected:
    fake.on("POST", "oauth/token/", TOKENS)
    fake.on("GET", "user/info/", ok({"user": {"open_id": "oid-1", "display_name": "Marca"}}))
    started = await social.start_authorization.execute("tiktok", purpose=Purpose.CONNECT, owner="cliente-1")
    assert isinstance(started, AuthorizationStarted)
    connected = await social.complete_authorization.execute(state=started.state, code="codigo")
    assert isinstance(connected, Connected)
    return connected


async def test_conectar_leer_y_renovar(clock: FakeClock) -> None:
    fake, connections = FakeTikTok(), InMemoryConnectionRepository()
    social = _social(fake, clock, connections)
    connected = await _connect(social, fake)
    [account] = connected.assets
    assert (account.kind, account.external_id) == ("tiktok_account", "oid-1")
    assert not account.supports(Capability.COMMENTS)

    fake.on("POST", "video/list/", ok({"videos": [video("v1", 1, view_count=9)], "has_more": False}))
    posts = await social.list_posts.execute(account.id, window=TimeWindow(NOW - timedelta(days=1), NOW))
    assert isinstance(posts, Done)
    assert posts.value[0].view_count == 9
    assert fake.calls[-1].headers == {"Authorization": "Bearer act.1"}

    # El token dura 2 horas: pasado ese tiempo se renueva solo y se guarda el refresh token nuevo.
    clock.advance(timedelta(hours=2))
    fake.routes[("POST", "oauth/token/")] = []
    fake.on("POST", "oauth/token/", {**TOKENS, "access_token": "act.2", "refresh_token": "rft.2"})
    fake.routes[("GET", "user/info/")] = []
    fake.on("GET", "user/info/", ok({"user": {"follower_count": 1500}}))
    insights = await social.read_insights.execute(
        account.id, metrics=[CanonicalMetric.FOLLOWERS], period=Period.DAY, window=TimeWindow()
    )
    assert isinstance(insights, InsightsRead)
    assert insights.series[0].canonical is CanonicalMetric.FOLLOWERS
    stored = await connections.get(connected.connection.id)
    assert stored is not None
    assert (stored.token.access_token, stored.token.refresh_token) == ("act.2", "rft.2")

    comments = await social.list_comments.execute(account.id, object_id="v1")
    assert isinstance(comments, Refused)
    assert comments.reason is Refusal.NOT_SUPPORTED


async def test_un_token_rechazado_deja_la_conexion_invalida(clock: FakeClock) -> None:
    fake, connections = FakeTikTok(), InMemoryConnectionRepository()
    social = _social(fake, clock, connections)
    connected = await _connect(social, fake)
    fake.on("POST", "video/list/", failure("access_token_invalid"), status=401)
    result = await social.list_posts.execute(connected.assets[0].id)
    assert isinstance(result, Refused)
    assert result.reason is Refusal.CONNECTION_INVALID
    stored = await connections.get(connected.connection.id)
    assert stored is not None
    assert stored.status is ConnectionStatus.INVALID


async def test_quitar_el_acceso_desde_tiktok_revoca_la_conexion(clock: FakeClock) -> None:
    fake, connections = FakeTikTok(), InMemoryConnectionRepository()
    social = _social(fake, clock, connections)
    connected = await _connect(social, fake)
    received: list[RoutedEvent] = []

    async def on_events(events: Sequence[RoutedEvent]) -> None:
        received.extend(events)

    result = await social.handle_webhook.execute("tiktok", request=signed(REMOVED), on_events=on_events)
    assert result.status == 200
    assert [r.assets[0].id for r in received] == [connected.assets[0].id]
    stored = await connections.get(connected.connection.id)
    assert stored is not None
    assert stored.status is ConnectionStatus.REVOKED
    after = await social.list_posts.execute(connected.assets[0].id)
    assert isinstance(after, Refused)
    assert after.reason is Refusal.CONNECTION_REVOKED
    # Un segundo aviso igual es un duplicado; uno nuevo sobre una conexión ya revocada no cambia nada.
    again = await social.handle_webhook.execute("tiktok", request=signed(REMOVED), on_events=on_events)
    assert again.outcome == "duplicate"
