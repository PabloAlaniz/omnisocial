"""Discord por bot y por webhook de canal, con una API falsa."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.discord.bot import (
    DiscordAssetDirectory,
    DiscordBot,
    DiscordIdentity,
    DiscordLookups,
    DiscordPublisher,
    discord_oauth,
)
from omnisocial.adapters.providers.discord.client import DiscordClient
from omnisocial.adapters.providers.discord.config import (
    DISCORD,
    DISCORD_WEBHOOK,
    DiscordOptions,
    DiscordWebhookOptions,
)
from omnisocial.adapters.providers.discord.provider import discord_provider, discord_webhook_provider
from omnisocial.adapters.providers.discord.spec import ERRORS, GUILD_LIMITS, WEBHOOK_ERRORS, WEBHOOK_LIMITS
from omnisocial.adapters.providers.discord.webhook import (
    DiscordWebhookAssets,
    DiscordWebhookIdentity,
    DiscordWebhookPublisher,
    DiscordWebhookSession,
)
from omnisocial.domain.errors import (
    NotPublished,
    PermissionMissing,
    ProviderError,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.lookup import Choice
from omnisocial.domain.publishing import (
    BytesFile,
    Draft,
    DraftIssue,
    Media,
    MediaKind,
    PublicationStatus,
    check_draft,
)
from omnisocial.domain.spec import Pace
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport
from tests.adapters.discord.conftest import (
    AGENT,
    BOT,
    BOT_GUILDS,
    CHANNEL,
    CHANNELS,
    GUILD,
    HOOK,
    HOOK_INFO,
    MY_GUILDS,
    TOKEN,
    USER,
    WEBHOOK,
    WEBHOOK_URL,
    config,
    failure,
    webhook_config,
)
from tests.fakes import FakeClock, SequentialIds

WHERE = DiscordOptions("500")
PHOTO = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/foto.jpg")
FILE = Media(MediaKind.IMAGE, file=BytesFile(b"PNG-datos", "image/png"), alt_text="El local")
CLIP = Media(MediaKind.VIDEO, file=BytesFile(b"MP4-datos", "video/mp4"))
CREATED = {"id": "7001", "channel_id": "500", "content": "Hola"}


def _client(transport: FakeTransport) -> DiscordClient:
    return DiscordClient(
        transport, api_base="https://discord.com/api/v10", user_agent=AGENT, provider=DISCORD, errors=ERRORS
    )


def _hook_client(transport: FakeTransport) -> DiscordClient:
    return DiscordClient(
        transport,
        api_base="https://discord.com/api/v10",
        user_agent=AGENT,
        provider=DISCORD_WEBHOOK,
        errors=WEBHOOK_ERRORS,
    )


@pytest.fixture
def bot(transport: FakeTransport) -> DiscordBot:
    return DiscordBot(_client(transport), config())


@pytest.fixture
def publisher(bot: DiscordBot) -> DiscordPublisher:
    return DiscordPublisher(bot, SequentialIds("nonce-"))


@pytest.fixture
def hook(transport: FakeTransport) -> DiscordWebhookPublisher:
    return DiscordWebhookPublisher(_hook_client(transport))


# ── Login y servidores ──────────────────────────────────────────────────────────────────────────


async def test_al_autorizar_se_suma_el_bot_con_sus_permisos(transport: FakeTransport) -> None:
    client = _client(transport)
    oauth = discord_oauth(client, config(), FakeClock())
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://app.ejemplo.com/cb",
        scopes=("identify", "guilds", "bot"),
        code_challenge="reto",
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://discord.com/oauth2/authorize?")
    # Ver canales, escribir, mostrar links y adjuntar archivos.
    assert (query["permissions"], query["scope"], query["code_challenge"]) == (
        ["52224"],
        ["identify guilds bot"],
        ["reto"],
    )
    transport.on(
        "POST",
        "oauth2/token",
        {"access_token": "a1", "refresh_token": "r1", "expires_in": 604800},
        {"access_token": "a2", "refresh_token": "r2", "expires_in": 604800},
    )
    transport.on("POST", "oauth2/token/revoke", HttpResponse(200, {}, ""))
    transport.on("GET", "users/@me", USER, {"username": "sin id"})
    token = await oauth.exchange_code(
        code="abc", redirect_uri="https://app.ejemplo.com/cb", code_verifier="v"
    )
    renewed = await oauth.refresh(token)
    assert (renewed.access_token, renewed.refresh_token) == ("a2", "r2")
    await oauth.revoke(renewed)
    identity = await oauth.identity(token)
    assert (identity.external_id, identity.name, identity.email, identity.avatar_url) == (
        "42",
        "Ana",
        "ana@ejemplo.com",
        "https://cdn.discordapp.com/avatars/42/a1b2.png",
    )
    # Todo pedido lleva el User-Agent que pide Discord, también el canje del código.
    assert all(call.headers is not None and call.headers["User-Agent"] == AGENT for call in transport.calls)
    exchange = transport.calls[0]
    assert exchange.headers is not None
    assert exchange.headers["Authorization"].startswith("Basic ")
    assert transport.calls[-1].headers["Authorization"] == "Bearer a1"  # type: ignore[index]
    with pytest.raises(ProviderError, match="id de la persona"):
        await DiscordIdentity(client).identity(token)
    assert "secreto" not in repr(config())
    assert "token-del-bot" not in repr(config())


async def test_los_servidores_que_la_persona_administra_y_donde_esta_el_bot(
    transport: FakeTransport, bot: DiscordBot
) -> None:
    transport.on("GET", "users/@me/guilds", MY_GUILDS, BOT_GUILDS)
    assets = await DiscordAssetDirectory(bot).discover(TOKEN)
    # Administra dos, pero el bot está en uno solo.
    assert [(a.kind, a.external_id, a.name) for a in assets] == [("discord_guild", "900", "Mi Comunidad")]
    mine, with_bot = transport.calls
    assert mine.headers is not None
    assert with_bot.headers is not None
    assert (mine.headers["Authorization"], with_bot.headers["Authorization"]) == ("Bearer acceso-de-ana", BOT)


async def test_sin_servidores_propios_no_se_le_pregunta_al_bot(
    transport: FakeTransport, bot: DiscordBot
) -> None:
    transport.on("GET", "users/@me/guilds", [MY_GUILDS[2]])
    assert await DiscordAssetDirectory(bot).discover(TOKEN) == []
    assert len(transport.calls) == 1


async def test_los_servidores_del_bot_se_recorren_de_a_doscientos(
    transport: FakeTransport, bot: DiscordBot
) -> None:
    first = [{"id": str(n)} for n in range(1000, 1200)]
    transport.on("GET", "users/@me/guilds", first, [{"id": "5"}])
    assert len(await bot.guild_ids()) == 201
    assert [call.params.get("after") for call in transport.calls] == [None, "1199"]


async def test_los_canales_donde_se_puede_publicar(transport: FakeTransport, bot: DiscordBot) -> None:
    transport.on("GET", "guilds/900/channels", CHANNELS)
    lookups = DiscordLookups(bot)
    found = await lookups.choices(GUILD, TOKEN, lookup="channels", query=None, parent=None)
    assert found == [
        Choice("500", "#general", data={"type": "text"}),
        Choice("501", "#anuncios", data={"type": "announcement"}),
        Choice("502", "#ideas", data={"type": "forum", "nsfw": "true"}),
    ]
    assert transport.calls[0].headers["Authorization"] == BOT  # type: ignore[index]
    assert await lookups.choices(GUILD, TOKEN, lookup="otra", query=None, parent=None) == []


# ── Publicar con el bot ─────────────────────────────────────────────────────────────────────────


async def test_un_mensaje_en_un_canal(transport: FakeTransport, publisher: DiscordPublisher) -> None:
    transport.on("POST", "channels/500/messages", CREATED)
    outcome = await publisher.publish(GUILD, TOKEN, draft=Draft("Hola @everyone", options=WHERE))
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        "500:7001",
        "https://discord.com/channels/900/500/7001",
    )
    call = transport.calls[0]
    assert call.json == {
        "content": "Hola @everyone",
        # Por defecto las menciones no avisan: un texto ajeno no puede notificar a todo el servidor.
        "allowed_mentions": {"parse": []},
        "nonce": "nonce1",
        "enforce_nonce": True,
    }
    assert call.headers is not None
    assert (call.headers["Authorization"], call.headers["User-Agent"]) == (BOT, AGENT)
    # Con el nonce Discord no publica dos veces: el transporte sí puede reintentar.
    assert call.retry_safe is not None


async def test_imagenes_incrustadas_archivos_adjuntos_y_opciones(
    transport: FakeTransport, publisher: DiscordPublisher
) -> None:
    transport.on("POST", "channels/500/messages", CREATED)
    options = DiscordOptions("500", mentions=True, silent=True, suppress_embeds=True, reply_to="6999")
    await publisher.publish(GUILD, TOKEN, draft=Draft("Mirá", media=(PHOTO, FILE, CLIP), options=options))
    call = transport.calls[0]
    assert call.content is not None
    assert call.headers is not None
    boundary = call.headers["Content-Type"].split("boundary=")[1]
    payload = json.loads(call.content.split(b"\r\n\r\n")[1].split(f"\r\n--{boundary}".encode())[0])
    assert payload == {
        "content": "Mirá",
        "flags": 4 | 4096,
        "embeds": [{"image": {"url": "https://cdn.ejemplo.com/foto.jpg"}}],
        "attachments": [
            {"id": 0, "filename": "archivo0.png", "description": "El local"},
            {"id": 1, "filename": "archivo1.mp4"},
        ],
        "message_reference": {"message_id": "6999"},
        "nonce": "nonce1",
        "enforce_nonce": True,
    }
    assert b'name="files[0]"; filename="archivo0.png"' in call.content
    assert b'name="files[1]"; filename="archivo1.mp4"' in call.content
    assert b"PNG-datos" in call.content
    # El mismo pedido, repetido, es idéntico: el separador sale del contenido.
    await publisher.publish(GUILD, TOKEN, draft=Draft("Mirá", media=(PHOTO, FILE, CLIP), options=options))
    assert transport.calls[1].headers["Content-Type"] == call.headers["Content-Type"]  # type: ignore[index]


async def test_una_publicacion_en_un_foro_y_un_anuncio_que_se_reparte(
    transport: FakeTransport, publisher: DiscordPublisher
) -> None:
    thread = {"id": "8000", "name": "Idea", "message": {"id": "8001", "channel_id": "8000"}}
    transport.on("POST", "channels/502/threads", thread)
    forum = DiscordOptions("502", thread_name="Idea: horario extendido")
    outcome = await publisher.publish(GUILD, TOKEN, draft=Draft("¿Qué opinan?", options=forum))
    assert (outcome.post_id, outcome.url) == ("8000:8001", "https://discord.com/channels/900/8000/8001")
    call = transport.calls[0]
    assert call.json == {
        "name": "Idea: horario extendido",
        "message": {"content": "¿Qué opinan?", "allowed_mentions": {"parse": []}},
    }
    # Un hilo no lleva nonce: no se reintenta solo.
    assert call.retry_safe is None

    transport.on("POST", "channels/501/messages", {"id": "7002", "channel_id": "501"})
    transport.on(
        "POST",
        "channels/501/messages/7002/crosspost",
        {"id": "7002"},
        failure(403, 50013, "Missing Permissions"),
    )
    news = DiscordOptions("501", crosspost=True)
    assert (await publisher.publish(GUILD, TOKEN, draft=Draft("Novedad", options=news))).status is (
        PublicationStatus.PUBLISHED
    )
    partial = await publisher.publish(GUILD, TOKEN, draft=Draft("Novedad", options=news))
    # Ya salió en el canal: que no se reparta no es un fracaso.
    assert (partial.status, partial.post_id) == (PublicationStatus.PUBLISHED_WITH_ERROR, "501:7002")
    assert "siguen el canal" in (partial.error or "")


@pytest.mark.parametrize(
    ("answer", "error", "certain"),
    [
        (failure(403, 50013, "Missing Permissions"), PermissionMissing, True),
        (failure(404, 10003, "Unknown Channel"), ProviderError, True),
        (failure(400, 50035, "Invalid Form Body"), ProviderError, True),
        (failure(429, 20016, "Slowmode", retry_after=4.5), RateLimited, True),
        # El token del bot no vale: es un problema de la app, no de la conexión de nadie.
        (failure(401, 0, "401: Unauthorized"), NotPublished, True),
        # Un 5xx, un corte o una respuesta sin id: no se sabe, y no se afirma que no salió.
        (HttpResponse(502, None, "Bad Gateway"), ProviderError, False),
        (TransportError("se cortó"), TransportError, False),
        ({"channel_id": "500"}, ProviderError, False),
    ],
)
async def test_solo_un_rechazo_es_certeza(
    transport: FakeTransport,
    publisher: DiscordPublisher,
    answer: object,
    error: type[Exception],
    certain: bool,
) -> None:
    transport.on("POST", "channels/500/messages", answer)
    with pytest.raises(error) as raised:
        await publisher.publish(GUILD, TOKEN, draft=Draft("Hola", options=WHERE))
    assert type(raised.value) is error
    assert not isinstance(raised.value, TokenRejected)
    kind = getattr(raised.value, "kind", None)
    says_why = kind is not None and kind.value in {"invalid_request", "rate_limited", "missing_permission"}
    assert (isinstance(raised.value, NotPublished) or says_why) is certain
    if isinstance(raised.value, RateLimited):
        assert raised.value.retry_after == 4.5


async def test_borrar_retomar_y_publicar_sin_canal(
    transport: FakeTransport, publisher: DiscordPublisher
) -> None:
    transport.on("DELETE", "channels/500/messages/7001", HttpResponse(204, None, ""), failure(401))
    await publisher.delete(GUILD, TOKEN, post_id="500:7001")
    with pytest.raises(ProviderError, match="token del bot") as dead:
        await publisher.delete(GUILD, TOKEN, post_id="500:7001")
    assert not isinstance(dead.value, TokenRejected)
    with pytest.raises(ProviderError, match="una sola etapa"):
        await publisher.resume(GUILD, TOKEN, resume={})
    with pytest.raises(ProviderError, match="canal"):
        await publisher.publish(GUILD, TOKEN, draft=Draft("Hola"))
    with pytest.raises(ValueError, match="channel_id"):
        DiscordOptions("#general")
    with pytest.raises(ValueError, match="100 caracteres"):
        DiscordOptions("500", thread_name="x" * 101)


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("x" * 2000, media=(PHOTO,) * 9 + (CLIP,), options=WHERE), GUILD_LIMITS) == ()
    assert check_draft(Draft("hola"), WEBHOOK_LIMITS) == ()
    by_url = Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/v.mp4")
    big = Media(MediaKind.IMAGE, file=BytesFile(b"x", "image/png"), size_bytes=None)
    problems = {
        "sin canal": Draft("hola"),
        "largo": Draft("x" * 2001, options=WHERE),
        "video por URL": Draft("", media=(by_url,), options=WHERE),
    }
    assert {
        name: [p.issue for p in check_draft(draft, GUILD_LIMITS)] for name, draft in problems.items()
    } == {
        "sin canal": [DraftIssue.OPTIONS_REQUIRED],
        "largo": [DraftIssue.TEXT_TOO_LONG],
        "video por URL": [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED],
    }
    assert check_draft(Draft("", media=(big,), options=WHERE), GUILD_LIMITS) == ()


# ── Por webhook de canal ────────────────────────────────────────────────────────────────────────


async def test_un_canal_se_conecta_pegando_la_url_de_su_webhook(transport: FakeTransport) -> None:
    client = _hook_client(transport)
    transport.on("GET", WEBHOOK, HOOK_INFO)
    session = DiscordWebhookSession(client)
    assert [(field.name, field.secret) for field in session.fields] == [("webhook_url", True)]
    token = await session.login({"webhook_url": f" {WEBHOOK_URL}/ "})
    # Lo que se guarda es el id y la clave: a dónde se hacen los pedidos lo decide la configuración.
    assert (token.access_token, session.can_refresh(token)) == ("111222333/clave-del_webhook", False)
    assert transport.calls[0].headers == {"User-Agent": AGENT}
    await session.revoke(token)
    with pytest.raises(ProviderError, match="no se renueva"):
        await session.refresh(token)
    identity = await DiscordWebhookIdentity(client).identity(token)
    assert (identity.provider, identity.external_id, identity.name) == (
        DISCORD_WEBHOOK,
        "111222333",
        "Novedades",
    )
    [asset] = await DiscordWebhookAssets(client).discover(token)
    assert (asset.kind, asset.external_id, asset.name, asset.parent_external_id, asset.metadata) == (
        "discord_webhook",
        "111222333",
        "Novedades",
        "900",
        {"channel_id": "500", "guild_id": "900"},
    )
    for other in (
        "https://canary.discord.com/api/v10/webhooks/1/abc",
        "https://discordapp.com/api/webhooks/1/abc",
    ):
        transport.on("GET", "webhooks/1/abc", HOOK_INFO)
        assert (await session.login({"webhook_url": other})).access_token == "1/abc"


async def test_lo_que_no_es_un_webhook_de_discord_no_se_pide(transport: FakeTransport) -> None:
    client = _hook_client(transport)
    session = DiscordWebhookSession(client)
    wrong = (
        "http://discord.com/api/webhooks/1/abc",
        "https://discord.com.ejemplo.com/api/webhooks/1/abc",
        "https://ejemplo.com/api/webhooks/1/abc",
        "https://discord.com/api/webhooks/1/abc/../../users/@me",
        "https://discord.com/api/webhooks/uno/abc",
        "169.254.169.254",
    )
    for url in wrong:
        with pytest.raises(TokenRejected, match="webhook de Discord"):
            await session.login({"webhook_url": url})
    with pytest.raises(TokenRejected, match="webhook de Discord"):
        await DiscordWebhookIdentity(client).identity(Token(TokenKind.USER, "../users/@me"))
    assert transport.calls == []
    transport.on("GET", WEBHOOK, failure(404, 10015, "Unknown Webhook"), {"name": "sin id"})
    with pytest.raises(TokenRejected):
        await session.login({"webhook_url": WEBHOOK_URL})
    with pytest.raises(ProviderError, match="no devolvió el webhook"):
        await DiscordWebhookAssets(client).discover(HOOK)


async def test_publicar_por_webhook(transport: FakeTransport, hook: DiscordWebhookPublisher) -> None:
    transport.on("POST", WEBHOOK, {"id": "7100", "channel_id": "500"}, {"id": "7101"})
    outcome = await hook.publish(CHANNEL, HOOK, draft=Draft("Abrimos el sábado"))
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        "7100",
        "https://discord.com/channels/900/500/7100",
    )
    call = transport.calls[0]
    assert (call.json, call.params) == (
        {"content": "Abrimos el sábado", "allowed_mentions": {"parse": []}},
        {"wait": "true"},
    )
    # No lleva credencial en una cabecera: la clave va en la ruta. Y no se reintenta solo.
    assert (call.headers, call.retry_safe) == ({"User-Agent": AGENT}, None)
    options = DiscordWebhookOptions(
        username="Mi Tienda",
        avatar_url="https://cdn.ejemplo.com/logo.png",
        thread_id="8000",
        thread_name="Tema",
    )
    again = await hook.publish(CHANNEL, HOOK, draft=Draft("Con foto", media=(FILE,), options=options))
    # Si la respuesta no dice el canal, queda el del webhook.
    assert again.url == "https://discord.com/channels/900/500/7101"
    upload = transport.calls[1]
    assert upload.params == {"wait": "true", "thread_id": "8000"}
    assert upload.content is not None
    assert b'"username": "Mi Tienda"' in upload.content
    assert b'"thread_name": "Tema"' in upload.content
    assert b"PNG-datos" in upload.content


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (failure(404, 10015, "Unknown Webhook"), TokenRejected),
        (failure(401, 50027, "Invalid Webhook Token"), TokenRejected),
        (failure(400, 50006, "Cannot send an empty message"), ProviderError),
        (failure(429, 0, "rate limited", retry_after=2), RateLimited),
        (failure(404, 10008, "Unknown Message"), ProviderError),
        (failure(418), NotPublished),
        (HttpResponse(503, None, "ups"), ProviderError),
        ({}, ProviderError),
    ],
)
async def test_un_webhook_borrado_deja_la_conexion_sin_valor(
    transport: FakeTransport, hook: DiscordWebhookPublisher, answer: object, error: type[Exception]
) -> None:
    transport.on("POST", WEBHOOK, answer)
    with pytest.raises(error) as raised:
        await hook.publish(CHANNEL, HOOK, draft=Draft("Hola"))
    assert type(raised.value) is error


async def test_borrar_lo_que_publico_el_webhook(
    transport: FakeTransport, hook: DiscordWebhookPublisher
) -> None:
    transport.on("DELETE", f"{WEBHOOK}/messages/7100", HttpResponse(204, None, ""))
    await hook.delete(CHANNEL, HOOK, post_id="7100")
    with pytest.raises(ProviderError, match="una sola etapa"):
        await hook.resume(CHANNEL, HOOK, resume={})


# ── Los proveedores ─────────────────────────────────────────────────────────────────────────────


def test_los_dos_proveedores(transport: FakeTransport) -> None:
    by_bot = discord_provider(config(), transport, pace=None)
    by_hook = discord_webhook_provider(webhook_config(), transport)
    assert (by_bot.id, by_hook.id) == (DISCORD, DISCORD_WEBHOOK)
    assert by_bot.spec is not None
    assert by_bot.spec.pace == Pace(max_concurrent=5)
    assert (by_hook.oauth, by_hook.lookups) == (None, None)
    assert by_hook.refresher is by_hook.credentials
