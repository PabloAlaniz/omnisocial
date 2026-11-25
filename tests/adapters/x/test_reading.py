"""Login, cuenta, posts, respuestas, contadores y perfiles públicos, con una API falsa."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.x.assets import XAssetDirectory
from omnisocial.adapters.providers.x.client import XClient, iso, parse_time
from omnisocial.adapters.providers.x.comments import XCommentGateway
from omnisocial.adapters.providers.x.config import X_ACCOUNT, XConfig
from omnisocial.adapters.providers.x.content import XContentReader
from omnisocial.adapters.providers.x.insights import XInsightsReader
from omnisocial.adapters.providers.x.oauth import x_oauth
from omnisocial.adapters.providers.x.profiles import XProfileLookup
from omnisocial.adapters.providers.x.provider import x_provider
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.content import CommentAction
from omnisocial.domain.errors import (
    ErrorKind,
    PermissionMissing,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.handles import Handle, HandleKind, Network, parse_handle
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.provider import Capability
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.window import TimeWindow
from omnisocial.testing import FakeTransport
from tests.adapters.x.conftest import ACCOUNT, ME, TOKEN, TOKEN_URL, config, problem
from tests.fakes import NOW, FakeClock

# ── Configuración, cliente y errores ────────────────────────────────────────────────────────────


def test_la_configuracion_valida_lo_basico() -> None:
    with pytest.raises(ValueError, match="van juntos"):
        XConfig(client_id="app")
    with pytest.raises(ValueError, match="token de la app"):
        XConfig()
    with pytest.raises(ValueError, match="3 MB"):
        config(media_segment_bytes=4 * 1024 * 1024)
    assert "secreto" not in repr(config())
    assert "token-app" not in repr(config())
    assert iso(datetime(2026, 11, 20, 7, tzinfo=UTC)) == "2026-11-20T07:00:00Z"
    assert parse_time("2026-11-20T07:00:00.000Z") == datetime(2026, 11, 20, 7, tzinfo=UTC)
    assert parse_time("2026-11-20T07:00:00") == datetime(2026, 11, 20, 7, tzinfo=UTC)
    assert parse_time("ayer") is None
    assert parse_time(None) is None


@pytest.mark.parametrize(
    ("response", "error", "kind"),
    [
        (problem(401, detail="Unauthorized"), TokenRejected, None),
        (problem(403, "client-forbidden"), PermissionMissing, ErrorKind.MISSING_PERMISSION),
        (problem(403, "usage-capped"), QuotaExhausted, ErrorKind.QUOTA_EXHAUSTED),
        # Sin créditos: no es el token, la conexión sigue sana.
        (problem(402, detail="Add credits"), QuotaExhausted, ErrorKind.QUOTA_EXHAUSTED),
        (problem(400, "invalid-request"), ProviderError, ErrorKind.INVALID_REQUEST),
        # Un 403 sin tipo conocido (contenido duplicado, por ejemplo) no invalida la conexión.
        (problem(403, detail="duplicate content"), ProviderError, ErrorKind.UNKNOWN),
        # La forma vieja de los errores, y el dominio viejo en `type`.
        (
            HttpResponse(429, {"errors": [{"code": 88, "message": "Rate limit exceeded"}]}, ""),
            RateLimited,
            ErrorKind.RATE_LIMITED,
        ),
        (
            HttpResponse(
                403, {"type": "https://api.twitter.com/2/problems/usage-capped", "title": "Tope"}, ""
            ),
            QuotaExhausted,
            ErrorKind.QUOTA_EXHAUSTED,
        ),
        (HttpResponse(503, None, "ups"), ProviderError, ErrorKind.TRANSIENT),
    ],
)
async def test_errores(
    transport: FakeTransport,
    client: XClient,
    response: HttpResponse,
    error: type[Exception],
    kind: ErrorKind | None,
) -> None:
    transport.on("GET", "users/me", response)
    with pytest.raises(error) as raised:
        await client.get("users/me", "tok")
    assert type(raised.value) is error
    assert getattr(raised.value, "kind", None) is kind


async def test_el_limite_dice_cuando_vuelve_con_una_hora(transport: FakeTransport, client: XClient) -> None:
    reset = int((NOW + timedelta(minutes=9)).timestamp())
    transport.on("GET", "users/me", problem(429, "rate-limit-exceeded", **{"x-rate-limit-reset": str(reset)}))
    with pytest.raises(RateLimited) as raised:
        await client.get("users/me", "tok")
    assert raised.value.retry_after == 540.0
    transport.routes.clear()
    transport.on("GET", "users/me", problem(429, **{"x-rate-limit-reset": str(reset - 3600)}))
    with pytest.raises(RateLimited) as past:
        await client.get("users/me", "tok")
    assert past.value.retry_after == 0.0


# ── Login y cuenta ──────────────────────────────────────────────────────────────────────────────


def test_la_url_usa_pkce_y_pide_acceso_sin_conexion(client: XClient) -> None:
    oauth = x_oauth(client, FakeClock())
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://api/cb",
        scopes=oauth.default_scopes(Purpose.CONNECT),
        code_challenge="d",
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://x.com/i/oauth2/authorize?")
    assert query["scope"] == ["tweet.read users.read offline.access"]
    assert (query["code_challenge"], query["code_challenge_method"]) == (["d"], ["S256"])
    assert oauth.default_scopes(Purpose.LOGIN) == ("tweet.read", "users.read")


async def test_la_app_se_identifica_por_cabecera_y_el_token_de_renovacion_rota(
    transport: FakeTransport, client: XClient
) -> None:
    transport.on("POST", TOKEN_URL, {"access_token": "a2", "refresh_token": "r2", "expires_in": 7200})
    transport.on("POST", "oauth2/revoke", {"revoked": True})
    oauth = x_oauth(client, FakeClock())
    fresh = await oauth.refresh(Token(TokenKind.USER, "a1", refresh_token="r1"))
    # El de renovación es de un solo uso: hay que guardar el nuevo.
    assert (fresh.access_token, fresh.refresh_token) == ("a2", "r2")
    assert fresh.expires_at == NOW + timedelta(hours=2)
    call = transport.calls[0]
    assert call.headers == {"Authorization": "Basic YXBwOnNlY3JldG8="}
    assert call.form == {"grant_type": "refresh_token", "refresh_token": "r1"}
    await oauth.revoke(fresh)
    assert transport.calls[1].form == {"token": "a2"}


async def test_un_token_de_renovacion_ya_usado_es_terminal(transport: FakeTransport, client: XClient) -> None:
    transport.on(
        "POST",
        TOKEN_URL,
        {"error": "invalid_grant", "error_description": "Value passed for the token was invalid."},
        status=400,
    )
    with pytest.raises(TokenRejected, match="invalid"):
        await x_oauth(client, FakeClock()).refresh(Token(TokenKind.USER, "a1", refresh_token="r1"))


async def test_la_identidad_y_el_activo_son_la_cuenta(transport: FakeTransport, client: XClient) -> None:
    transport.on("GET", "users/me", ME, {"data": {}})
    identity = await x_oauth(client, FakeClock()).identity(TOKEN)
    assert (identity.external_id, identity.name, identity.avatar_url) == (
        "2244994945",
        "Mi Marca",
        "https://pbs.twimg.com/a.jpg",
    )
    assert transport.calls[0].headers == {"Authorization": "Bearer acceso-x"}
    with pytest.raises(ProviderError, match="id de la cuenta"):
        await XAssetDirectory(client).discover(TOKEN)
    transport.routes.clear()
    transport.on("GET", "users/me", ME)
    [asset] = await XAssetDirectory(client).discover(TOKEN)
    assert (asset.kind, asset.external_id, asset.name, asset.metadata) == (
        X_ACCOUNT,
        "2244994945",
        "Mi Marca",
        {"username": "mimarca"},
    )


# ── Posts ───────────────────────────────────────────────────────────────────────────────────────


def _post(post_id: str, **metrics: int) -> dict[str, object]:
    return {
        "id": post_id,
        "text": f"Post {post_id}",
        "created_at": "2026-11-20T10:00:00.000Z",
        "public_metrics": metrics,
    }


async def test_los_posts_propios_sin_reposts_ni_respuestas(transport: FakeTransport, client: XClient) -> None:
    first = {
        "data": [_post("3", like_count=10, reply_count=2, retweet_count=4, impression_count=900)],
        "meta": {"next_token": "pag-2"},
    }
    second = {
        "data": [{**_post("2", repost_count=1), "attachments": {"media_keys": ["3_1"]}}, {"text": "sin id"}]
    }
    transport.on("GET", "users/2244994945/tweets", first, second)
    window = TimeWindow(datetime(2026, 11, 15, tzinfo=UTC), datetime(2026, 11, 21, tzinfo=UTC))
    posts = await XContentReader(client).list_posts(ACCOUNT, TOKEN, window=window, limit=None)
    # X filtra por fecha: no se trae de más. Cada post leído se cobra.
    assert transport.calls[0].params == {
        "max_results": 100,
        "exclude": "retweets,replies",
        "tweet.fields": "created_at,public_metrics,conversation_id,attachments",
        "start_time": "2026-11-15T00:00:00Z",
        "end_time": "2026-11-21T00:00:00Z",
    }
    assert transport.calls[1].params["pagination_token"] == "pag-2"
    first_post, second_post = posts
    assert (first_post.external_id, first_post.text, first_post.permalink) == (
        "3",
        "Post 3",
        "https://x.com/i/web/status/3",
    )
    assert (
        first_post.like_count,
        first_post.comment_count,
        first_post.share_count,
        first_post.view_count,
    ) == (10, 2, 4, 900)
    # Los reposts vienen con un nombre o con el otro.
    assert (second_post.share_count, second_post.media_type, first_post.media_type) == (1, "media", "text")


async def test_el_tope_y_el_nombre_del_parametro_de_campos(transport: FakeTransport) -> None:
    client = XClient(config(post_fields_param="post.fields", page_size=5), transport, FakeClock())
    transport.on("GET", "users/2244994945/tweets", {"data": [_post("3"), _post("2")]})
    posts = await XContentReader(client).list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=1)
    assert [post.external_id for post in posts] == ["3"]
    assert "post.fields" in transport.calls[0].params
    assert "start_time" not in transport.calls[0].params


# ── Respuestas ──────────────────────────────────────────────────────────────────────────────────


async def test_las_respuestas_se_buscan_en_la_conversacion(transport: FakeTransport, client: XClient) -> None:
    page = {
        "data": [
            {
                "id": "11",
                "text": "¡Genial!",
                "author_id": "77",
                "created_at": "2026-11-20T11:00:00Z",
                "public_metrics": {"like_count": 3, "reply_count": 1},
            },
            # La segunda parte del hilo es de la propia cuenta: no es un comentario.
            {"id": "12", "text": "sigue…", "author_id": "2244994945"},
        ],
        "includes": {"users": [{"id": "77", "username": "ana", "name": "Ana"}]},
        "meta": {"next_token": "pag-2"},
    }
    transport.on("GET", "tweets/search/recent", page, {"meta": {"result_count": 0}})
    [comment] = await XCommentGateway(client).list_comments(ACCOUNT, TOKEN, object_id="10")
    assert (comment.external_id, comment.object_external_id, comment.text) == ("11", "10", "¡Genial!")
    assert (comment.author_id, comment.author_name, comment.like_count, comment.reply_count) == (
        "77",
        "ana",
        3,
        1,
    )
    assert transport.calls[0].params["query"] == "conversation_id:10 is:reply"
    assert transport.calls[0].params["expansions"] == "author_id"
    # La búsqueda pagina con otro nombre de parámetro.
    assert transport.calls[1].params["next_token"] == "pag-2"


async def test_responder_ocultar_y_dar_like(transport: FakeTransport, client: XClient) -> None:
    gateway = XCommentGateway(client)
    transport.on(
        "POST",
        "tweets",
        HttpResponse(201, {"data": {"id": "20", "text": "¡Gracias!"}}, ""),
        HttpResponse(201, {"data": {}}, ""),
    )
    assert await gateway.reply(ACCOUNT, TOKEN, comment_id="11", text="¡Gracias!") == "20"
    assert transport.calls[0].json == {"text": "¡Gracias!", "reply": {"in_reply_to_tweet_id": "11"}}
    with pytest.raises(ProviderError, match="id de la respuesta"):
        await gateway.reply(ACCOUNT, TOKEN, comment_id="11", text="otra")

    transport.on("PUT", "tweets/11/hidden", {"data": {"hidden": True}})
    await gateway.set_hidden(ACCOUNT, TOKEN, comment_id="11", hidden=True)
    assert transport.calls[2].json == {"hidden": True}

    transport.on("POST", "users/2244994945/likes", {"data": {"liked": True}})
    await gateway.like(ACCOUNT, TOKEN, comment_id="11")
    assert transport.calls[3].json == {"tweet_id": "11"}


async def test_lo_que_x_no_ofrece_en_respuestas(transport: FakeTransport, client: XClient) -> None:
    gateway = XCommentGateway(client)
    assert not gateway.supports(ACCOUNT, CommentAction.DELETE)
    assert all(
        gateway.supports(ACCOUNT, a) for a in (CommentAction.REPLY, CommentAction.HIDE, CommentAction.LIKE)
    )
    with pytest.raises(ProviderError, match="ocultar"):
        await gateway.delete(ACCOUNT, TOKEN, comment_id="11")
    # Responder por API a quien no mencionó a la cuenta: X lo rechaza.
    transport.on("POST", "tweets", problem(403, detail="Reply not allowed"))
    with pytest.raises(ProviderError, match="Reply not allowed"):
        await gateway.reply(ACCOUNT, TOKEN, comment_id="11", text="hola")


# ── Contadores ──────────────────────────────────────────────────────────────────────────────────


async def test_los_contadores_de_la_cuenta(transport: FakeTransport, client: XClient) -> None:
    reader = XInsightsReader(client, FakeClock())
    renamed = {"data": {"id": "1", "public_metrics": {"followers_count": 9, "post_count": 3}}}
    transport.on("GET", "users/me", ME, renamed)
    series = await reader.read(
        ACCOUNT,
        TOKEN,
        metrics=["followers_count", "tweet_count", "inventada"],
        period=Period.DAY,
        window=TimeWindow(),
    )
    assert [(s.name, s.period, s.points[0].value, s.points[0].end_time) for s in series] == [
        ("followers_count", Period.LIFETIME, 5200.0, NOW),
        ("tweet_count", Period.LIFETIME, 980.0, NOW),
    ]
    # La cantidad de posts viene con un nombre o con el otro.
    [posts] = await reader.read(
        ACCOUNT, TOKEN, metrics=["tweet_count"], period=Period.DAY, window=TimeWindow()
    )
    assert posts.points[0].value == 3.0
    assert (
        reader.catalog.native_for(X_ACCOUNT, CanonicalMetric.FOLLOWERS, reader.api_version)
        == "followers_count"
    )
    assert (
        await reader.read(ACCOUNT, TOKEN, metrics=["inventada"], period=Period.DAY, window=TimeWindow()) == []
    )
    assert len(transport.calls) == 2


# ── Perfiles públicos ───────────────────────────────────────────────────────────────────────────


def _handle(text: str) -> Handle:
    handle = parse_handle(Network.X, text)
    assert handle is not None
    return handle


async def test_perfil_publico_con_el_token_de_la_app(transport: FakeTransport, client: XClient) -> None:
    lookup = XProfileLookup(client)
    assert lookup.networks == frozenset({Network.X})
    assert lookup.viewer_kinds(Network.X) == frozenset()
    transport.on("GET", "users/by/username/mimarca", ME)
    profile = await lookup.lookup(_handle("https://x.com/MiMarca"), viewer=None, token=None)
    assert profile is not None
    assert (profile.external_id, profile.username, profile.name) == ("2244994945", "mimarca", "Mi Marca")
    assert (profile.followers, profile.following, profile.posts, profile.verified) == (5200, 120, 980, True)
    assert (profile.url, profile.website, profile.bio) == (
        "https://x.com/mimarca",
        "https://ejemplo.com",
        "Hacemos cosas",
    )
    assert transport.calls[0].headers == {"Authorization": "Bearer token-app"}

    transport.on("GET", "users/123", ME)
    by_id = await lookup.lookup(Handle(Network.X, "123", HandleKind.ID), viewer=None, token=None)
    assert by_id is not None


async def test_una_cuenta_que_no_existe(transport: FakeTransport, client: XClient) -> None:
    lookup = XProfileLookup(client)
    # Con 200 y sin `data` (cuenta inexistente o suspendida), o con 404.
    not_found = {"errors": [{"title": "Not Found Error", "detail": "Could not find user"}]}
    transport.on("GET", "users/by/username/nadie", not_found, problem(404, "resource-not-found"))
    assert await lookup.lookup(_handle("@nadie"), viewer=None, token=None) is None
    assert await lookup.lookup(_handle("@nadie"), viewer=None, token=None) is None
    transport.routes.clear()
    transport.on("GET", "users/by/username/nadie", problem(403, "client-forbidden"))
    with pytest.raises(PermissionMissing):
        await lookup.lookup(_handle("@nadie"), viewer=None, token=None)


async def test_solo_con_el_token_de_la_app_hay_perfiles_y_nada_mas(transport: FakeTransport) -> None:
    only_bearer = x_provider(XConfig(bearer_token="token-app"), transport)
    assert only_bearer.capabilities == frozenset({Capability.PUBLIC_PROFILES})
    without = XClient(config(bearer_token=None), transport, FakeClock())
    with pytest.raises(ProviderError, match="token de la app"):
        await without.get_public("users/1", {})
    assert x_provider(config(bearer_token=None), transport).profiles is None
