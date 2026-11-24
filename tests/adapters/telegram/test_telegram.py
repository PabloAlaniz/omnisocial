"""Conectar un bot, publicar, conversar y recibir avisos, con una API falsa."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from omniwebhook import IncomingRequest

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.telegram.client import TelegramClient, Upload, multipart
from omnisocial.adapters.providers.telegram.config import TelegramOptions
from omnisocial.adapters.providers.telegram.provider import telegram_provider, telegram_webhooks
from omnisocial.adapters.providers.telegram.sending import TelegramMessagingGateway, TelegramPublisher
from omnisocial.adapters.providers.telegram.session import (
    TelegramAssetDirectory,
    TelegramIdentity,
    TelegramSession,
)
from omnisocial.adapters.providers.telegram.spec import BOT_LIMITS
from omnisocial.adapters.providers.telegram.webhooks import TelegramWebhookParser, secret_for
from omnisocial.domain.errors import NotPublished, ProviderError, RateLimited, TokenRejected
from omnisocial.domain.inbox import InboxKind, from_event
from omnisocial.domain.messaging import AttachmentKind, OutboundMessage
from omnisocial.domain.publishing import (
    BytesFile,
    Draft,
    DraftIssue,
    Media,
    MediaKind,
    PublicationStatus,
    check_draft,
)
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.webhooks import EventAction, EventKind
from omnisocial.testing import FakeTransport
from tests.adapters.telegram.conftest import (
    BOT,
    BOT_ID,
    BOT_TOKEN,
    ME,
    TOKEN,
    WEBHOOK_SECRET,
    config,
    failure,
    message,
    ok,
    update,
)
from tests.fakes import SequentialIds

CHANNEL = TelegramOptions("@micanal")
PHOTO = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/foto.jpg")
FILE = Media(MediaKind.IMAGE, file=BytesFile(b"JPG-datos", "image/jpeg"))
CLIP = Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/clip.mp4")
PRIVATE = {"id": 555, "type": "private", "first_name": "Ana"}


@pytest.fixture
def publisher(client: TelegramClient) -> TelegramPublisher:
    return TelegramPublisher(client, SequentialIds("x"))


@pytest.fixture
def gateway(client: TelegramClient) -> TelegramMessagingGateway:
    return TelegramMessagingGateway(client, SequentialIds("x"))


# ── Conectar ────────────────────────────────────────────────────────────────────────────────────


async def test_un_bot_se_conecta_con_su_token(transport: FakeTransport, client: TelegramClient) -> None:
    transport.on("POST", "getMe", ok(ME))
    session = TelegramSession(client)
    assert [(field.name, field.secret) for field in session.fields] == [("token", True)]
    token = await session.login({"token": f"  {BOT_TOKEN} "})
    # El token no vence ni se renueva.
    assert (token.access_token, token.expires_at, session.can_refresh(token)) == (BOT_TOKEN, None, False)
    with pytest.raises(ProviderError, match="no se renueva"):
        await session.refresh(token)
    await session.revoke(token)
    identity = await TelegramIdentity(client).identity(token)
    assert (identity.external_id, identity.name) == (BOT_ID, "mitienda_bot")
    [asset] = await TelegramAssetDirectory(client).discover(token)
    assert (asset.kind, asset.external_id, asset.name, asset.metadata) == (
        "telegram_bot",
        BOT_ID,
        "@mitienda_bot",
        {"username": "mitienda_bot"},
    )
    # Consultar quién es el bot se puede repetir.
    assert all(call.retry_safe is not None for call in transport.calls)


async def test_lo_que_no_tiene_forma_de_token_no_se_manda_a_ningun_lado(
    transport: FakeTransport, client: TelegramClient
) -> None:
    session = TelegramSession(client)
    for wrong in ("hola", "123:corto", "../../getMe?x=1", f"{BOT_TOKEN}/getMe"):
        with pytest.raises(TokenRejected, match="forma de un token"):
            await session.login({"token": wrong})
        with pytest.raises(TokenRejected, match="forma de un token"):
            await client.get(wrong, "getMe")
    assert transport.calls == []
    transport.on("POST", "getMe", failure(401, "Unauthorized"), ok({"first_name": "sin id"}), ok([]))
    with pytest.raises(TokenRejected):
        await session.login({"token": BOT_TOKEN})
    with pytest.raises(ProviderError, match="id del bot"):
        await TelegramIdentity(client).identity(TOKEN)
    with pytest.raises(ProviderError, match="inesperado"):
        await client.get(BOT_TOKEN, "getMe")


async def test_un_bot_sin_nombre_de_usuario_usa_su_nombre(
    transport: FakeTransport, client: TelegramClient
) -> None:
    transport.on("POST", "getMe", ok({"id": 7001234567, "first_name": "Mi Tienda"}))
    [asset] = await TelegramAssetDirectory(client).discover(TOKEN)
    assert (asset.name, asset.metadata) == ("Mi Tienda", {})


# ── Publicar ────────────────────────────────────────────────────────────────────────────────────


async def test_un_texto_en_un_canal(transport: FakeTransport, publisher: TelegramPublisher) -> None:
    transport.on("POST", "sendMessage", ok(message(41)))
    options = TelegramOptions(
        "@micanal", parse_mode="HTML", silent=True, protect=True, disable_preview=True, thread_id=7
    )
    outcome = await publisher.publish(BOT, TOKEN, draft=Draft("<b>Abrimos</b> el sábado", options=options))
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        "@micanal:41",
        "https://t.me/micanal/41",
    )
    call = transport.calls[0]
    assert call.json == {
        "chat_id": "@micanal",
        "parse_mode": "HTML",
        "disable_notification": True,
        "protect_content": True,
        "message_thread_id": 7,
        "link_preview_options": {"is_disabled": True},
        "text": "<b>Abrimos</b> el sábado",
    }
    # Publicar no es repetible: un reintento automático lo duplicaría.
    assert call.retry_safe is None


async def test_un_medio_con_el_texto_al_pie(transport: FakeTransport, publisher: TelegramPublisher) -> None:
    private = {"id": -1009, "type": "channel", "title": "Privado"}
    transport.on("POST", "sendPhoto", ok(message(42, private)))
    transport.on("POST", "sendVideo", ok(message(43)))
    outcome = await publisher.publish(
        BOT, TOKEN, draft=Draft("El local nuevo", media=(PHOTO,), options=TelegramOptions("-1009"))
    )
    # Un canal sin nombre público no tiene una dirección que se pueda armar.
    assert (outcome.post_id, outcome.url) == ("-1009:42", None)
    assert transport.calls[0].json == {
        "chat_id": -1009,
        "photo": "https://cdn.ejemplo.com/foto.jpg",
        "caption": "El local nuevo",
    }
    await publisher.publish(BOT, TOKEN, draft=Draft("", media=(CLIP,), options=CHANNEL))
    assert transport.calls[1].json == {"chat_id": "@micanal", "video": "https://cdn.ejemplo.com/clip.mp4"}


async def test_un_archivo_viaja_en_el_pedido(transport: FakeTransport, publisher: TelegramPublisher) -> None:
    transport.on("POST", "sendPhoto", ok(message(44)))
    await publisher.publish(BOT, TOKEN, draft=Draft("Foto", media=(FILE,), options=CHANNEL))
    call = transport.calls[0]
    assert call.headers == {"Content-Type": "multipart/form-data; boundary=omnisocial-x1"}
    assert call.content == multipart(
        "omnisocial-x1",
        {"chat_id": "@micanal", "photo": "attach://file0", "caption": "Foto"},
        [Upload("file0", b"JPG-datos", "image/jpeg")],
    )


async def test_un_album_con_el_texto_en_el_primero(
    transport: FakeTransport, publisher: TelegramPublisher
) -> None:
    transport.on("POST", "sendMediaGroup", ok([message(50), message(51), message(52)]))
    options = TelegramOptions("@micanal", parse_mode="HTML")
    outcome = await publisher.publish(
        BOT, TOKEN, draft=Draft("<i>Tres</i>", media=(PHOTO, FILE, CLIP), options=options)
    )
    assert (outcome.post_id, outcome.url) == ("@micanal:50,51,52", "https://t.me/micanal/50")
    content = transport.calls[0].content
    assert content is not None
    album = [
        {
            "type": "photo",
            "media": "https://cdn.ejemplo.com/foto.jpg",
            "caption": "<i>Tres</i>",
            "parse_mode": "HTML",
        },
        {"type": "photo", "media": "attach://file1"},
        {"type": "video", "media": "https://cdn.ejemplo.com/clip.mp4"},
    ]
    assert json.dumps(album).encode() in content
    assert content.count(b'form-data; name="file1"') == 1
    assert b"JPG-datos" in content


async def test_un_texto_que_no_entra_al_pie_sale_aparte(
    transport: FakeTransport, publisher: TelegramPublisher
) -> None:
    long = "x" * 1025
    transport.on("POST", "sendPhoto", ok(message(60)))
    transport.on("POST", "sendMessage", ok(message(61)), failure(400, "Bad Request: message is too long"))
    options = TelegramOptions("@micanal", parse_mode="HTML")
    outcome = await publisher.publish(BOT, TOKEN, draft=Draft(long, media=(PHOTO,), options=options))
    assert (outcome.status, outcome.post_id) == (PublicationStatus.PUBLISHED, "@micanal:60,61")
    photo, text = transport.calls
    assert photo.json == {"chat_id": "@micanal", "photo": "https://cdn.ejemplo.com/foto.jpg"}
    assert text.json == {
        "chat_id": "@micanal",
        "parse_mode": "HTML",
        "text": long,
        "reply_parameters": {"message_id": 60},
    }
    # Si el texto falla, la foto ya salió: no es un fracaso, y repetir la duplicaría.
    partial = await publisher.publish(BOT, TOKEN, draft=Draft(long, media=(PHOTO,), options=CHANNEL))
    assert (partial.status, partial.post_id) == (PublicationStatus.PUBLISHED_WITH_ERROR, "@micanal:60")
    assert "El texto no salió" in (partial.error or "")


@pytest.mark.parametrize(
    ("answer", "error", "certain"),
    [
        (failure(400, "Bad Request: chat not found"), ProviderError, True),
        (failure(403, "Forbidden: bot is not a member of the channel chat"), ProviderError, True),
        (failure(429, "Too Many Requests: retry after 7", retry_after=7), RateLimited, True),
        (failure(401, "Unauthorized"), TokenRejected, True),
        (failure(404, "Not Found"), NotPublished, True),
        # Un 5xx, un corte o una respuesta sin id: no se sabe, y no se afirma que no salió.
        (HttpResponse(502, None, "Bad Gateway"), ProviderError, False),
        (TransportError("se cortó"), TransportError, False),
        (ok({}), ProviderError, False),
    ],
)
async def test_solo_un_rechazo_es_certeza(
    transport: FakeTransport,
    publisher: TelegramPublisher,
    answer: object,
    error: type[Exception],
    certain: bool,
) -> None:
    transport.on("POST", "sendMessage", answer)
    with pytest.raises(error) as raised:
        await publisher.publish(BOT, TOKEN, draft=Draft("Hola", options=CHANNEL))
    assert type(raised.value) is error
    kind = getattr(raised.value, "kind", None)
    says_why = kind is not None and kind.value in {"invalid_request", "rate_limited"}
    assert (isinstance(raised.value, NotPublished | TokenRejected) or says_why) is certain
    if isinstance(raised.value, RateLimited):
        assert raised.value.retry_after == 7.0
    # El token va en la URL: nunca en el mensaje de un error.
    assert BOT_TOKEN not in str(raised.value)


async def test_borrar_retomar_y_publicar_sin_chat(
    transport: FakeTransport, publisher: TelegramPublisher
) -> None:
    transport.on("POST", "deleteMessage", ok(True))
    await publisher.delete(BOT, TOKEN, post_id="-1009:50,51")
    assert [call.json for call in transport.calls] == [
        {"chat_id": -1009, "message_id": 50},
        {"chat_id": -1009, "message_id": 51},
    ]
    with pytest.raises(ProviderError, match="una sola etapa"):
        await publisher.resume(BOT, TOKEN, resume={})
    with pytest.raises(ProviderError, match="chat"):
        await publisher.publish(BOT, TOKEN, draft=Draft("Hola"))
    with pytest.raises(ValueError, match="chat_id"):
        TelegramOptions("  ")


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("x" * 4096, media=(PHOTO,) * 5 + (CLIP,) * 5, options=CHANNEL), BOT_LIMITS) == ()
    problems = {
        "sin chat": Draft("hola"),
        "largo": Draft("x" * 4097, options=CHANNEL),
        "muchos": Draft("", media=(PHOTO,) * 6 + (CLIP,) * 5, options=CHANNEL),
    }
    assert {name: [p.issue for p in check_draft(draft, BOT_LIMITS)] for name, draft in problems.items()} == {
        "sin chat": [DraftIssue.OPTIONS_REQUIRED],
        "largo": [DraftIssue.TEXT_TOO_LONG],
        "muchos": [DraftIssue.TOO_MANY_MEDIA],
    }


# ── Conversar ───────────────────────────────────────────────────────────────────────────────────


async def test_escribirle_a_quien_le_escribio_al_bot(
    transport: FakeTransport, gateway: TelegramMessagingGateway
) -> None:
    transport.on("POST", "sendMessage", ok(message(9, PRIVATE)), ok({}))
    transport.on("POST", "sendPhoto", ok(message(10, PRIVATE)))
    sent = await gateway.send(
        BOT, TOKEN, recipient_id="555", message=OutboundMessage("¡Hola!", reply_to="555:8")
    )
    assert sent == "555:9"
    assert transport.calls[0].json == {
        "chat_id": 555,
        "reply_parameters": {"message_id": 8},
        "text": "¡Hola!",
    }
    photo = OutboundMessage("Mirá", attachments=(PHOTO,), reply_to="8")
    assert await gateway.send(BOT, TOKEN, recipient_id="555", message=photo) == "555:10"
    assert transport.calls[1].json == {
        "chat_id": 555,
        "reply_parameters": {"message_id": 8},
        "photo": "https://cdn.ejemplo.com/foto.jpg",
        "caption": "Mirá",
    }
    with pytest.raises(ProviderError, match="id del mensaje"):
        await gateway.send(BOT, TOKEN, recipient_id="555", message=OutboundMessage("Hola"))
    long = OutboundMessage("x" * 1025, attachments=(PHOTO,))
    with pytest.raises(ProviderError, match="1024"):
        await gateway.send(BOT, TOKEN, recipient_id="555", message=long)
    limits = gateway.limits_for(BOT)
    assert (limits.history, limits.templates, gateway.reply_window.duration) == (False, False, None)
    with pytest.raises(ProviderError, match="avisos"):
        await gateway.list_conversations(BOT, TOKEN, limit=None)
    with pytest.raises(ProviderError, match="avisos"):
        await gateway.list_messages(BOT, TOKEN, conversation_id="555", limit=None)


async def test_una_persona_que_bloqueo_al_bot(
    transport: FakeTransport, gateway: TelegramMessagingGateway
) -> None:
    transport.on("POST", "sendMessage", failure(403, "Forbidden: bot was blocked by the user"))
    with pytest.raises(ProviderError, match="blocked by the user") as blocked:
        await gateway.send(BOT, TOKEN, recipient_id="555", message=OutboundMessage("Hola"))
    # No es un token muerto ni un permiso que falte: la conexión sigue sana.
    assert blocked.value.kind.value == "invalid_request"


# ── Avisos ──────────────────────────────────────────────────────────────────────────────────────


def test_el_secreto_de_un_bot_no_sirve_para_otro() -> None:
    verifier = TelegramWebhookParser(WEBHOOK_SECRET).verifier
    good = verifier.verify(update({"update_id": 100}))
    assert (good.outcome, getattr(good, "event_key", None)) == ("ok", f"telegram:{BOT_ID}:100")
    stolen = secret_for(WEBHOOK_SECRET, BOT_ID)
    assert verifier.verify(update({"update_id": 100}, bot="999", secret=stolen)).outcome == "invalid"
    assert verifier.verify(update({"update_id": 100}, secret="otro")).outcome == "invalid"
    assert (
        verifier.verify(IncomingRequest(headers=[], query=[("bot", BOT_ID)], body=b"{}")).outcome == "missing"
    )
    no_bot = IncomingRequest(headers=[("X-Telegram-Bot-Api-Secret-Token", stolen)], query=[], body=b"{}")
    assert verifier.verify(no_bot).outcome == "missing"
    twice = IncomingRequest(
        headers=[("X-Telegram-Bot-Api-Secret-Token", stolen)],
        query=[("bot", BOT_ID), ("bot", "999")],
        body=b"{}",
    )
    assert verifier.verify(twice).outcome == "ambiguous"
    broken = update({"update_id": 1})
    broken = IncomingRequest(headers=broken.headers, query=broken.query, body=b"<html>")
    assert verifier.verify(broken).outcome == "malformed"
    # Sin número de aviso, la clave es la huella del cuerpo.
    assert verifier.verify(update({"otra": "cosa"})).outcome == "ok"
    assert TelegramWebhookParser(None).verifier.verify(update({"update_id": 1})).outcome == "unconfigured"
    assert TelegramWebhookParser(WEBHOOK_SECRET).handshake({"hub.mode": "subscribe"}) is None


def _parse(payload: dict[str, object]) -> list[object]:
    request = update(payload)
    return list(TelegramWebhookParser(WEBHOOK_SECRET).parse(request.body, query={"bot": BOT_ID}))


def test_un_mensaje_privado_con_adjuntos() -> None:
    incoming = message(
        8,
        PRIVATE,
        **{"from": {"id": 555, "first_name": "Ana", "last_name": "Pérez"}},
        caption="Mirá",
        photo=[{"file_id": "chica"}, {"file_id": "grande"}],
        document={"file_id": "doc-1", "mime_type": "application/pdf", "file_name": "factura.pdf"},
        location={"latitude": -34.6, "longitude": -58.4},
    )
    [event] = _parse({"update_id": 1, "message": incoming})
    assert (event.kind, event.action, event.asset_external_id, event.object_external_id) == (  # type: ignore[attr-defined]
        EventKind.MESSAGE,
        EventAction.CREATED,
        BOT_ID,
        "555:8",
    )
    assert (event.actor_id, event.actor_name, event.conversation_external_id, event.text) == (  # type: ignore[attr-defined]
        "555",
        "Ana Pérez",
        "555",
        "Mirá",
    )
    assert event.occurred_at == datetime.fromtimestamp(1795000000, UTC)  # type: ignore[attr-defined]
    kinds = [(a.kind, a.media_id, a.name) for a in event.attachments]  # type: ignore[attr-defined]
    assert kinds == [
        (AttachmentKind.IMAGE, "grande", None),
        (AttachmentKind.FILE, "doc-1", "factura.pdf"),
        (AttachmentKind.LOCATION, None, None),
    ]
    item = from_event(event)  # type: ignore[arg-type]
    assert item is not None
    assert (item.kind, item.thread_external_id) == (InboxKind.MESSAGE, "555")


def test_canales_grupos_y_ediciones() -> None:
    post = message(70, sender_chat={"id": -1001234567890, "title": "Mi Canal"}, text="Novedades")
    [posted] = _parse({"update_id": 2, "channel_post": post})
    assert (posted.kind, posted.actor_name, posted.text) == (EventKind.POST, "Mi Canal", "Novedades")  # type: ignore[attr-defined]
    group = {"id": -200, "type": "supergroup", "title": "Clientes"}
    said = message(
        71, group, **{"from": {"id": 9, "username": "beto"}}, text="¿Abren hoy?", edit_date=1795000500
    )
    [edited] = _parse({"update_id": 3, "edited_message": said})
    # Lo que se escribe en un grupo es parte de una charla de varios: va como comentario.
    assert (edited.kind, edited.action, edited.actor_name) == (EventKind.COMMENT, EventAction.UPDATED, "beto")  # type: ignore[attr-defined]
    assert edited.occurred_at == datetime.fromtimestamp(1795000500, UTC)  # type: ignore[attr-defined]
    assert from_event(edited) is None  # type: ignore[arg-type]


def test_cuando_suman_o_sacan_al_bot_de_un_chat() -> None:
    change = {
        "chat": {"id": -1001234567890, "type": "channel", "title": "Mi Canal"},
        "from": {"id": 9, "first_name": "Beto"},
        "date": 1795000000,
        "old_chat_member": {"status": "left"},
        "new_chat_member": {"status": "administrator", "can_post_messages": True},
    }
    [joined] = _parse({"update_id": 4, "my_chat_member": change})
    assert (joined.kind, joined.action, joined.text, joined.conversation_external_id) == (  # type: ignore[attr-defined]
        EventKind.OTHER,
        EventAction.UPDATED,
        "administrator",
        "-1001234567890",
    )
    assert _parse({"update_id": 5, "my_chat_member": {"chat": {}}}) == []
    assert _parse({"update_id": 6, "message": {"chat": {"id": 1}}}) == []
    assert _parse({"update_id": 7, "poll": {}}) == []
    parser = TelegramWebhookParser(WEBHOOK_SECRET)
    assert parser.parse(b"<html>", query={"bot": BOT_ID}) == []
    # Sin saber de qué bot es, no se puede enrutar.
    assert parser.parse(b'{"update_id": 1, "message": {}}') == []


async def test_registrar_la_url_de_los_avisos_de_un_bot(transport: FakeTransport) -> None:
    webhooks = telegram_webhooks(config(), transport)
    transport.on("POST", "getMe", ok(ME))
    transport.on("POST", "setWebhook", ok(True))
    transport.on("POST", "deleteWebhook", ok(True))
    target = await webhooks.register(TOKEN, "https://api.ejemplo.com/webhooks/telegram?v=1")
    assert target == f"https://api.ejemplo.com/webhooks/telegram?v=1&bot={BOT_ID}"
    registered = transport.calls[-1].json
    assert registered is not None
    assert (registered["url"], registered["secret_token"]) == (target, secret_for(WEBHOOK_SECRET, BOT_ID))
    assert "my_chat_member" in registered["allowed_updates"]  # type: ignore[operator]
    await webhooks.remove(TOKEN)
    with pytest.raises(ProviderError, match="webhook_secret"):
        await telegram_webhooks(config(webhook_secret=None), transport).register(
            TOKEN, "https://api.ejemplo.com/t"
        )


async def test_el_proveedor_trae_todo(transport: FakeTransport) -> None:
    provider = telegram_provider(config(), transport)
    assert provider.oauth is None
    assert provider.credentials is not None
    assert provider.refresher is provider.credentials
    assert Token(TokenKind.USER, BOT_TOKEN).access_token not in repr(config())
