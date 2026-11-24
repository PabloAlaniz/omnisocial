"""Login, canal, videos, comentarios, métricas y perfiles públicos, con una API falsa."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.youtube.assets import YouTubeAssetDirectory
from omnisocial.adapters.providers.youtube.client import YouTubeClient, as_int, parse_time
from omnisocial.adapters.providers.youtube.comments import YouTubeCommentGateway
from omnisocial.adapters.providers.youtube.config import YOUTUBE_CHANNEL, YouTubeConfig
from omnisocial.adapters.providers.youtube.content import YouTubeContentReader
from omnisocial.adapters.providers.youtube.insights import YouTubeInsightsReader
from omnisocial.adapters.providers.youtube.oauth import youtube_oauth
from omnisocial.adapters.providers.youtube.profiles import YouTubeProfileLookup
from omnisocial.adapters.providers.youtube.provider import youtube_provider
from omnisocial.adapters.stores.memory import InMemoryQuotaLedger
from omnisocial.application.quota import QuotaBudget
from omnisocial.domain.asset import Asset
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
from omnisocial.domain.handles import Handle, Network, parse_handle
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.provider import Capability
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.window import TimeWindow
from omnisocial.testing import FakeTransport
from tests.adapters.youtube.conftest import CHANNEL, OWN_CHANNEL, TOKEN, TOKEN_URL, config, failure
from tests.fakes import NOW, FakeClock

REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def _handle(text: str) -> Handle:
    handle = parse_handle(Network.YOUTUBE, text)
    assert handle is not None
    return handle


# ── Configuración y cliente ─────────────────────────────────────────────────────────────────────


def test_la_configuracion_valida_lo_basico() -> None:
    with pytest.raises(ValueError, match="van juntos"):
        YouTubeConfig(client_id="app")
    with pytest.raises(ValueError, match="clave de API"):
        YouTubeConfig()
    with pytest.raises(ValueError, match="256 KB"):
        config(upload_chunk_bytes=1000)
    assert "secreto" not in repr(config())
    assert "clave" not in repr(config())


def test_valores_de_la_api() -> None:
    assert as_int("1230") == 1230
    assert as_int(7) == 7
    assert as_int(True) is None
    assert as_int("mucho") is None
    assert parse_time("2026-11-20T10:00:00Z") == datetime(2026, 11, 20, 10, tzinfo=UTC)
    assert parse_time("2026-11-20T10:00:00") == datetime(2026, 11, 20, 10, tzinfo=UTC)
    assert parse_time("ayer") is None
    assert parse_time(None) is None


@pytest.mark.parametrize(
    ("response", "error", "kind"),
    [
        (failure("authError", 401), TokenRejected, None),
        (failure("insufficientPermissions"), PermissionMissing, ErrorKind.MISSING_PERMISSION),
        (failure("quotaExceeded"), QuotaExhausted, ErrorKind.QUOTA_EXHAUSTED),
        (failure("userRateLimitExceeded"), RateLimited, ErrorKind.RATE_LIMITED),
        (failure("invalidTitle", 400), ProviderError, ErrorKind.INVALID_REQUEST),
        # Un 403 sin motivo conocido no invalida la conexión ni se confunde con la cuota.
        (failure("forbidden"), ProviderError, ErrorKind.UNKNOWN),
        (HttpResponse(502, None, "bad gateway"), ProviderError, ErrorKind.TRANSIENT),
    ],
)
async def test_el_motivo_del_error_manda_sobre_el_estado(
    transport: FakeTransport,
    client: YouTubeClient,
    response: HttpResponse,
    error: type[Exception],
    kind: ErrorKind | None,
) -> None:
    transport.on("GET", "channels", response)
    with pytest.raises(error) as raised:
        await client.get("channels", "tok", {"part": "snippet"})
    assert type(raised.value) is error
    assert getattr(raised.value, "kind", None) is kind


async def test_el_presupuesto_corta_antes_de_llamar(transport: FakeTransport) -> None:
    ledger = InMemoryQuotaLedger()
    clock = FakeClock()
    client = YouTubeClient(
        config(),
        transport,
        units=QuotaBudget("yt:unidades", 51, ledger, clock),
        uploads=QuotaBudget("yt:subidas", 1, ledger, clock),
    )
    transport.on("GET", "channels", OWN_CHANNEL)
    transport.on("POST", "comments", {"id": "c1"})
    await client.get("channels", "tok", {"part": "snippet"})  # 1 unidad
    await client.write("POST", "comments", "tok", params={"part": "snippet"})  # 50
    with pytest.raises(QuotaExhausted, match="presupuesto") as raised:
        await client.get("channels", "tok", {"part": "snippet"})
    assert raised.value.code == "local_budget"
    assert len(transport.calls) == 2
    await client.spend_upload()
    with pytest.raises(QuotaExhausted, match="subidas"):
        await client.spend_upload()


async def test_el_proveedor_cuenta_la_cuota_por_proyecto_y_por_dia_del_pacifico() -> None:
    ledger = InMemoryQuotaLedger()
    transport = FakeTransport(base="https://www.googleapis.com/youtube/v3/")
    transport.on("GET", "channels", OWN_CHANNEL)
    clock = FakeClock()  # 12:00 UTC del 23: en el Pacífico son las 04:00 del 23
    provider = youtube_provider(config(), transport, clock=clock, quota=ledger)
    await provider.require_assets().discover(TOKEN)
    assert await ledger.spent("youtube:app:unidades", "2026-11-23") == 1
    only_key = youtube_provider(YouTubeConfig(api_key="clave"), transport, clock=clock, quota=ledger)
    assert only_key.capabilities == frozenset({Capability.PUBLIC_PROFILES})
    await only_key.require_profiles().lookup(_handle("@marca"), viewer=None, token=None)
    assert await ledger.spent("youtube:clave-de-api:unidades", "2026-11-23") == 1


# ── Login y canal ───────────────────────────────────────────────────────────────────────────────


def test_la_url_pide_acceso_sin_conexion(client: YouTubeClient) -> None:
    oauth = youtube_oauth(client, FakeClock())
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://api/cb",
        scopes=oauth.default_scopes(Purpose.CONNECT),
        code_challenge="d",
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert query["client_id"] == ["app"]
    assert query["scope"] == ["https://www.googleapis.com/auth/youtube.readonly"]
    # Sin esto Google no manda el token de renovación, o lo manda solo la primera vez.
    assert (query["access_type"], query["prompt"]) == (["offline"], ["consent"])
    assert query["code_challenge"] == ["d"]


async def test_renovar_conserva_el_token_de_renovacion(
    transport: FakeTransport, client: YouTubeClient
) -> None:
    """Google no lo repite al renovar."""
    transport.on("POST", TOKEN_URL, {"access_token": "ya29.nuevo", "expires_in": 3599})
    old = Token(TokenKind.USER, "ya29.viejo", refresh_token="1//renovar")
    fresh = await youtube_oauth(client, FakeClock()).refresh(old)
    assert (fresh.access_token, fresh.refresh_token) == ("ya29.nuevo", "1//renovar")


async def test_un_token_de_renovacion_vencido_es_terminal(
    transport: FakeTransport, client: YouTubeClient
) -> None:
    transport.on("POST", TOKEN_URL, {"error": "invalid_grant", "error_description": "expired"}, status=400)
    with pytest.raises(TokenRejected, match="expired"):
        await youtube_oauth(client, FakeClock()).refresh(Token(TokenKind.USER, "a", refresh_token="r"))


async def test_revocar_va_sin_las_credenciales_y_sin_cuerpo_de_respuesta(
    transport: FakeTransport, client: YouTubeClient
) -> None:
    transport.on("POST", REVOKE_URL, HttpResponse(200, None, ""))
    await youtube_oauth(client, FakeClock()).revoke(TOKEN)
    assert transport.calls[0].form == {"token": "ya29.acceso"}


async def test_la_identidad_y_el_activo_son_el_canal(transport: FakeTransport, client: YouTubeClient) -> None:
    transport.on("GET", "channels", OWN_CHANNEL)
    identity = await youtube_oauth(client, FakeClock()).identity(TOKEN)
    assert (identity.external_id, identity.name, identity.avatar_url) == (
        "UC1234567890123456789012",
        "Mi canal",
        "https://yt3.ggpht.com/a",
    )
    [asset] = await YouTubeAssetDirectory(client).discover(TOKEN)
    assert (asset.kind, asset.external_id, asset.name, asset.token) == (
        YOUTUBE_CHANNEL,
        "UC1234567890123456789012",
        "Mi canal",
        None,
    )
    assert asset.metadata == {"uploads": "UU1234567890123456789012", "handle": "@micanal"}
    assert transport.calls[0].params == {"part": "snippet", "mine": "true"}
    assert transport.calls[0].headers == {"Authorization": "Bearer ya29.acceso"}


async def test_una_cuenta_de_google_sin_canal(transport: FakeTransport, client: YouTubeClient) -> None:
    transport.on("GET", "channels", {"items": []})
    with pytest.raises(ProviderError, match="no tiene un canal"):
        await YouTubeAssetDirectory(client).discover(TOKEN)


# ── Videos ──────────────────────────────────────────────────────────────────────────────────────


def _item(video_id: str, day: int) -> dict[str, object]:
    return {"contentDetails": {"videoId": video_id, "videoPublishedAt": f"2026-11-{day:02d}T10:00:00Z"}}


def _video(video_id: str, **statistics: str) -> dict[str, object]:
    snippet = {
        "title": f"Video {video_id}",
        "publishedAt": "2026-11-20T10:00:00Z",
        "thumbnails": {"default": {"url": f"https://i.ytimg.com/{video_id}.jpg"}},
    }
    return {"id": video_id, "snippet": snippet, "statistics": statistics}


async def test_los_videos_salen_de_la_playlist_de_subidas_y_no_de_una_busqueda(
    transport: FakeTransport, client: YouTubeClient
) -> None:
    transport.on(
        "GET",
        "playlistItems",
        {"items": [_item("v3", 22), _item("v2", 20)], "nextPageToken": "pag-2"},
        {"items": [_item("v1", 10), _item("v0", 1)]},
    )
    transport.on(
        "GET",
        "videos",
        {
            "items": [
                _video("v3", viewCount="10"),
                _video("v2", viewCount="5", likeCount="2", commentCount="1"),
            ]
        },
    )
    window = TimeWindow(datetime(2026, 11, 15, tzinfo=UTC), datetime(2026, 11, 21, tzinfo=UTC))
    posts = await YouTubeContentReader(client).list_posts(CHANNEL, TOKEN, window=window, limit=None)
    assert [call.path for call in transport.calls] == ["playlistItems", "playlistItems", "videos"]
    assert transport.calls[0].params == {
        "part": "contentDetails",
        "playlistId": "UU1234567890123456789012",
        "maxResults": 50,
    }
    assert transport.calls[1].params["pageToken"] == "pag-2"
    # v3 quedó después de la ventana y v1 antes: se corta ahí, sin pedir más páginas.
    assert transport.calls[2].params == {"part": "snippet,statistics", "id": "v2"}
    second = posts[1]
    assert (second.external_id, second.text, second.permalink) == (
        "v2",
        "Video v2",
        "https://www.youtube.com/watch?v=v2",
    )
    assert (second.view_count, second.like_count, second.comment_count, second.media_type) == (
        5,
        2,
        1,
        "video",
    )
    # Likes ocultos o comentarios desactivados: el contador no viene, y no es cero.
    assert (posts[0].like_count, posts[0].comment_count) == (None, None)


async def test_el_tope_y_un_canal_sin_playlist(transport: FakeTransport, client: YouTubeClient) -> None:
    transport.on("GET", "playlistItems", {"items": [_item("v3", 22), _item("v2", 20)]})
    transport.on("GET", "videos", {"items": [_video("v3")]})
    posts = await YouTubeContentReader(client).list_posts(CHANNEL, TOKEN, window=TimeWindow(), limit=1)
    assert [post.external_id for post in posts] == ["v3"]

    # Un activo guardado sin la playlist la busca; un canal que nunca subió nada no tiene.
    transport.calls.clear()
    bare = Asset("a1", "c1", CHANNEL.provider, "dueño", YOUTUBE_CHANNEL, CHANNEL.external_id)
    transport.on("GET", "channels", {"items": [{"id": CHANNEL.external_id, "contentDetails": {}}]})
    assert await YouTubeContentReader(client).list_posts(bare, TOKEN, window=TimeWindow(), limit=None) == []
    assert [call.path for call in transport.calls] == ["channels"]


# ── Comentarios ─────────────────────────────────────────────────────────────────────────────────


def _comment(comment_id: str, text: str, **extra: object) -> dict[str, object]:
    snippet = {
        "textDisplay": text,
        "authorDisplayName": "Ana",
        "authorChannelId": {"value": "UCana"},
        "likeCount": 3,
        "publishedAt": "2026-11-20T10:00:00Z",
        **extra,
    }
    return {"id": comment_id, "snippet": snippet}


async def test_leer_comentarios_con_sus_respuestas(transport: FakeTransport, client: YouTubeClient) -> None:
    thread = {
        "snippet": {"topLevelComment": _comment("c1", "¡Qué bueno!"), "totalReplyCount": 4},
        "replies": {"comments": [_comment("c1.r1", "Gracias", moderationStatus="heldForReview")]},
    }
    transport.on(
        "GET",
        "commentThreads",
        {"items": [thread, {"snippet": {}}], "nextPageToken": "pag-2"},
        {"items": [{"snippet": {"topLevelComment": _comment("c2", "Otro")}}]},
    )
    comments = await YouTubeCommentGateway(client).list_comments(CHANNEL, TOKEN, object_id="v1")
    assert [c.external_id for c in comments] == ["c1", "c2"]
    first = comments[0]
    assert (first.text, first.author_id, first.author_name, first.like_count) == (
        "¡Qué bueno!",
        "UCana",
        "Ana",
        3,
    )
    # Puede venir solo una parte de las respuestas: el total está aparte.
    assert (first.reply_count, len(first.replies), first.object_external_id) == (4, 1, "v1")
    assert (first.replies[0].object_external_id, first.replies[0].hidden) == ("c1", True)
    assert first.hidden is None
    assert transport.calls[0].params == {
        "part": "snippet,replies",
        "videoId": "v1",
        "maxResults": 100,
        "textFormat": "plainText",
    }
    assert transport.calls[1].params["pageToken"] == "pag-2"


async def test_un_video_con_los_comentarios_desactivados_no_es_un_error(
    transport: FakeTransport, client: YouTubeClient
) -> None:
    transport.on("GET", "commentThreads", failure("commentsDisabled"))
    assert await YouTubeCommentGateway(client).list_comments(CHANNEL, TOKEN, object_id="v1") == []
    transport.routes.clear()
    # Otro 403 sí lo es.
    transport.on("GET", "commentThreads", failure("insufficientPermissions"))
    with pytest.raises(PermissionMissing):
        await YouTubeCommentGateway(client).list_comments(CHANNEL, TOKEN, object_id="v1")


async def test_responder_y_moderar(transport: FakeTransport, client: YouTubeClient) -> None:
    gateway = YouTubeCommentGateway(client)
    transport.on("POST", "comments", {"id": "c1.r9"}, {})
    transport.on("POST", "comments/setModerationStatus", HttpResponse(204, None, ""))
    assert await gateway.reply(CHANNEL, TOKEN, comment_id="c1", text="¡Gracias!") == "c1.r9"
    assert transport.calls[0].json == {"snippet": {"parentId": "c1", "textOriginal": "¡Gracias!"}}
    with pytest.raises(ProviderError, match="id de la respuesta"):
        await gateway.reply(CHANNEL, TOKEN, comment_id="c1", text="otra")

    await gateway.set_hidden(CHANNEL, TOKEN, comment_id="c1", hidden=True)
    await gateway.set_hidden(CHANNEL, TOKEN, comment_id="c1", hidden=False)
    await gateway.delete(CHANNEL, TOKEN, comment_id="c1")
    # Ocultar se puede deshacer (retener); borrar no (rechazar).
    assert [call.params["moderationStatus"] for call in transport.calls[2:]] == [
        "heldForReview",
        "published",
        "rejected",
    ]
    transport.routes.clear()
    transport.on("POST", "comments/setModerationStatus", failure("insufficientPermissions"))
    with pytest.raises(PermissionMissing):
        await gateway.set_hidden(CHANNEL, TOKEN, comment_id="c1", hidden=True)


async def test_la_api_no_deja_dar_like_a_un_comentario(client: YouTubeClient) -> None:
    gateway = YouTubeCommentGateway(client)
    assert not gateway.supports(CHANNEL, CommentAction.LIKE)
    assert all(
        gateway.supports(CHANNEL, a) for a in (CommentAction.REPLY, CommentAction.HIDE, CommentAction.DELETE)
    )
    with pytest.raises(ProviderError, match="like"):
        await gateway.like(CHANNEL, TOKEN, comment_id="c1")


# ── Métricas ────────────────────────────────────────────────────────────────────────────────────


async def test_los_contadores_del_canal(transport: FakeTransport, client: YouTubeClient) -> None:
    reader = YouTubeInsightsReader(client, FakeClock())
    transport.on("GET", "channels", OWN_CHANNEL)
    series = await reader.read(
        CHANNEL,
        TOKEN,
        metrics=["subscriberCount", "videoCount", "inventada"],
        period=Period.DAY,
        window=TimeWindow(),
    )
    assert [(s.name, s.period, s.points[0].value, s.points[0].end_time) for s in series] == [
        ("subscriberCount", Period.LIFETIME, 1230.0, NOW),
        ("videoCount", Period.LIFETIME, 42.0, NOW),
    ]
    assert transport.calls[0].params == {"part": "statistics", "mine": "true"}
    assert (
        reader.catalog.native_for(YOUTUBE_CHANNEL, CanonicalMetric.FOLLOWERS, reader.api_version)
        == "subscriberCount"
    )
    # Sin nada que pedir, no se llama.
    assert (
        await reader.read(CHANNEL, TOKEN, metrics=["inventada"], period=Period.DAY, window=TimeWindow()) == []
    )
    assert len(transport.calls) == 1


# ── Perfiles públicos ───────────────────────────────────────────────────────────────────────────


async def test_perfil_publico_con_la_clave_de_api(transport: FakeTransport, client: YouTubeClient) -> None:
    lookup = YouTubeProfileLookup(client)
    assert lookup.networks == frozenset({Network.YOUTUBE})
    assert lookup.viewer_kinds(Network.YOUTUBE) == frozenset()
    transport.on("GET", "channels", OWN_CHANNEL, {"items": []})
    profile = await lookup.lookup(_handle("@micanal"), viewer=None, token=None)
    assert profile is not None
    assert (profile.external_id, profile.username, profile.name, profile.followers, profile.posts) == (
        "UC1234567890123456789012",
        "@micanal",
        "Mi canal",
        1230,
        42,
    )
    assert profile.url == "https://www.youtube.com/channel/UC1234567890123456789012"
    assert transport.calls[0].params == {
        "part": "snippet,statistics",
        "forHandle": "@micanal",
        "key": "clave",
    }
    assert transport.calls[0].headers is None

    by_id = _handle("UC1234567890123456789012")
    assert await lookup.lookup(by_id, viewer=None, token=None) is None
    assert transport.calls[1].params["id"] == "UC1234567890123456789012"


async def test_un_canal_que_oculta_sus_suscriptores(transport: FakeTransport, client: YouTubeClient) -> None:
    hidden = {"items": [{"id": "UCx", "statistics": {"hiddenSubscriberCount": True, "subscriberCount": "0"}}]}
    transport.on("GET", "channels", hidden)
    profile = await YouTubeProfileLookup(client).lookup(_handle("@oculto"), viewer=None, token=None)
    assert profile is not None
    assert profile.followers is None


async def test_sin_clave_de_api_no_hay_perfiles_publicos(transport: FakeTransport) -> None:
    without = YouTubeClient(config(api_key=None), transport)
    with pytest.raises(ProviderError, match="clave de API"):
        await without.get_public("channels", {"part": "snippet"})
    assert youtube_provider(config(api_key=None), transport).profiles is None
