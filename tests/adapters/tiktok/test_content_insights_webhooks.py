from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from omniwebhook import IncomingRequest, Rejected, Verified

from omnisocial.adapters.providers.tiktok.client import TikTokClient
from omnisocial.adapters.providers.tiktok.config import TIKTOK, TIKTOK_ACCOUNT
from omnisocial.adapters.providers.tiktok.content import TikTokContentReader
from omnisocial.adapters.providers.tiktok.insights import TikTokInsightsReader
from omnisocial.adapters.providers.tiktok.webhooks import TikTokWebhookParser
from omnisocial.domain.asset import Asset
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.webhooks import EventAction, EventKind
from omnisocial.domain.window import TimeWindow
from tests.adapters.tiktok.conftest import FakeTikTok, config, ok
from tests.fakes import NOW, FakeClock

ACCOUNT = Asset("a1", "c1", TIKTOK, "dueño", TIKTOK_ACCOUNT, "oid-1")
TOKEN = Token(TokenKind.USER, "act")


def video(video_id: str, hours_ago: int, **extra: object) -> dict[str, object]:
    return {"id": video_id, "create_time": int((NOW - timedelta(hours=hours_ago)).timestamp()), **extra}


async def test_videos_en_la_ventana(fake: FakeTikTok, client: TikTokClient) -> None:
    fake.on(
        "POST",
        "video/list/",
        ok(
            {
                "videos": [
                    video(
                        "v1",
                        1,
                        view_count=100,
                        like_count=5,
                        share_count=2,
                        comment_count=1,
                        video_description="hola",
                        share_url="https://tiktok/v1",
                        cover_image_url="c",
                    ),
                    {"title": "sin id"},
                    video("v2", 30, title="solo título"),
                ],
                "cursor": 111,
                "has_more": True,
            }
        ),
        ok({"videos": [video("v3", 50), video("v4", 100)], "cursor": 222, "has_more": True}),
    )
    window = TimeWindow(NOW - timedelta(hours=72), NOW)
    posts = await TikTokContentReader(client).list_posts(ACCOUNT, TOKEN, window=window, limit=None)
    assert [p.external_id for p in posts] == ["v1", "v2", "v3"]
    first = posts[0]
    assert (first.view_count, first.like_count, first.share_count, first.comment_count) == (100, 5, 2, 1)
    assert (first.text, first.permalink, first.media_url) == ("hola", "https://tiktok/v1", "c")
    assert posts[1].text == "solo título"
    # Arranca desde el final de la ventana y sigue con el cursor que devuelve TikTok; `fields` va en la query.
    assert fake.calls[0].json == {"max_count": 20, "cursor": int(NOW.timestamp() * 1000)}
    assert fake.calls[1].json == {"max_count": 20, "cursor": 111}
    assert "view_count" in str(fake.calls[0].params["fields"])
    assert len(fake.calls) == 2  # v4 quedó antes de la ventana: no se pide otra página


async def test_tope_y_fin_de_la_lista(fake: FakeTikTok, client: TikTokClient) -> None:
    fake.on("POST", "video/list/", ok({"videos": [video("v1", 1), video("v2", 2)], "has_more": False}))
    reader = TikTokContentReader(client)
    assert len(await reader.list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=1)) == 1
    assert len(await reader.list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=None)) == 2
    assert "cursor" not in (fake.calls[0].json or {})
    recent = TimeWindow(NOW - timedelta(minutes=10), NOW)
    assert await reader.list_posts(ACCOUNT, TOKEN, window=recent, limit=None) == []


async def test_contadores_de_la_cuenta(fake: FakeTikTok, client: TikTokClient, clock: FakeClock) -> None:
    fake.on("GET", "user/info/", ok({"user": {"follower_count": 1500, "video_count": 40}}))
    reader = TikTokInsightsReader(client, clock)
    series = await reader.read(
        ACCOUNT,
        TOKEN,
        metrics=["follower_count", "video_count", "likes_count", "no_existe"],
        period=Period.DAY,
        window=TimeWindow(),
    )
    assert [(s.name, s.period, s.points[0].value, s.points[0].end_time) for s in series] == [
        ("follower_count", Period.LIFETIME, 1500.0, NOW),
        ("video_count", Period.LIFETIME, 40.0, NOW),
    ]
    assert fake.calls[0].params == {"fields": "follower_count,likes_count,video_count"}
    assert (
        await reader.read(ACCOUNT, TOKEN, metrics=["no_existe"], period=Period.DAY, window=TimeWindow()) == []
    )
    assert reader.api_version == "v2"
    assert reader.catalog.native_for(TIKTOK_ACCOUNT, CanonicalMetric.FOLLOWERS, "v2") == "follower_count"


# ── Webhooks ────────────────────────────────────────────────────────────────────────────────────


def signed(body: bytes, *, secret: str = "secreto", at: int | None = None) -> IncomingRequest:
    timestamp = str(at if at is not None else int(NOW.timestamp()))
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return IncomingRequest(
        headers=[("TikTok-Signature", f"t={timestamp},s={signature}")], query=[], body=body
    )


REMOVED = json.dumps(
    {
        "client_key": "clave",
        "event": "authorization.removed",
        "create_time": int(NOW.timestamp()),
        "user_openid": "oid-1",
        "content": json.dumps({"reason": 1}),
    }
).encode()


def test_firma_valida_y_clave_por_cuerpo(clock: FakeClock) -> None:
    verifier = TikTokWebhookParser(config(), clock).verifier
    verified = verifier.verify(signed(REMOVED))
    assert isinstance(verified, Verified)
    assert verified.timestamp == int(NOW.timestamp())
    assert verified.event_key == f"tiktok:sha256:{hashlib.sha256(REMOVED).hexdigest()}"


def test_secreto_anterior_mientras_se_rota(clock: FakeClock) -> None:
    parser = TikTokWebhookParser(config(client_secret="nuevo", previous_client_secrets=("viejo",)), clock)
    assert isinstance(parser.verifier.verify(signed(REMOVED, secret="viejo")), Verified)


@pytest.mark.parametrize(
    ("request_", "outcome"),
    [
        (IncomingRequest(headers=[], query=[], body=REMOVED), "missing"),
        (IncomingRequest(headers=[("tiktok-signature", "t=1,s=a")] * 2, query=[], body=REMOVED), "ambiguous"),
        (IncomingRequest(headers=[("tiktok-signature", "s=abc")], query=[], body=REMOVED), "malformed"),
        (
            IncomingRequest(headers=[("tiktok-signature", "t=ayer,s=abc")], query=[], body=REMOVED),
            "malformed",
        ),
        (IncomingRequest(headers=[("tiktok-signature", "basura")], query=[], body=REMOVED), "malformed"),
        (signed(REMOVED, secret="otro"), "invalid"),
        (signed(REMOVED, at=int(NOW.timestamp()) - 3600), "stale"),
    ],
)
def test_rechazos(clock: FakeClock, request_: IncomingRequest, outcome: str) -> None:
    assert TikTokWebhookParser(config(), clock).verifier.verify(request_) == Rejected(outcome)  # type: ignore[arg-type]


def test_sin_secreto(clock: FakeClock) -> None:
    parser = TikTokWebhookParser(config(client_secret=""), clock)
    assert parser.verifier.verify(signed(REMOVED)) == Rejected("unconfigured")
    assert parser.handshake({"hub.challenge": "x"}) is None


def test_traduce_los_avisos(clock: FakeClock) -> None:
    parser = TikTokWebhookParser(config(), clock)
    [removed] = parser.parse(REMOVED)
    assert (removed.kind, removed.action, removed.asset_external_id) == (
        EventKind.AUTHORIZATION,
        EventAction.DELETED,
        "oid-1",
    )
    assert removed.occurred_at == NOW
    assert removed.raw["content"] == {"reason": 1}
    published = json.dumps(
        {"event": "video.publish.completed", "user_openid": "oid-1", "content": '{"share_id": "sh1"}'}
    ).encode()
    [post] = parser.parse(published)
    assert (post.kind, post.action, post.object_external_id, post.occurred_at) == (
        EventKind.POST,
        EventAction.CREATED,
        "sh1",
        None,
    )
    unknown = json.dumps({"event": "algo.nuevo", "user_openid": "oid-1", "content": "{roto"}).encode()
    [other] = parser.parse(unknown)
    assert (other.kind, other.raw["content"]) == (EventKind.OTHER, {})
    assert parser.parse(b"no es json") == []
    assert parser.parse(json.dumps({"event": "x"}).encode()) == []
