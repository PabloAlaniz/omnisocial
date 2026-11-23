"""Los casos de uso genéricos, de punta a punta, con el proveedor de Meta y una Graph API falsa."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

from omniwebhook import AsyncMemoryIdempotencyStore, IncomingRequest

from omnisocial.adapters.providers.meta.config import FACEBOOK_PAGE
from omnisocial.adapters.providers.meta.provider import meta_provider
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
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.domain.window import TimeWindow
from omnisocial.entrypoints.hub import Omnisocial
from tests.adapters.meta.conftest import FakeGraph, config
from tests.fakes import NOW, FakeClock, FakeSecrets, SequentialIds


def _social(fake: FakeGraph, clock: FakeClock) -> Omnisocial:
    return Omnisocial.build(
        providers=[meta_provider(config(), fake, clock=clock)],
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


def _meta_responds(fake: FakeGraph) -> None:
    fake.on(
        "GET",
        "oauth/access_token",
        {"access_token": "corto"},
        {"access_token": "largo", "expires_in": 5184000},
    )
    fake.on("GET", "me/permissions", {"data": [{"permission": "read_insights", "status": "granted"}]})
    fake.on("GET", "me", {"id": "persona-1", "name": "Ana"})
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


async def _connect(social: Omnisocial) -> Connected:
    started = await social.start_authorization.execute(
        "meta", purpose=Purpose.CONNECT, owner="cliente-1", return_url="https://app.ejemplo.com/conexiones"
    )
    assert isinstance(started, AuthorizationStarted)
    assert started.url.startswith("https://www.facebook.com/v24.0/dialog/oauth?")
    result = await social.complete_authorization.execute(state=started.state, code="codigo")
    assert isinstance(result, Connected)
    return result


async def test_conectar_y_leer_metricas_de_una_pagina(fake: FakeGraph, clock: FakeClock) -> None:
    _meta_responds(fake)
    social = _social(fake, clock)
    connected = await _connect(social)
    assert connected.connection.subject.name == "Ana"
    assert connected.connection.token.scopes == {"read_insights"}
    page = next(a for a in connected.assets if a.kind == FACEBOOK_PAGE)

    fake.on(
        "GET",
        "p1/insights",
        {
            "data": [
                {"name": "page_follows", "values": [{"value": 1200, "end_time": "2026-11-22T08:00:00+0000"}]}
            ]
        },
    )
    result = await social.read_insights.execute(
        page.id,
        metrics=[CanonicalMetric.FOLLOWERS],
        period=Period.DAY,
        window=TimeWindow(NOW - timedelta(days=7), NOW),
    )
    assert isinstance(result, InsightsRead)
    [series] = result.series
    assert (series.name, series.canonical, series.points[0].value) == (
        "page_follows",
        CanonicalMetric.FOLLOWERS,
        1200.0,
    )
    # Se habló con la página usando el token de la página, no el de la persona.
    assert fake.calls[-1].params["access_token"] == "tok-p1"


async def test_el_token_de_usuario_vencido_obliga_a_reconectar(fake: FakeGraph, clock: FakeClock) -> None:
    _meta_responds(fake)
    social = _social(fake, clock)
    connected = await _connect(social)
    clock.advance(timedelta(days=61))
    result = await social.get_valid_token.execute(connected.connection.id)
    assert isinstance(result, Refused)
    assert result.reason is Refusal.CONNECTION_EXPIRED


async def test_responder_un_mensaje_de_instagram(fake: FakeGraph, clock: FakeClock) -> None:
    _meta_responds(fake)
    social = _social(fake, clock)
    connected = await _connect(social)
    instagram = next(a for a in connected.assets if a.external_id == "ig1")
    fake.on(
        "GET",
        "t1/messages",
        {
            "data": [
                {
                    "id": "m1",
                    "message": "Hola",
                    "from": {"id": "u1"},
                    "created_time": (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S+0000"),
                }
            ]
        },
    )
    fake.on("POST", "p1/messages", {"recipient_id": "u1", "message_id": "mid.9"})
    assert await social.send_message.execute(instagram.id, conversation_id="t1", text="¡Hola!") == Done(
        "mid.9"
    )


async def test_un_webhook_firmado_llega_al_dueno(fake: FakeGraph, clock: FakeClock) -> None:
    _meta_responds(fake)
    social = _social(fake, clock)
    await _connect(social)
    body = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "p1",
                    "changes": [
                        {"field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "c1"}}
                    ],
                }
            ],
        }
    ).encode()
    signature = "sha256=" + hmac.new(b"secreto", body, hashlib.sha256).hexdigest()
    received: list[object] = []

    async def on_events(events: object) -> None:
        received.append(events)

    request = IncomingRequest(headers=[("X-Hub-Signature-256", signature)], query=[], body=body)
    result = await social.handle_webhook.execute("meta", request=request, on_events=on_events)
    assert result.outcome == "ok"
    [routed] = result.events
    assert [a.owner for a in routed.assets] == ["cliente-1"]
    duplicate = await social.handle_webhook.execute("meta", request=request, on_events=on_events)
    assert duplicate.outcome == "duplicate"
    assert len(received) == 1
