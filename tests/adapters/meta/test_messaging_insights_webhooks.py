from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from omniwebhook import IncomingRequest, Verified

from omnisocial.adapters.providers.meta.config import FACEBOOK_PAGE, INSTAGRAM_ACCOUNT, META
from omnisocial.adapters.providers.meta.graph import GraphClient
from omnisocial.adapters.providers.meta.insights import MetaInsightsReader
from omnisocial.adapters.providers.meta.messaging import MetaMessagingGateway
from omnisocial.adapters.providers.meta.webhooks import MetaWebhookParser, verify_subscription
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.metrics import MetricPoint, Period
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.webhooks import EventAction, EventKind
from omnisocial.domain.window import TimeWindow
from tests.adapters.meta.conftest import FakeGraph, config
from tests.fakes import NOW, FakeClock

TOKEN = Token(TokenKind.ASSET, "tok")
PAGE = Asset("a1", "c1", META, "dueño", FACEBOOK_PAGE, "p1")
INSTAGRAM = Asset("a2", "c1", META, "dueño", INSTAGRAM_ACCOUNT, "ig1", parent_external_id="p1")
ORPHAN = Asset("a3", "c1", META, "dueño", INSTAGRAM_ACCOUNT, "ig2")


# ── Mensajes ────────────────────────────────────────────────────────────────────────────────────


async def test_conversaciones_de_messenger_e_instagram(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on(
        "GET",
        "p1/conversations",
        {
            "data": [
                {
                    "id": "t1",
                    "updated_time": "2026-11-20T10:00:00+0000",
                    "participants": {"data": [{"id": "u1"}, {"id": "p1"}]},
                },
                {"updated_time": "sin id"},
            ]
        },
    )
    gateway = MetaMessagingGateway(graph)
    [conversation] = await gateway.list_conversations(PAGE, TOKEN, limit=10)
    assert (conversation.participant_ids, conversation.channel) == (("u1", "p1"), "messenger")
    [ig] = await gateway.list_conversations(INSTAGRAM, TOKEN, limit=None)
    assert ig.channel == "instagram"
    assert ig.asset_external_id == "ig1"
    assert [c.params["platform"] for c in fake.calls] == ["messenger", "instagram"]


async def test_mensajes_distinguen_lo_que_mando_el_activo(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on(
        "GET",
        "t1/messages",
        {
            "data": [
                {
                    "id": "m2",
                    "message": "Hola, ¿en qué te ayudo?",
                    "from": {"id": "ig1"},
                    "created_time": "2026-11-20T10:05:00+0000",
                },
                {
                    "id": "m1",
                    "message": "Hola",
                    "from": {"id": "u1"},
                    "created_time": "2026-11-20T10:00:00+0000",
                },
                {"message": "sin id"},
            ]
        },
    )
    reply, inbound = await MetaMessagingGateway(graph).list_messages(
        INSTAGRAM, TOKEN, conversation_id="t1", limit=None
    )
    assert reply.from_asset
    assert not inbound.from_asset
    assert inbound.sender_id == "u1"


async def test_enviar_por_la_pagina(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("POST", "p1/messages", {"recipient_id": "u1", "message_id": "mid.1"})
    gateway = MetaMessagingGateway(graph)
    assert await gateway.send(INSTAGRAM, TOKEN, recipient_id="u1", text="Hola") == "mid.1"
    assert fake.calls[0].json == {
        "recipient": {"id": "u1"},
        "message": {"text": "Hola"},
        "messaging_type": "RESPONSE",
    }
    assert gateway.reply_window.duration == timedelta(hours=24)


async def test_enviar_sin_id_o_sin_pagina_es_error(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("POST", "p1/messages", {"recipient_id": "u1"})
    gateway = MetaMessagingGateway(graph)
    with pytest.raises(ProviderError, match="id del mensaje"):
        await gateway.send(PAGE, TOKEN, recipient_id="u1", text="Hola")
    with pytest.raises(ProviderError, match="página conectada"):
        await gateway.list_conversations(ORPHAN, TOKEN, limit=None)


# ── Métricas ────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def reader(graph: GraphClient) -> MetaInsightsReader:
    return MetaInsightsReader(graph, FakeClock())


async def test_metricas_de_pagina_parten_la_ventana(fake: FakeGraph, reader: MetaInsightsReader) -> None:
    fake.on(
        "GET",
        "p1/insights",
        {
            "data": [
                {
                    "name": "page_follows",
                    "values": [
                        {"value": 100, "end_time": "2026-08-02T07:00:00+0000"},
                        {"value": {"AR": 3, "ES": 2}, "end_time": "2026-08-03T07:00:00+0000"},
                        {"value": "raro", "end_time": "2026-08-04T07:00:00+0000"},
                    ],
                },
                {"values": []},
            ]
        },
    )
    window = TimeWindow(NOW - timedelta(days=120), NOW)
    [series] = await reader.read(PAGE, TOKEN, metrics=["page_follows"], period=Period.DAY, window=window)
    assert len(fake.calls) == 2  # 90 + 30 días
    assert series.points[:2] == (
        MetricPoint(datetime(2026, 8, 2, 7, tzinfo=UTC), 100.0),
        MetricPoint(datetime(2026, 8, 3, 7, tzinfo=UTC), 5.0),
    )
    first = fake.calls[0].params
    assert (first["metric"], first["period"]) == ("page_follows", "day")
    assert first["until"] - first["since"] == 90 * 86400  # type: ignore[operator]


async def test_sin_ventana_usa_los_ultimos_28_dias(fake: FakeGraph, reader: MetaInsightsReader) -> None:
    fake.on("GET", "p1/insights", {"data": []})
    assert (
        await reader.read(PAGE, TOKEN, metrics=["page_follows"], period=Period.DAY, window=TimeWindow()) == []
    )
    params = fake.calls[0].params
    assert params["until"] == int(NOW.timestamp())
    assert params["since"] == int((NOW - timedelta(days=28)).timestamp())


async def test_instagram_separa_series_y_totales(fake: FakeGraph, reader: MetaInsightsReader) -> None:
    fake.on(
        "GET",
        "ig1/insights",
        {"data": [{"name": "reach", "values": [{"value": 10, "end_time": "2026-11-22T08:00:00+0000"}]}]},
        {"data": [{"name": "views", "total_value": {"value": 500}}, {"name": "likes", "total_value": {}}]},
    )
    window = TimeWindow(NOW - timedelta(days=7), NOW)
    series = await reader.read(
        INSTAGRAM, TOKEN, metrics=["reach", "views", "likes"], period=Period.DAY, window=window
    )
    assert [(s.name, s.points) for s in series] == [
        ("reach", (MetricPoint(datetime(2026, 11, 22, 8, tzinfo=UTC), 10.0),)),
        ("views", (MetricPoint(NOW, 500.0),)),
    ]
    assert "metric_type" not in fake.calls[0].params
    assert fake.calls[1].params["metric_type"] == "total_value"
    assert fake.calls[1].params["metric"] == "views,likes"
    assert reader.api_version == "v24.0"


# ── Webhooks ────────────────────────────────────────────────────────────────────────────────────


def _signed(body: bytes, secret: bytes = b"secreto") -> dict[str, str]:
    return {"x-hub-signature-256": "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()}


def test_suscripcion() -> None:
    query = {"hub.mode": "subscribe", "hub.verify_token": "verificar", "hub.challenge": "123"}
    assert verify_subscription(query, "verificar") == "123"
    assert verify_subscription({**query, "hub.verify_token": "otro"}, "verificar") is None
    assert verify_subscription({**query, "hub.mode": "otra"}, "verificar") is None
    assert verify_subscription(query, None) is None


def _verify(parser: MetaWebhookParser, body: bytes, headers: dict[str, str]) -> str:
    verification = parser.verifier.verify(IncomingRequest(headers=list(headers.items()), query=[], body=body))
    return "ok" if isinstance(verification, Verified) else verification.outcome


def test_firma() -> None:
    parser = MetaWebhookParser(config())
    body = b'{"object":"page"}'
    assert _verify(parser, body, _signed(body)) == "ok"
    assert _verify(parser, body, {"X-Hub-Signature-256": _signed(body)["x-hub-signature-256"]}) == "ok"
    assert _verify(parser, body, _signed(body, b"otro")) == "invalid"
    assert _verify(parser, body + b" ", _signed(body)) == "invalid"
    assert _verify(parser, body, {}) == "missing"
    assert _verify(parser, body, {"x-hub-signature-256": "sha1=abc"}) == "malformed"


def test_rotacion_del_secreto() -> None:
    body = b'{"object":"page"}'
    rotating = MetaWebhookParser(config(app_secret="nuevo", previous_app_secrets=("secreto",)))
    assert _verify(rotating, body, _signed(body, b"secreto")) == "ok"
    assert _verify(rotating, body, _signed(body, b"nuevo")) == "ok"
    assert (
        _verify(MetaWebhookParser(config(app_secret="nuevo")), body, _signed(body, b"secreto")) == "invalid"
    )


def test_los_secretos_no_aparecen_en_repr() -> None:
    assert "anterior" not in repr(config(previous_app_secrets=("anterior",)))


def test_traduce_avisos_de_pagina_instagram_y_mensajes() -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "p1",
                "time": 1795000000,
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "add",
                            "comment_id": "c1",
                            "message": "Hola",
                            "from": {"id": "u1"},
                            "created_time": 1795000001,
                        },
                    },
                    {"field": "feed", "value": {"item": "status", "verb": "edited", "post_id": "p1_9"}},
                    {"field": "feed", "value": {"item": "reaction", "verb": "remove"}},
                    {"field": "comments", "value": {"id": "c2", "text": "Lindo", "from": {"id": "u2"}}},
                    {"field": "mentions", "value": {"media_id": "m1"}},
                    {"field": "ratings", "value": {}},
                ],
                "messaging": [
                    {
                        "sender": {"id": "u3"},
                        "timestamp": 1795000002000,
                        "message": {"mid": "mid.1", "text": "Hola"},
                    },
                    {"sender": {"id": "u3"}, "message": {"mid": "mid.2", "is_deleted": True}},
                    {"sender": {"id": "u3"}, "read": {"watermark": 1}},
                ],
            },
            {"changes": []},
        ],
    }
    events = MetaWebhookParser(config()).parse(json.dumps(payload).encode())
    assert [(e.kind, e.action, e.object_external_id) for e in events] == [
        (EventKind.COMMENT, EventAction.CREATED, "c1"),
        (EventKind.POST, EventAction.UPDATED, "p1_9"),
        (EventKind.OTHER, EventAction.UNKNOWN, None),
        (EventKind.COMMENT, EventAction.CREATED, "c2"),
        (EventKind.MENTION, EventAction.CREATED, "m1"),
        (EventKind.OTHER, EventAction.UNKNOWN, None),
        (EventKind.MESSAGE, EventAction.CREATED, "mid.1"),
        (EventKind.MESSAGE, EventAction.DELETED, "mid.2"),
    ]
    comment = events[0]
    assert (comment.asset_external_id, comment.actor_id, comment.text) == ("p1", "u1", "Hola")
    assert comment.occurred_at == datetime.fromtimestamp(1795000001, UTC)
    assert events[2].occurred_at == datetime.fromtimestamp(1795000000, UTC)
    assert events[6].occurred_at == datetime.fromtimestamp(1795000002, UTC)


def test_un_cuerpo_que_no_es_json_no_produce_eventos() -> None:
    assert MetaWebhookParser(config()).parse(b"<html>") == []
