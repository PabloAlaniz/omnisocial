"""La app por servidor, la cuenta, publicaciones, respuestas, contadores y perfiles, con una API falsa."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.mastodon.client import MastodonClient, parse_time, plain
from omnisocial.adapters.providers.mastodon.config import (
    MASTODON,
    MASTODON_ACCOUNT,
    PIXELFED_FLAVOR,
    MastodonConfig,
    PixelfedConfig,
)
from omnisocial.adapters.providers.mastodon.oauth import MastodonIdentity, MastodonOAuth
from omnisocial.adapters.providers.mastodon.reading import (
    MastodonAssetDirectory,
    MastodonCommentGateway,
    MastodonContentReader,
    MastodonInsightsReader,
    MastodonProfileLookup,
    catalog_for,
)
from omnisocial.adapters.stores.memory import InMemoryServerAppStore
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.content import CommentAction
from omnisocial.domain.errors import ErrorKind, PermissionMissing, ProviderError, RateLimited, TokenRejected
from omnisocial.domain.handles import Network, parse_handle
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.window import TimeWindow
from omnisocial.testing import FakeTransport
from tests.adapters.mastodon.conftest import ACCOUNT, APP, ME, REDIRECT, SERVER, TOKEN, failure
from tests.fakes import NOW, FakeClock


def oauth(
    client: MastodonClient, apps: InMemoryServerAppStore, config: MastodonConfig | None = None
) -> MastodonOAuth:
    return MastodonOAuth(client, config or MastodonConfig(), apps, FakeClock())


# ── Cliente y errores ───────────────────────────────────────────────────────────────────────────


def test_el_texto_viene_como_html() -> None:
    assert (
        plain("<p>Hola <a href='x'>@ana</a> &amp; cía</p><p>Segunda<br/>línea</p>")
        == "Hola @ana & cía\nSegunda\nlínea"
    )
    assert plain("") is None
    assert plain(None) is None
    assert parse_time("2026-11-20T10:00:00.000Z") == datetime(2026, 11, 20, 10, tzinfo=UTC)
    assert parse_time("ayer") is None


@pytest.mark.parametrize(
    ("response", "error", "kind"),
    [
        (failure(401, "The access token is invalid"), TokenRejected, None),
        (
            failure(403, "This action is outside the authorized scopes"),
            PermissionMissing,
            ErrorKind.MISSING_PERMISSION,
        ),
        # Otro 403 (el de Pixelfed ante una publicación vacía, por ejemplo) no es un permiso faltante.
        (failure(403, "Empty statuses are not allowed"), ProviderError, ErrorKind.UNKNOWN),
        (failure(422, "Validation failed: Text can't be blank"), ProviderError, ErrorKind.INVALID_REQUEST),
        (HttpResponse(503, None, "ups"), ProviderError, ErrorKind.TRANSIENT),
    ],
)
async def test_errores(
    transport: FakeTransport,
    client: MastodonClient,
    response: HttpResponse,
    error: type[Exception],
    kind: ErrorKind | None,
) -> None:
    transport.on("GET", "api/v1/accounts/verify_credentials", response)
    with pytest.raises(error) as raised:
        await client.get("api/v1/accounts/verify_credentials", TOKEN)
    assert type(raised.value) is error
    assert getattr(raised.value, "kind", None) is kind
    assert getattr(raised.value, "provider", MASTODON) == MASTODON


async def test_el_limite_dice_cuando_vuelve_con_una_fecha(
    transport: FakeTransport, client: MastodonClient
) -> None:
    reset = (NOW + timedelta(minutes=4)).isoformat().replace("+00:00", "Z")
    transport.on("GET", "x", failure(429, "Too many requests", **{"X-RateLimit-Reset": reset}))
    with pytest.raises(RateLimited) as raised:
        await client.get("x", TOKEN)
    assert raised.value.retry_after == 240.0
    with pytest.raises(ProviderError, match="servidor"):
        await client.get("x", Token(TokenKind.USER, "sin-servidor"))


# ── Una app por servidor ────────────────────────────────────────────────────────────────────────


async def test_la_app_se_registra_una_vez_por_servidor(
    transport: FakeTransport, client: MastodonClient, apps: InMemoryServerAppStore
) -> None:
    transport.on("POST", "api/v1/apps", APP)
    flow = oauth(client, apps, MastodonConfig(client_name="Mi App", website="https://ejemplo.com"))
    url = await flow.authorization_url(
        SERVER,
        state="s",
        redirect_uri=REDIRECT,
        scopes=flow.default_scopes(Purpose.CONNECT),
        code_challenge="d",
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://mastodon.social/oauth/authorize?")
    assert (query["client_id"], query["scope"], query["state"]) == (
        ["id-app"],
        ["read:accounts read:statuses"],
        ["s"],
    )
    assert (query["code_challenge"], query["code_challenge_method"]) == (["d"], ["S256"])
    assert transport.calls[0].form == {
        "client_name": "Mi App",
        "redirect_uris": REDIRECT,
        # La app se registra con el máximo de permisos que después se le puede pedir a alguien.
        "scopes": "read:accounts read:statuses write:statuses write:media write:favourites",
        "website": "https://ejemplo.com",
    }
    stored = await apps.get(MASTODON, SERVER)
    assert stored is not None
    assert (stored.client_id, stored.client_secret, stored.redirect_uri) == (
        "id-app",
        "secreto-app",
        REDIRECT,
    )

    # La segunda persona de ese servidor usa la misma app.
    await flow.authorization_url(
        SERVER, state="s2", redirect_uri=REDIRECT, scopes=("read:accounts",), code_challenge=None
    )
    assert len(transport.calls) == 1
    assert flow.default_scopes(Purpose.LOGIN) == ("read:accounts",)


async def test_si_cambia_la_url_de_retorno_la_app_se_registra_de_nuevo(
    transport: FakeTransport, client: MastodonClient, apps: InMemoryServerAppStore
) -> None:
    transport.on("POST", "api/v1/apps", APP, {**APP, "client_id": "id-nueva"})
    flow = oauth(client, apps)
    await flow.authorization_url(SERVER, state="s", redirect_uri=REDIRECT, scopes=(), code_challenge=None)
    url = await flow.authorization_url(
        SERVER, state="s", redirect_uri="https://nueva/cb", scopes=(), code_challenge=None
    )
    assert "client_id=id-nueva" in url
    stored = await apps.get(MASTODON, SERVER)
    assert stored is not None
    assert stored.redirect_uri == "https://nueva/cb"


async def test_un_servidor_que_no_registra_la_app(
    transport: FakeTransport, client: MastodonClient, apps: InMemoryServerAppStore
) -> None:
    flow = oauth(client, apps)
    transport.on("POST", "api/v1/apps", {"name": "sin claves"})
    with pytest.raises(ProviderError, match="no registró la app"):
        await flow.authorization_url(SERVER, state="s", redirect_uri=REDIRECT, scopes=(), code_challenge=None)
    transport.routes.clear()
    # Un Pixelfed con OAuth apagado responde 404.
    transport.on("POST", "api/v1/apps", HttpResponse(404, None, "Not Found"))
    with pytest.raises(ProviderError, match="Not Found"):
        await flow.authorization_url(SERVER, state="s", redirect_uri=REDIRECT, scopes=(), code_challenge=None)
    with pytest.raises(ProviderError, match="No hay una app registrada"):
        await flow.exchange_code(SERVER, code="c", redirect_uri=REDIRECT, code_verifier=None)


async def test_canjear_el_codigo_con_la_app_de_ese_servidor(
    transport: FakeTransport, client: MastodonClient, apps: InMemoryServerAppStore
) -> None:
    transport.on("POST", "api/v1/apps", APP)
    transport.on(
        "POST",
        "oauth/token",
        {"access_token": "acceso-1", "scope": "read:accounts read:statuses", "created_at": 1},
    )
    transport.on("POST", "oauth/revoke", {})
    flow = oauth(client, apps)
    await flow.authorization_url(SERVER, state="s", redirect_uri=REDIRECT, scopes=(), code_challenge=None)
    token = await flow.exchange_code(SERVER, code="c", redirect_uri=REDIRECT, code_verifier="v")
    assert (token.access_token, token.server, token.scopes) == (
        "acceso-1",
        SERVER,
        frozenset({"read:accounts", "read:statuses"}),
    )
    # Un token de Mastodon no vence ni se renueva.
    assert (token.expires_at, token.refresh_token, flow.can_refresh(token)) == (None, None, False)
    assert transport.calls[1].form == {
        "grant_type": "authorization_code",
        "code": "c",
        "client_id": "id-app",
        "client_secret": "secreto-app",
        "redirect_uri": REDIRECT,
        "code_verifier": "v",
    }
    await flow.revoke(token)
    assert transport.calls[2].form == {
        "client_id": "id-app",
        "client_secret": "secreto-app",
        "token": "acceso-1",
    }
    await flow.revoke(Token(TokenKind.USER, "sin-servidor"))
    assert len(transport.calls) == 3
    with pytest.raises(ProviderError, match="renovarse"):
        await flow.refresh(token)


async def test_pixelfed_no_manda_pkce_y_sus_tokens_se_renuevan(
    transport: FakeTransport, apps: InMemoryServerAppStore
) -> None:
    client = MastodonClient(PIXELFED_FLAVOR, transport, FakeClock())
    flow = oauth(client, apps, PixelfedConfig())
    transport.on("POST", "api/v1/apps", APP)
    url = await flow.authorization_url(
        SERVER,
        state="s",
        redirect_uri=REDIRECT,
        scopes=flow.default_scopes(Purpose.CONNECT),
        code_challenge="d",
    )
    assert "code_challenge" not in url
    assert "scope=read" in url
    assert transport.calls[0].form is not None
    assert transport.calls[0].form["scopes"] == "read write"
    granted = {"access_token": "a1", "refresh_token": "r1", "expires_in": 30758400}
    transport.on("POST", "oauth/token", granted, {"access_token": "a2", "expires_in": 30758400})
    token = await flow.exchange_code(SERVER, code="c", redirect_uri=REDIRECT, code_verifier="v")
    assert "code_verifier" not in (transport.calls[1].form or {})
    assert (token.refresh_token, token.expires_at, flow.can_refresh(token)) == (
        "r1",
        NOW + timedelta(days=356),
        True,
    )
    fresh = await flow.refresh(token)
    # El servidor y lo que la respuesta no repite se conservan.
    assert (fresh.access_token, fresh.refresh_token, fresh.server) == ("a2", "r1", SERVER)
    assert transport.calls[2].form == {
        "grant_type": "refresh_token",
        "refresh_token": "r1",
        "client_id": "id-app",
        "client_secret": "secreto-app",
    }


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (
            HttpResponse(400, {"error": "invalid_grant", "error_description": "código vencido"}, ""),
            TokenRejected,
        ),
        (HttpResponse(200, {"scope": "read"}, ""), ProviderError),
        (failure(401, "invalid_client"), TokenRejected),
    ],
)
async def test_canjes_que_fallan(
    transport: FakeTransport,
    client: MastodonClient,
    apps: InMemoryServerAppStore,
    response: HttpResponse,
    error: type[Exception],
) -> None:
    transport.on("POST", "api/v1/apps", APP)
    transport.on("POST", "oauth/token", response)
    flow = oauth(client, apps)
    await flow.authorization_url(SERVER, state="s", redirect_uri=REDIRECT, scopes=(), code_challenge=None)
    with pytest.raises(error):
        await flow.exchange_code(SERVER, code="c", redirect_uri=REDIRECT, code_verifier=None)


# ── La cuenta ───────────────────────────────────────────────────────────────────────────────────


async def test_la_identidad_lleva_el_servidor(transport: FakeTransport, client: MastodonClient) -> None:
    transport.on("GET", "api/v1/accounts/verify_credentials", ME, {"username": "sin-id"})
    identity = await MastodonIdentity(client).identity(TOKEN)
    # El id de una cuenta vale solo en su servidor.
    assert (identity.external_id, identity.name, identity.avatar_url) == (
        "109@mastodon.social",
        "Ana Pérez",
        "https://files.mastodon.social/a.png",
    )
    assert transport.calls[0].headers == {"Authorization": "Bearer acceso-1"}
    with pytest.raises(ProviderError, match="id de la cuenta"):
        await MastodonAssetDirectory(client).discover(TOKEN)
    transport.routes.clear()
    transport.on("GET", "api/v1/accounts/verify_credentials", ME)
    [asset] = await MastodonAssetDirectory(client).discover(TOKEN)
    assert (asset.kind, asset.external_id, asset.name, asset.token) == (
        MASTODON_ACCOUNT,
        "109",
        "Ana Pérez",
        None,
    )
    assert asset.metadata == {"server": SERVER, "acct": "ana@mastodon.social"}


# ── Publicaciones ───────────────────────────────────────────────────────────────────────────────


def _status(status_id: str, day: int, **extra: object) -> dict[str, object]:
    return {
        "id": status_id,
        "created_at": f"2026-11-{day:02d}T10:00:00.000Z",
        "content": f"<p>Publicación {status_id}</p>",
        "url": f"https://mastodon.social/@ana/{status_id}",
        "favourites_count": 7,
        "replies_count": 2,
        "reblogs_count": 1,
        "media_attachments": [],
        **extra,
    }


async def test_las_publicaciones_propias(transport: FakeTransport, client: MastodonClient) -> None:
    media = [{"type": "image", "preview_url": "https://files/p.png"}]
    first = [_status("40", 22), _status("30", 20, media_attachments=media)]
    second = [_status("20", 10), {"content": "sin id"}]
    path = "api/v1/accounts/109/statuses"
    transport.on("GET", path, HttpResponse(200, first, ""), HttpResponse(200, second, ""))
    window = TimeWindow(datetime(2026, 11, 15, tzinfo=UTC), datetime(2026, 11, 21, tzinfo=UTC))
    [post] = await MastodonContentReader(client, 40).list_posts(ACCOUNT, TOKEN, window=window, limit=None)
    assert (post.external_id, post.text, post.permalink) == (
        "30",
        "Publicación 30",
        "https://mastodon.social/@ana/30",
    )
    assert (post.like_count, post.comment_count, post.share_count) == (7, 2, 1)
    assert (post.media_type, post.media_url) == ("image", "https://files/p.png")
    assert transport.calls[0].params == {"limit": 40, "exclude_replies": "true", "exclude_reblogs": "true"}
    # La página siguiente es lo anterior a la última publicación de esta.
    assert transport.calls[1].params["max_id"] == "30"
    assert len(transport.calls) == 2


async def test_el_tope_y_un_error_al_listar(transport: FakeTransport, client: MastodonClient) -> None:
    path = "api/v1/accounts/109/statuses"
    transport.on("GET", path, HttpResponse(200, [_status("40", 22), _status("30", 20)], ""))
    posts = await MastodonContentReader(client, 40).list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=1)
    assert [post.external_id for post in posts] == ["40"]
    transport.routes.clear()
    transport.on("GET", path, HttpResponse(200, [], ""))
    assert (
        await MastodonContentReader(client, 40).list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=None)
        == []
    )
    transport.routes.clear()
    transport.on("GET", path, failure(401, "The access token is invalid"))
    with pytest.raises(TokenRejected):
        await MastodonContentReader(client, 40).list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=None)


# ── Respuestas ──────────────────────────────────────────────────────────────────────────────────


async def test_las_respuestas_de_la_conversacion(transport: FakeTransport, client: MastodonClient) -> None:
    reply = _status(
        "50",
        20,
        content="<p>¡Genial!</p>",
        in_reply_to_id="30",
        account={"id": "777", "acct": "luis@hachyderm.io"},
    )
    nested = _status("51", 20, in_reply_to_id="50", account={"id": "888", "acct": "eva"})
    own = _status("52", 20, in_reply_to_id="30", account={"id": "109", "acct": "ana"})
    transport.on("GET", "api/v1/statuses/30/context", {"ancestors": [], "descendants": [reply, nested, own]})
    first, second = await MastodonCommentGateway(client).list_comments(ACCOUNT, TOKEN, object_id="30")
    assert (first.external_id, first.object_external_id, first.text) == ("50", "30", "¡Genial!")
    assert (first.author_id, first.author_name, first.like_count) == ("777", "luis@hachyderm.io", 7)
    # Vienen todas las de la conversación: cada una dice a cuál responde.
    assert second.object_external_id == "50"


async def test_responder_y_marcar_favorita(transport: FakeTransport, client: MastodonClient) -> None:
    gateway = MastodonCommentGateway(client)
    transport.on("POST", "api/v1/statuses", {"id": "60"}, {})
    assert await gateway.reply(ACCOUNT, TOKEN, comment_id="50", text="¡Gracias!") == "60"
    assert transport.calls[0].json == {"status": "¡Gracias!", "in_reply_to_id": "50"}
    with pytest.raises(ProviderError, match="id de la respuesta"):
        await gateway.reply(ACCOUNT, TOKEN, comment_id="50", text="otra")
    transport.on("POST", "api/v1/statuses/50/favourite", {"id": "50", "favourited": True})
    await gateway.like(ACCOUNT, TOKEN, comment_id="50")
    assert transport.calls[2].retry_safe

    assert gateway.supports(ACCOUNT, CommentAction.REPLY)
    assert gateway.supports(ACCOUNT, CommentAction.LIKE)
    assert not gateway.supports(ACCOUNT, CommentAction.HIDE)
    assert not gateway.supports(ACCOUNT, CommentAction.DELETE)
    with pytest.raises(ProviderError, match="ocultar"):
        await gateway.set_hidden(ACCOUNT, TOKEN, comment_id="50", hidden=True)
    with pytest.raises(ProviderError, match="borrar"):
        await gateway.delete(ACCOUNT, TOKEN, comment_id="50")


# ── Contadores y perfiles ───────────────────────────────────────────────────────────────────────


async def test_los_contadores_de_la_cuenta(transport: FakeTransport, client: MastodonClient) -> None:
    reader = MastodonInsightsReader(client, FakeClock(), catalog_for(MASTODON_ACCOUNT))
    transport.on("GET", "api/v1/accounts/verify_credentials", ME)
    series = await reader.read(
        ACCOUNT,
        TOKEN,
        metrics=["followers_count", "statuses_count", "inventada"],
        period=Period.DAY,
        window=TimeWindow(),
    )
    assert [(s.name, s.period, s.points[0].value, s.points[0].end_time) for s in series] == [
        ("followers_count", Period.LIFETIME, 820.0, NOW),
        ("statuses_count", Period.LIFETIME, 1340.0, NOW),
    ]
    assert (
        reader.catalog.native_for(MASTODON_ACCOUNT, CanonicalMetric.FOLLOWERS, reader.api_version)
        == "followers_count"
    )
    assert (
        await reader.read(ACCOUNT, TOKEN, metrics=["inventada"], period=Period.DAY, window=TimeWindow()) == []
    )
    assert len(transport.calls) == 1


async def test_el_perfil_publico_se_le_pide_al_servidor_de_la_cuenta(client: MastodonClient) -> None:
    transport = FakeTransport()
    lookup = MastodonProfileLookup(MastodonClient(client.flavor, transport, FakeClock()))
    assert lookup.networks == frozenset({Network.MASTODON})
    assert lookup.viewer_kinds(Network.MASTODON) == frozenset()
    url = "https://hachyderm.io/api/v1/accounts/lookup"
    transport.on(
        "GET",
        url,
        {**ME, "id": "777"},
        HttpResponse(404, {"error": "Record not found"}, ""),
        {"username": "sin-id"},
    )
    handle = parse_handle(Network.MASTODON, "@Ana@Hachyderm.io")
    assert handle is not None
    profile = await lookup.lookup(handle, viewer=None, token=None)
    assert profile is not None
    assert (profile.external_id, profile.username, profile.name) == (
        "777@hachyderm.io",
        "ana@hachyderm.io",
        "Ana Pérez",
    )
    assert (profile.followers, profile.following, profile.posts, profile.bio) == (820, 95, 1340, "Hago cosas")
    assert (transport.calls[0].params, transport.calls[0].headers) == ({"acct": "ana"}, None)
    assert await lookup.lookup(handle, viewer=None, token=None) is None
    assert await lookup.lookup(handle, viewer=None, token=None) is None
    transport.routes.clear()
    transport.on("GET", url, failure(401, "This method requires an authenticated user"))
    with pytest.raises(TokenRejected):
        await lookup.lookup(handle, viewer=None, token=None)
