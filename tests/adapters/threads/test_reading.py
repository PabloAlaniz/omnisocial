"""Login, cuenta, posts, respuestas y métricas de Threads, con una API falsa."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.threads.assets import ThreadsAssetDirectory
from omnisocial.adapters.providers.threads.client import ThreadsClient, as_str, parse_time
from omnisocial.adapters.providers.threads.comments import ThreadsCommentGateway
from omnisocial.adapters.providers.threads.config import THREADS_ACCOUNT
from omnisocial.adapters.providers.threads.content import ThreadsContentReader
from omnisocial.adapters.providers.threads.insights import ThreadsInsightsReader
from omnisocial.adapters.providers.threads.oauth import ThreadsOAuth
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.content import CommentAction
from omnisocial.domain.errors import ErrorKind, PermissionMissing, ProviderError, RateLimited, TokenRejected
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.window import TimeWindow
from omnisocial.testing import FakeTransport
from tests.adapters.threads.conftest import (
    ACCOUNT,
    LONG_TOKEN_URL,
    ME,
    REFRESH_URL,
    SHORT_TOKEN_URL,
    TOKEN,
    config,
    failure,
)
from tests.fakes import NOW, FakeClock

# ── Cliente y errores ───────────────────────────────────────────────────────────────────────────


def test_valores_de_la_api() -> None:
    assert parse_time("2026-11-20T10:00:00+0000") == datetime(2026, 11, 20, 10, tzinfo=UTC)
    assert parse_time("2026-11-20T10:00:00") == datetime(2026, 11, 20, 10, tzinfo=UTC)
    assert parse_time("ayer") is None
    assert parse_time(None) is None
    assert (as_str(17841400000), as_str(""), as_str(True)) == ("17841400000", None, None)
    assert "secreto" not in repr(config())


@pytest.mark.parametrize(
    ("response", "error", "kind"),
    [
        (failure(190, status=401), TokenRejected, None),
        (failure(10, status=403), PermissionMissing, ErrorKind.MISSING_PERMISSION),
        (failure(200, status=403), PermissionMissing, ErrorKind.MISSING_PERMISSION),
        (failure(4), RateLimited, ErrorKind.RATE_LIMITED),
        (failure(100), ProviderError, ErrorKind.INVALID_REQUEST),
        # Un error con 200 también es un error; un 401 sin código conocido no invalida la conexión.
        (failure(2, status=200), ProviderError, ErrorKind.TRANSIENT),
        (HttpResponse(401, {"error": {"message": "raro"}}, ""), ProviderError, ErrorKind.UNKNOWN),
        (HttpResponse(502, None, "bad gateway"), ProviderError, ErrorKind.TRANSIENT),
    ],
)
async def test_errores(
    transport: FakeTransport,
    client: ThreadsClient,
    response: HttpResponse,
    error: type[Exception],
    kind: ErrorKind | None,
) -> None:
    transport.on("GET", "me", response)
    with pytest.raises(error) as raised:
        await client.get("me", "tok")
    assert type(raised.value) is error
    assert getattr(raised.value, "kind", None) is kind


# ── Login ───────────────────────────────────────────────────────────────────────────────────────


def test_la_url_de_autorizacion(client: ThreadsClient) -> None:
    oauth = ThreadsOAuth(client, FakeClock())
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://api/cb",
        scopes=oauth.default_scopes(Purpose.CONNECT),
        code_challenge="d",
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://threads.com/oauth/authorize?")
    assert query["scope"] == ["threads_basic,threads_read_replies,threads_manage_insights"]
    assert (query["client_id"], query["state"], query["response_type"]) == (["app"], ["s"], ["code"])
    assert "code_challenge" not in query
    assert oauth.default_scopes(Purpose.LOGIN) == ("threads_basic",)


async def test_el_codigo_se_canjea_por_un_token_corto_y_ese_por_uno_largo(
    transport: FakeTransport, client: ThreadsClient
) -> None:
    transport.on("POST", SHORT_TOKEN_URL, {"access_token": "THQ-corto", "user_id": 1})
    transport.on(
        "GET", LONG_TOKEN_URL, {"access_token": "THQ-largo", "token_type": "bearer", "expires_in": 5184000}
    )
    token = await ThreadsOAuth(client, FakeClock()).exchange_code(
        code="c", redirect_uri="https://api/cb", code_verifier=None
    )
    assert (token.access_token, token.refresh_token) == ("THQ-largo", None)
    assert token.expires_at == NOW + timedelta(days=60)
    short, long = transport.calls
    assert short.form == {
        "client_id": "app",
        "client_secret": "secreto",
        "grant_type": "authorization_code",
        "redirect_uri": "https://api/cb",
        "code": "c",
    }
    assert long.params == {
        "grant_type": "th_exchange_token",
        "client_secret": "secreto",
        "access_token": "THQ-corto",
    }


async def test_canjes_sin_token(transport: FakeTransport, client: ThreadsClient) -> None:
    oauth = ThreadsOAuth(client, FakeClock())
    transport.on("POST", SHORT_TOKEN_URL, {"user_id": 1})
    with pytest.raises(ProviderError, match="token"):
        await oauth.exchange_code(code="c", redirect_uri="r", code_verifier=None)
    transport.routes.clear()
    transport.on("POST", SHORT_TOKEN_URL, {"access_token": "THQ-corto"})
    transport.on("GET", LONG_TOKEN_URL, {})
    with pytest.raises(ProviderError, match="token"):
        await oauth.exchange_code(code="c", redirect_uri="r", code_verifier=None)
    transport.routes.clear()
    transport.on("POST", SHORT_TOKEN_URL, failure(100, "código inválido"))
    with pytest.raises(ProviderError, match="código inválido"):
        await oauth.exchange_code(code="c", redirect_uri="r", code_verifier=None)


async def test_se_renueva_el_mismo_token_y_solo_si_tiene_mas_de_un_dia(
    transport: FakeTransport, client: ThreadsClient
) -> None:
    clock = FakeClock()
    oauth = ThreadsOAuth(client, clock)
    fresh = Token(TokenKind.USER, "THQ-largo", expires_at=clock.now() + timedelta(days=60))
    # Recién emitido no se puede renovar; sin vencimiento, tampoco.
    assert not oauth.can_refresh(fresh)
    assert not oauth.can_refresh(Token(TokenKind.USER, "x"))
    clock.advance(timedelta(hours=25))
    assert oauth.can_refresh(fresh)
    transport.on("GET", REFRESH_URL, {"access_token": "THQ-nuevo", "expires_in": 5184000})
    renewed = await oauth.refresh(fresh)
    assert (renewed.access_token, renewed.expires_at) == ("THQ-nuevo", clock.now() + timedelta(days=60))
    assert transport.calls[0].params == {"grant_type": "th_refresh_token", "access_token": "THQ-largo"}
    # Vencido ya no se recupera: hay que volver a autorizar.
    clock.advance(timedelta(days=60))
    assert not oauth.can_refresh(fresh)
    await oauth.revoke(fresh)
    assert len(transport.calls) == 1


async def test_la_identidad_y_el_activo_son_la_cuenta(
    transport: FakeTransport, client: ThreadsClient
) -> None:
    transport.on("GET", "me", ME, {"username": "sin-id"})
    identity = await ThreadsOAuth(client, FakeClock()).identity(TOKEN)
    assert (identity.external_id, identity.name, identity.avatar_url) == (
        "17841400000",
        "Mi Marca",
        "https://scontent/a.jpg",
    )
    assert transport.calls[0].params["access_token"] == "THQ-largo"
    with pytest.raises(ProviderError, match="id de la cuenta"):
        await ThreadsAssetDirectory(client).discover(TOKEN)
    transport.routes.clear()
    transport.on("GET", "me", ME)
    [asset] = await ThreadsAssetDirectory(client).discover(TOKEN)
    assert (asset.kind, asset.external_id, asset.name, asset.metadata) == (
        THREADS_ACCOUNT,
        "17841400000",
        "Mi Marca",
        {"username": "mimarca"},
    )


# ── Posts ───────────────────────────────────────────────────────────────────────────────────────


def _post(post_id: str) -> dict[str, object]:
    return {
        "id": post_id,
        "text": f"Post {post_id}",
        "timestamp": "2026-11-20T10:00:00+0000",
        "permalink": f"https://www.threads.com/@mimarca/post/{post_id}",
        "media_type": "TEXT_POST",
    }


async def test_los_posts_de_la_cuenta(transport: FakeTransport, client: ThreadsClient) -> None:
    first = {"data": [_post("3"), {"text": "sin id"}], "paging": {"cursors": {"after": "cur-2"}}}
    transport.on(
        "GET",
        "17841400000/threads",
        first,
        {"data": [_post("2")], "paging": {"cursors": {"after": "cur-3"}}},
        {"data": []},
    )
    window = TimeWindow(datetime(2026, 11, 15, tzinfo=UTC), datetime(2026, 11, 21, tzinfo=UTC))
    posts = await ThreadsContentReader(client).list_posts(ACCOUNT, TOKEN, window=window, limit=None)
    assert [post.external_id for post in posts] == ["3", "2"]
    assert transport.calls[0].params["since"] == int(window.since.timestamp())  # type: ignore[union-attr]
    assert transport.calls[0].params["until"] == int(window.until.timestamp())  # type: ignore[union-attr]
    assert transport.calls[1].params["after"] == "cur-2"
    post = posts[0]
    assert (post.text, post.permalink, post.media_type) == (
        "Post 3",
        "https://www.threads.com/@mimarca/post/3",
        "TEXT_POST",
    )
    assert post.created_at == datetime(2026, 11, 20, 10, tzinfo=UTC)
    # Los contadores están en las métricas de cada post: acá no vienen, y eso no es cero.
    assert post.like_count is None


async def test_el_tope_de_posts(transport: FakeTransport, client: ThreadsClient) -> None:
    transport.on("GET", "17841400000/threads", {"data": [_post("3"), _post("2")]})
    posts = await ThreadsContentReader(client).list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=1)
    assert [post.external_id for post in posts] == ["3"]
    assert "since" not in transport.calls[0].params


# ── Respuestas ──────────────────────────────────────────────────────────────────────────────────


async def test_leer_respuestas(transport: FakeTransport, client: ThreadsClient) -> None:
    replies = {
        "data": [
            {
                "id": "11",
                "text": "¡Genial!",
                "username": "ana",
                "timestamp": "2026-11-20T11:00:00+0000",
                "hide_status": "NOT_HUSHED",
            },
            {"id": "12", "text": "spam", "username": "bot", "hide_status": "HIDDEN"},
            # La segunda parte del hilo es de la propia cuenta: no es un comentario.
            {"id": "13", "text": "sigue…", "username": "mimarca", "is_reply_owned_by_me": True},
        ]
    }
    transport.on("GET", "10/replies", replies)
    first, hidden = await ThreadsCommentGateway(client).list_comments(ACCOUNT, TOKEN, object_id="10")
    assert (first.external_id, first.object_external_id, first.text, first.author_name) == (
        "11",
        "10",
        "¡Genial!",
        "ana",
    )
    # Threads identifica al autor por su nombre: no da un id.
    assert (first.author_id, first.hidden, hidden.hidden) == (None, False, True)
    assert transport.calls[0].params["reverse"] == "false"


async def test_responder_y_ocultar(transport: FakeTransport, client: ThreadsClient) -> None:
    gateway = ThreadsCommentGateway(client)
    transport.on("POST", "17841400000/threads", {"id": "20"}, {})
    assert await gateway.reply(ACCOUNT, TOKEN, comment_id="11", text="¡Gracias!") == "20"
    # Una respuesta de texto sale en un solo paso.
    assert transport.calls[0].form == {
        "media_type": "TEXT",
        "text": "¡Gracias!",
        "reply_to_id": "11",
        "auto_publish_text": "true",
        "access_token": "THQ-largo",
    }
    with pytest.raises(ProviderError, match="id de la respuesta"):
        await gateway.reply(ACCOUNT, TOKEN, comment_id="11", text="otra")
    transport.on("POST", "11/manage_reply", {"success": True})
    await gateway.set_hidden(ACCOUNT, TOKEN, comment_id="11", hidden=True)
    await gateway.set_hidden(ACCOUNT, TOKEN, comment_id="11", hidden=False)
    assert [call.form["hide"] for call in transport.calls[2:]] == ["true", "false"]  # type: ignore[index]


async def test_lo_que_threads_no_ofrece_en_respuestas(client: ThreadsClient) -> None:
    gateway = ThreadsCommentGateway(client)
    assert gateway.supports(ACCOUNT, CommentAction.REPLY)
    assert gateway.supports(ACCOUNT, CommentAction.HIDE)
    assert not gateway.supports(ACCOUNT, CommentAction.DELETE)
    assert not gateway.supports(ACCOUNT, CommentAction.LIKE)
    with pytest.raises(ProviderError, match="ocultar"):
        await gateway.delete(ACCOUNT, TOKEN, comment_id="11")
    with pytest.raises(ProviderError, match="like"):
        await gateway.like(ACCOUNT, TOKEN, comment_id="11")


# ── Métricas ────────────────────────────────────────────────────────────────────────────────────


async def test_metricas_de_la_cuenta(transport: FakeTransport, client: ThreadsClient) -> None:
    reader = ThreadsInsightsReader(client, FakeClock())
    followers = {"data": [{"name": "followers_count", "period": "day", "total_value": {"value": 4100}}]}
    windowed = {
        "data": [
            {
                "name": "views",
                "period": "day",
                "values": [
                    {"value": 30, "end_time": "2026-11-20T08:00:00+0000"},
                    {"value": 45, "end_time": "2026-11-21T08:00:00+0000"},
                    {"end_time": "2026-11-22T08:00:00+0000"},
                ],
            },
            {"name": "likes", "period": "day", "total_value": {"value": 12}},
            {"name": "replies", "period": "day", "values": []},
            {"period": "day"},
        ]
    }
    transport.on("GET", "17841400000/threads_insights", followers, windowed)
    window = TimeWindow(datetime(2026, 11, 19, tzinfo=UTC), datetime(2026, 11, 22, tzinfo=UTC))
    series = await reader.read(
        ACCOUNT,
        TOKEN,
        metrics=["followers_count", "views", "likes", "replies", "inventada"],
        period=Period.DAY,
        window=window,
    )
    assert [(s.name, s.period, [p.value for p in s.points]) for s in series] == [
        ("followers_count", Period.LIFETIME, [4100.0]),
        ("views", Period.DAY, [30.0, 45.0]),
        ("likes", Period.LIFETIME, [12.0]),
    ]
    assert series[1].points[0].end_time == datetime(2026, 11, 20, 8, tzinfo=UTC)
    # Los seguidores no aceptan ventana: se piden aparte.
    assert transport.calls[0].params == {"metric": "followers_count", "access_token": "THQ-largo"}
    assert transport.calls[1].params == {
        "metric": "views,likes,replies",
        "since": int(window.since.timestamp()),  # type: ignore[union-attr]
        "until": int(window.until.timestamp()),  # type: ignore[union-attr]
        "access_token": "THQ-largo",
    }
    assert (
        reader.catalog.native_for(THREADS_ACCOUNT, CanonicalMetric.FOLLOWERS, reader.api_version)
        == "followers_count"
    )
    assert (
        await reader.read(ACCOUNT, TOKEN, metrics=["inventada"], period=Period.DAY, window=TimeWindow()) == []
    )
    assert len(transport.calls) == 2
