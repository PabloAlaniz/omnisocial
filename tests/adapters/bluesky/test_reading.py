"""Sesión, cuenta, posts, respuestas, contadores y perfiles de Bluesky, con una API falsa."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.bluesky.assets import BlueskyAssetDirectory
from omnisocial.adapters.providers.bluesky.client import BlueskyClient, iso, parse_time
from omnisocial.adapters.providers.bluesky.comments import BlueskyCommentGateway
from omnisocial.adapters.providers.bluesky.config import BLUESKY_ACCOUNT
from omnisocial.adapters.providers.bluesky.content import BlueskyContentReader
from omnisocial.adapters.providers.bluesky.insights import BlueskyInsightsReader
from omnisocial.adapters.providers.bluesky.profiles import BlueskyProfileLookup
from omnisocial.adapters.providers.bluesky.richtext import facets
from omnisocial.adapters.providers.bluesky.session import BlueskyIdentity, BlueskySession
from omnisocial.domain.content import CommentAction
from omnisocial.domain.errors import ErrorKind, ProviderError, RateLimited, TokenRejected
from omnisocial.domain.handles import Handle, HandleKind, Network, parse_handle
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.window import TimeWindow
from omnisocial.testing import FakeTransport
from tests.adapters.bluesky.conftest import (
    ACCOUNT,
    CREATE_RECORD,
    CREATE_SESSION,
    CREDENTIALS,
    DID,
    GET_SESSION,
    PUBLIC,
    SESSION,
    TOKEN,
    failure,
    jwt,
)
from tests.fakes import NOW

POST_URI = f"at://{DID}/app.bsky.feed.post/3kabc"
REPLY_URI = "at://did:plc:otra/app.bsky.feed.post/3kxyz"


# ── Cliente, errores y texto enriquecido ────────────────────────────────────────────────────────


def test_fechas() -> None:
    assert iso(datetime(2026, 11, 20, 7, tzinfo=UTC)) == "2026-11-20T07:00:00.000Z"
    assert parse_time("2026-11-20T07:00:00.000Z") == datetime(2026, 11, 20, 7, tzinfo=UTC)
    assert parse_time("2026-11-20T07:00:00") == datetime(2026, 11, 20, 7, tzinfo=UTC)
    assert parse_time("ayer") is None
    assert parse_time(None) is None


@pytest.mark.parametrize(
    ("response", "error", "kind"),
    [
        (failure("InvalidToken"), TokenRejected, None),
        (failure("AccountTakedown"), TokenRejected, None),
        (failure("InvalidRequest"), ProviderError, ErrorKind.INVALID_REQUEST),
        # Un token de acceso vencido se renueva: no invalida la conexión.
        (failure("ExpiredToken"), ProviderError, ErrorKind.UNKNOWN),
        (failure("AuthMissing", 401), ProviderError, ErrorKind.UNKNOWN),
        (HttpResponse(502, None, "bad gateway"), ProviderError, ErrorKind.TRANSIENT),
    ],
)
async def test_errores(
    transport: FakeTransport,
    client: BlueskyClient,
    response: HttpResponse,
    error: type[Exception],
    kind: ErrorKind | None,
) -> None:
    transport.on("GET", GET_SESSION, response)
    with pytest.raises(error) as raised:
        await client.get(GET_SESSION, TOKEN, {})
    assert type(raised.value) is error
    assert getattr(raised.value, "kind", None) is kind


async def test_el_limite_dice_cuando_vuelve_con_una_hora(
    transport: FakeTransport, client: BlueskyClient
) -> None:
    reset = str(int((NOW + timedelta(minutes=5)).timestamp()))
    transport.on("GET", GET_SESSION, failure("RateLimitExceeded", 429, **{"ratelimit-reset": reset}))
    with pytest.raises(RateLimited) as raised:
        await client.get(GET_SESSION, TOKEN, {})
    assert raised.value.retry_after == 300.0


def test_links_y_hashtags_se_marcan_por_bytes() -> None:
    text = "Año nuevo 🎉: mirá https://ejemplo.com/a#ancla. #novedad y #2026 no"
    marks = facets(text)
    encoded = text.encode()
    spans = []
    for mark in marks:
        index, features = mark["index"], mark["features"]
        assert isinstance(index, dict)
        assert isinstance(features, list)
        spans.append((encoded[index["byteStart"] : index["byteEnd"]].decode(), features[0]))
    assert spans == [
        # El punto final no es parte del link, y el `#` dentro de la URL no es un hashtag.
        (
            "https://ejemplo.com/a#ancla",
            {"$type": "app.bsky.richtext.facet#link", "uri": "https://ejemplo.com/a#ancla"},
        ),
        ("#novedad", {"$type": "app.bsky.richtext.facet#tag", "tag": "novedad"}),
    ]
    assert facets("sin nada que marcar") == []


# ── Sesión ──────────────────────────────────────────────────────────────────────────────────────


async def test_la_contraseña_de_aplicacion_se_cambia_por_una_sesion(
    transport: FakeTransport, client: BlueskyClient
) -> None:
    transport.on("POST", CREATE_SESSION, {**SESSION, "accessJwt": jwt(7200), "refreshJwt": "renovar-1"})
    session = BlueskySession(client)
    assert [(f.name, f.secret, f.required) for f in session.fields] == [
        ("identifier", False, True),
        ("password", True, True),
        ("server", False, False),
    ]
    token = await session.login(CREDENTIALS)
    assert (token.refresh_token, token.server) == ("renovar-1", "bsky.social")
    # El vencimiento sale del token mismo.
    assert token.expires_at == NOW + timedelta(hours=2)
    call = transport.calls[0]
    assert call.json == {"identifier": "ana.bsky.social", "password": "abcd-efgh-ijkl-mnop"}
    assert call.headers is None


async def test_un_servidor_propio_y_un_token_que_no_dice_cuando_vence(client: BlueskyClient) -> None:
    transport = FakeTransport()
    own = BlueskyClient(client.config, transport, client.clock)
    transport.on(
        "POST", f"https://pds.ejemplo.com/xrpc/{CREATE_SESSION}", {"accessJwt": "opaco", "refreshJwt": "r"}
    )
    token = await BlueskySession(own).login({**CREDENTIALS, "server": "https://PDS.ejemplo.com/"})
    assert (token.server, token.expires_at) == ("pds.ejemplo.com", NOW + timedelta(hours=2))
    with pytest.raises(TokenRejected, match="servidor"):
        await BlueskySession(own).login({**CREDENTIALS, "server": "localhost"})
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("response", "error", "match"),
    [
        (
            failure("AuthenticationRequired", 401, "Invalid identifier or password"),
            TokenRejected,
            "Invalid identifier",
        ),
        # Con el código por mail activado, la contraseña de la cuenta no sirve: hace falta una de aplicación.
        (failure("AuthFactorTokenRequired", 401), TokenRejected, "contraseña de aplicación"),
        (HttpResponse(401, None, ""), TokenRejected, "credencial inválida"),
        (failure("RateLimitExceeded", 429), RateLimited, "no"),
        (HttpResponse(200, {"did": DID}, ""), ProviderError, "sesión"),
    ],
)
async def test_credenciales_que_no_sirven(
    transport: FakeTransport,
    client: BlueskyClient,
    response: HttpResponse,
    error: type[Exception],
    match: str,
) -> None:
    transport.on("POST", CREATE_SESSION, response)
    with pytest.raises(error, match=match) as raised:
        await BlueskySession(client).login(CREDENTIALS)
    assert type(raised.value) is error


async def test_renovar_rota_el_token_y_cerrar_sesion_usa_el_de_renovacion(
    transport: FakeTransport, client: BlueskyClient
) -> None:
    session = BlueskySession(client)
    transport.on(
        "POST", "com.atproto.server.refreshSession", {"accessJwt": jwt(7200), "refreshJwt": "renovar-2"}
    )
    transport.on("POST", "com.atproto.server.deleteSession", HttpResponse(200, None, ""))
    assert session.can_refresh(TOKEN)
    fresh = await session.refresh(TOKEN)
    assert (fresh.refresh_token, fresh.server) == ("renovar-2", "bsky.social")
    assert transport.calls[0].headers == {"Authorization": "Bearer renovar-1"}
    await session.revoke(fresh)
    assert transport.calls[1].headers == {"Authorization": "Bearer renovar-2"}

    bare = Token(TokenKind.USER, "x")
    assert not session.can_refresh(bare)
    await session.revoke(bare)
    with pytest.raises(ProviderError, match="renovarse"):
        await session.refresh(bare)
    assert len(transport.calls) == 2
    transport.routes.clear()
    transport.on("POST", "com.atproto.server.refreshSession", failure("ExpiredToken"))
    with pytest.raises(TokenRejected):
        await session.refresh(TOKEN)


async def test_la_identidad_es_el_did(transport: FakeTransport, client: BlueskyClient) -> None:
    transport.on("GET", GET_SESSION, SESSION, {"handle": "sin-did"})
    identity = await BlueskyIdentity(client).identity(TOKEN)
    assert (identity.external_id, identity.name, identity.email) == (
        DID,
        "ana.bsky.social",
        "ana@ejemplo.com",
    )
    assert transport.calls[0].headers == {"Authorization": "Bearer acceso-1"}
    with pytest.raises(ProviderError, match="DID"):
        await BlueskyAssetDirectory(client).discover(TOKEN)
    transport.routes.clear()
    transport.on("GET", GET_SESSION, SESSION)
    [asset] = await BlueskyAssetDirectory(client).discover(TOKEN)
    assert (asset.kind, asset.external_id, asset.metadata) == (
        BLUESKY_ACCOUNT,
        DID,
        {"handle": "ana.bsky.social"},
    )


# ── Posts ───────────────────────────────────────────────────────────────────────────────────────


def _item(number: int, day: int, **extra: object) -> dict[str, object]:
    view = {
        "uri": f"at://{DID}/app.bsky.feed.post/3k{number}",
        "cid": f"cid-{number}",
        "author": {"did": DID, "handle": "ana.bsky.social"},
        "record": {"text": f"Post {number}", "createdAt": f"2026-11-{day:02d}T10:00:00.000Z"},
        "likeCount": 5,
        "replyCount": 2,
        "repostCount": 1,
    }
    return {"post": view, **extra}


async def test_los_posts_propios_sin_reposts(transport: FakeTransport, client: BlueskyClient) -> None:
    first = {
        "feed": [
            _item(4, 22),
            _item(3, 20, reason={"$type": "app.bsky.feed.defs#reasonRepost"}),
            _item(2, 19),
        ],
        "cursor": "c2",
    }
    second = {"feed": [_item(1, 10), {"post": {}}], "cursor": "c3"}
    transport.on("GET", "app.bsky.feed.getAuthorFeed", first, second)
    window = TimeWindow(datetime(2026, 11, 15, tzinfo=UTC), datetime(2026, 11, 21, tzinfo=UTC))
    posts = await BlueskyContentReader(client).list_posts(ACCOUNT, TOKEN, window=window, limit=None)
    [post] = posts
    assert (post.external_id, post.text) == (f"at://{DID}/app.bsky.feed.post/3k2", "Post 2")
    assert post.permalink == f"https://bsky.app/profile/{DID}/post/3k2"
    assert (post.like_count, post.comment_count, post.share_count, post.media_type) == (5, 2, 1, "text")
    assert transport.calls[0].params == {"actor": DID, "limit": 50, "filter": "posts_no_replies"}
    assert transport.calls[1].params["cursor"] == "c2"
    # El post del día 10 quedó antes de la ventana: no se pide otra página.
    assert len(transport.calls) == 2


async def test_el_tope_de_posts(transport: FakeTransport, client: BlueskyClient) -> None:
    transport.on("GET", "app.bsky.feed.getAuthorFeed", {"feed": [_item(4, 22), _item(2, 19)]})
    posts = await BlueskyContentReader(client).list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=1)
    assert len(posts) == 1


# ── Respuestas ──────────────────────────────────────────────────────────────────────────────────


async def test_leer_respuestas(transport: FakeTransport, client: BlueskyClient) -> None:
    reply = {
        "uri": REPLY_URI,
        "cid": "cid-r",
        "author": {"did": "did:plc:otra", "handle": "luis.bsky.social"},
        "record": {"text": "¡Genial!", "createdAt": "2026-11-20T11:00:00.000Z"},
        "likeCount": 3,
        "replyCount": 0,
    }
    own = {"uri": f"at://{DID}/app.bsky.feed.post/3kd", "author": {"did": DID}, "record": {"text": "sigue…"}}
    thread = {
        "thread": {"post": {"uri": POST_URI}, "replies": [{"post": reply}, {"post": own}, {"notFound": True}]}
    }
    transport.on("GET", "app.bsky.feed.getPostThread", thread)
    [comment] = await BlueskyCommentGateway(client).list_comments(ACCOUNT, TOKEN, object_id=POST_URI)
    assert (comment.external_id, comment.object_external_id, comment.text) == (
        REPLY_URI,
        POST_URI,
        "¡Genial!",
    )
    assert (comment.author_id, comment.author_name, comment.like_count) == (
        "did:plc:otra",
        "luis.bsky.social",
        3,
    )
    assert transport.calls[0].params == {"uri": POST_URI, "depth": 1}


async def test_responder_y_dar_like_piden_antes_el_contenido_del_post(
    transport: FakeTransport, client: BlueskyClient
) -> None:
    gateway = BlueskyCommentGateway(client)
    root = {"uri": POST_URI, "cid": "cid-raiz"}
    parent = {
        "uri": REPLY_URI,
        "cid": "cid-r",
        "record": {"text": "¡Genial!", "reply": {"root": root, "parent": root}},
    }
    transport.on("GET", "app.bsky.feed.getPosts", {"posts": [parent]})
    transport.on(
        "POST",
        CREATE_RECORD,
        {"uri": "at://x/app.bsky.feed.post/3knew", "cid": "c"},
        {"uri": "at://x/app.bsky.feed.like/3kl"},
        {},
    )
    created = await gateway.reply(ACCOUNT, TOKEN, comment_id=REPLY_URI, text="¡Gracias! #equipo")
    assert created == "at://x/app.bsky.feed.post/3knew"
    body = transport.calls[1].json
    assert body is not None
    assert (body["repo"], body["collection"]) == (DID, "app.bsky.feed.post")
    record = body["record"]
    assert isinstance(record, dict)
    # La raíz es la del hilo, no la respuesta a la que se contesta.
    assert record["reply"] == {"root": root, "parent": {"uri": REPLY_URI, "cid": "cid-r"}}
    assert (record["text"], record["createdAt"], len(record["facets"])) == ("¡Gracias! #equipo", iso(NOW), 1)

    await gateway.like(ACCOUNT, TOKEN, comment_id=REPLY_URI)
    like = transport.calls[3].json
    assert like is not None
    liked = like["record"]
    assert isinstance(liked, dict)
    assert (like["collection"], liked["subject"]) == (
        "app.bsky.feed.like",
        {"uri": REPLY_URI, "cid": "cid-r"},
    )
    with pytest.raises(ProviderError, match="dirección"):
        await gateway.like(ACCOUNT, TOKEN, comment_id=REPLY_URI)
    transport.routes[("GET", "app.bsky.feed.getPosts")] = [HttpResponse(200, {"posts": []}, "")]
    with pytest.raises(ProviderError, match="ya no existe"):
        await gateway.reply(ACCOUNT, TOKEN, comment_id=REPLY_URI, text="hola")


async def test_lo_que_no_se_ofrece_en_respuestas(client: BlueskyClient) -> None:
    gateway = BlueskyCommentGateway(client)
    assert gateway.supports(ACCOUNT, CommentAction.REPLY)
    assert gateway.supports(ACCOUNT, CommentAction.LIKE)
    assert not gateway.supports(ACCOUNT, CommentAction.HIDE)
    assert not gateway.supports(ACCOUNT, CommentAction.DELETE)
    with pytest.raises(ProviderError, match="Ocultar"):
        await gateway.set_hidden(ACCOUNT, TOKEN, comment_id=REPLY_URI, hidden=True)
    with pytest.raises(ProviderError, match="borrar"):
        await gateway.delete(ACCOUNT, TOKEN, comment_id=REPLY_URI)


# ── Contadores y perfiles ───────────────────────────────────────────────────────────────────────

PROFILE = {
    "did": DID,
    "handle": "ana.bsky.social",
    "displayName": "Ana",
    "description": "Hago cosas",
    "avatar": "https://cdn.bsky.app/a.jpg",
    "followersCount": 1200,
    "followsCount": 80,
    "postsCount": 340,
}


async def test_los_contadores_de_la_cuenta(transport: FakeTransport, client: BlueskyClient) -> None:
    reader = BlueskyInsightsReader(client)
    transport.on("GET", "app.bsky.actor.getProfile", PROFILE)
    series = await reader.read(
        ACCOUNT,
        TOKEN,
        metrics=["followersCount", "postsCount", "inventada"],
        period=Period.DAY,
        window=TimeWindow(),
    )
    assert [(s.name, s.period, s.points[0].value) for s in series] == [
        ("followersCount", Period.LIFETIME, 1200.0),
        ("postsCount", Period.LIFETIME, 340.0),
    ]
    assert (
        reader.catalog.native_for(BLUESKY_ACCOUNT, CanonicalMetric.FOLLOWERS, reader.api_version)
        == "followersCount"
    )
    assert (
        await reader.read(ACCOUNT, TOKEN, metrics=["inventada"], period=Period.DAY, window=TimeWindow()) == []
    )
    assert len(transport.calls) == 1


async def test_perfil_publico_sin_que_nadie_conecte(transport: FakeTransport, client: BlueskyClient) -> None:
    lookup = BlueskyProfileLookup(client)
    assert lookup.networks == frozenset({Network.BLUESKY})
    assert lookup.viewer_kinds(Network.BLUESKY) == frozenset()
    url = f"{PUBLIC}app.bsky.actor.getProfile"
    transport.on(
        "GET", url, PROFILE, failure("InvalidRequest", message="Profile not found"), {"handle": "sin-did"}
    )
    handle = parse_handle(Network.BLUESKY, "https://bsky.app/profile/ana.bsky.social")
    assert handle is not None
    profile = await lookup.lookup(handle, viewer=None, token=None)
    assert profile is not None
    assert (profile.external_id, profile.username, profile.name, profile.followers, profile.posts) == (
        DID,
        "ana.bsky.social",
        "Ana",
        1200,
        340,
    )
    assert profile.url == "https://bsky.app/profile/ana.bsky.social"
    assert (transport.calls[0].params, transport.calls[0].headers) == ({"actor": "ana.bsky.social"}, None)
    # Una cuenta que no existe responde 400.
    assert await lookup.lookup(Handle(Network.BLUESKY, "nadie.bsky.social"), viewer=None, token=None) is None
    assert await lookup.lookup(Handle(Network.BLUESKY, DID, HandleKind.ID), viewer=None, token=None) is None
    transport.routes.clear()
    transport.on("GET", url, failure("RateLimitExceeded", 429))
    with pytest.raises(RateLimited):
        await lookup.lookup(Handle(Network.BLUESKY, "ana.bsky.social"), viewer=None, token=None)
