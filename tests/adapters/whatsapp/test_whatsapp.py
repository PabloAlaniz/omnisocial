"""Login, números, mensajes, plantillas y avisos, con una API falsa."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from omniwebhook import AsyncMemoryIdempotencyStore, IncomingRequest

from omnisocial.adapters.providers.whatsapp.client import WhatsAppClient
from omnisocial.adapters.providers.whatsapp.messaging import (
    WhatsAppAssetDirectory,
    WhatsAppLookups,
    WhatsAppMessagingGateway,
)
from omnisocial.adapters.providers.whatsapp.oauth import whatsapp_oauth
from omnisocial.adapters.providers.whatsapp.provider import whatsapp_provider
from omnisocial.adapters.providers.whatsapp.webhooks import WhatsAppWebhookParser
from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
)
from omnisocial.application.results import Connected, Done, Refusal, Refused
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import PermissionMissing, ProviderError, RateLimited, TokenRejected
from omnisocial.domain.inbox import InboxKind, from_event
from omnisocial.domain.lookup import Choice
from omnisocial.domain.messaging import (
    AttachmentKind,
    DeliveryStatus,
    OutboundMessage,
    Recipient,
    TemplateRef,
)
from omnisocial.domain.publishing import Media, MediaKind
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.domain.webhooks import EventAction, EventKind
from omnisocial.entrypoints.hub import Omnisocial
from omnisocial.testing import FakeTransport
from tests.adapters.whatsapp.conftest import (
    INSPECTED,
    ME,
    NUMBER,
    NUMBERS,
    SENT,
    TOKEN,
    config,
    failure,
    signed,
)
from tests.fakes import NOW, FakeClock

MESSAGES = "106540352242922/messages"
PHOTO = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/foto.jpg")
CLIP = Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/clip.mp4")


def webhook(value: Mapping[str, object], field: str = "messages") -> dict[str, object]:
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "5491155550100", "phone_number_id": "106540352242922"},
        **value,
    }
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "102290129340398", "changes": [{"field": field, "value": value}]}],
    }


INBOUND = {
    "contacts": [{"profile": {"name": "Ana"}, "wa_id": "5491155550199", "user_id": "AR.1349"}],
    "messages": [
        {
            "from": "5491155550199",
            "id": "wamid.A",
            "timestamp": "1795000000",
            "type": "text",
            "text": {"body": "Hola"},
        },
        {
            "from_user_id": "AR.1349",
            "id": "wamid.B",
            "timestamp": "1795000060",
            "type": "image",
            "image": {"id": "media-1", "mime_type": "image/jpeg", "caption": "Mirá"},
        },
        {
            "from": "5491155550199",
            "id": "wamid.C",
            "timestamp": "raro",
            "type": "document",
            "document": {"id": "media-2", "mime_type": "application/pdf", "filename": "factura.pdf"},
        },
        {"from": "5491155550199", "id": "wamid.D", "type": "location", "location": {"name": "El local"}},
        {"id": "wamid.sin-remitente", "type": "text"},
    ],
}


# ── Login y números ─────────────────────────────────────────────────────────────────────────────


async def test_el_login_usa_el_dialogo_de_facebook_con_la_configuracion(
    transport: FakeTransport,
) -> None:
    client = WhatsAppClient(config(config_id="cfg-1"), transport)
    oauth = whatsapp_oauth(client, FakeClock())
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://app.ejemplo.com/cb",
        scopes=("whatsapp_business_management", "whatsapp_business_messaging"),
        code_challenge=None,
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://www.facebook.com/v26.0/dialog/oauth?")
    assert (query["config_id"], query["scope"], oauth.supports_pkce) == (
        ["cfg-1"],
        ["whatsapp_business_management,whatsapp_business_messaging"],
        False,
    )
    transport.on("POST", "oauth/access_token", {"access_token": "EAAG-1", "token_type": "bearer"})
    transport.on("GET", "me", ME, {"name": "sin id"})
    token = await oauth.exchange_code(
        code="abc", redirect_uri="https://app.ejemplo.com/cb", code_verifier=None
    )
    # El token de una integración de negocio no trae vencimiento.
    assert (token.access_token, token.expires_at) == ("EAAG-1", None)
    identity = await oauth.identity(token)
    assert (identity.external_id, identity.name) == ("122100", "Usuario de sistema")
    with pytest.raises(ProviderError, match="dueño del token"):
        await oauth.identity(token)
    assert "secreto-de-la-app" not in repr(config())


async def test_los_numeros_de_las_cuentas_a_las_que_el_token_tiene_acceso(
    transport: FakeTransport, client: WhatsAppClient
) -> None:
    transport.on("GET", "debug_token", INSPECTED)
    transport.on("GET", "102290129340398/phone_numbers", NUMBERS)
    [number] = await WhatsAppAssetDirectory(client).discover(TOKEN)
    assert (number.kind, number.external_id, number.name, number.parent_external_id) == (
        "whatsapp_number",
        "106540352242922",
        "Mi Tienda",
        "102290129340398",
    )
    assert number.metadata == {"display_phone_number": "+54 9 11 5555-0100", "quality_rating": "GREEN"}
    inspect = transport.calls[0]
    # El token se inspecciona con las credenciales de la app.
    assert inspect.params == {"input_token": "EAAG-acceso"}
    assert inspect.headers == {"Authorization": "Bearer app|secreto-de-la-app"}
    # La misma cuenta aparece en los dos permisos: se pide una vez.
    assert len(transport.calls) == 2


async def test_un_token_con_acceso_a_todo_el_portfolio_lista_sus_cuentas(transport: FakeTransport) -> None:
    client = WhatsAppClient(config(business_id="900"), transport)
    transport.on(
        "GET", "debug_token", {"data": {"granular_scopes": [{"scope": "whatsapp_business_messaging"}]}}
    )
    transport.on(
        "GET",
        "900/owned_whatsapp_business_accounts",
        {"data": [{"id": "w1"}], "paging": {"cursors": {"after": "c1"}, "next": "https://…"}},
        {"data": [{"id": "w2"}, {}], "paging": {"cursors": {"after": "c2"}}},
    )
    transport.on("GET", "900/client_whatsapp_business_accounts", {"data": [{"id": "w1"}]})
    transport.on("GET", "w1/phone_numbers", {"data": [{"id": "n1", "display_phone_number": "+54 11 1"}]})
    transport.on("GET", "w2/phone_numbers", {"data": [{"id": "n2"}]})
    numbers = await WhatsAppAssetDirectory(client).discover(TOKEN)
    assert [(n.external_id, n.name, n.parent_external_id) for n in numbers] == [
        ("n1", "+54 11 1", "w1"),
        ("n2", None, "w2"),
    ]
    owned = [call for call in transport.calls if call.path == "900/owned_whatsapp_business_accounts"]
    assert [call.params.get("after") for call in owned] == [None, "c1"]
    # Sin portfolio configurado y sin cuentas en el token, no hay nada que conectar.
    bare = WhatsAppClient(config(), transport)
    assert await WhatsAppAssetDirectory(bare).discover(TOKEN) == []


# ── Mensajes ────────────────────────────────────────────────────────────────────────────────────


async def test_un_texto_citando_un_mensaje(transport: FakeTransport, client: WhatsAppClient) -> None:
    transport.on("POST", MESSAGES, SENT, {"messages": []})
    gateway = WhatsAppMessagingGateway(client)
    message = OutboundMessage("¡Hola, Ana!", reply_to="wamid.A")
    assert await gateway.send(NUMBER, TOKEN, recipient_id="5491155550199", message=message) == "wamid.HBgL1"
    call = transport.calls[0]
    assert call.json == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "5491155550199",
        "type": "text",
        "text": {"body": "¡Hola, Ana!", "preview_url": True},
        "context": {"message_id": "wamid.A"},
    }
    # Mandar un mensaje no es repetible: un reintento automático lo duplicaría.
    assert call.retry_safe is None
    with pytest.raises(ProviderError, match="id del mensaje"):
        await gateway.send(NUMBER, TOKEN, recipient_id="5491155550199", message=OutboundMessage("Hola"))


async def test_adjuntos_plantillas_y_el_id_de_usuario(
    transport: FakeTransport, client: WhatsAppClient
) -> None:
    transport.on("POST", MESSAGES, SENT)
    gateway = WhatsAppMessagingGateway(client)
    await gateway.send(
        NUMBER, TOKEN, recipient_id="AR.1349", message=OutboundMessage("Mirá", attachments=(PHOTO,))
    )
    body = transport.calls[0].json
    assert body is not None
    # Cuando WhatsApp no da el teléfono, se le escribe al id de usuario que vino en el aviso.
    assert (body["recipient"], "to" in body, body["type"]) == ("AR.1349", False, "image")
    assert body["image"] == {"link": "https://cdn.ejemplo.com/foto.jpg", "caption": "Mirá"}
    await gateway.send(
        NUMBER, TOKEN, recipient_id="5491155550199", message=OutboundMessage(attachments=(CLIP,))
    )
    assert transport.calls[1].json["video"] == {"link": "https://cdn.ejemplo.com/clip.mp4"}  # type: ignore[index]

    components = ({"type": "body", "parameters": [{"type": "text", "text": "Ana"}]},)
    template = OutboundMessage(template=TemplateRef("recordatorio", "es_AR", components))
    await gateway.send(NUMBER, TOKEN, recipient_id="5491155550199", message=template)
    sent = transport.calls[2].json
    assert sent is not None
    assert (sent["type"], sent["template"]) == (
        "template",
        {"name": "recordatorio", "language": {"code": "es_AR"}, "components": list(components)},
    )
    bare = OutboundMessage(template=TemplateRef("hola", "es"))
    await gateway.send(NUMBER, TOKEN, recipient_id="5491155550199", message=bare)
    assert transport.calls[3].json["template"] == {"name": "hola", "language": {"code": "es"}}  # type: ignore[index]

    long = OutboundMessage("x" * 1025, attachments=(PHOTO,))
    with pytest.raises(ProviderError, match="1024") as too_long:
        await gateway.send(NUMBER, TOKEN, recipient_id="5491155550199", message=long)
    assert too_long.value.kind.value == "invalid_request"
    assert len(transport.calls) == 4


async def test_no_hay_historial_y_la_ventana_es_de_un_dia(client: WhatsAppClient) -> None:
    gateway = WhatsAppMessagingGateway(client)
    limits = gateway.limits_for(NUMBER)
    assert (limits.history, limits.templates, limits.max_text, limits.max_attachments) == (
        False,
        True,
        4096,
        1,
    )
    assert gateway.reply_window.duration == timedelta(hours=24)
    with pytest.raises(ProviderError, match="avisos"):
        await gateway.list_conversations(NUMBER, TOKEN, limit=None)
    with pytest.raises(ProviderError, match="avisos"):
        await gateway.list_messages(NUMBER, TOKEN, conversation_id="x", limit=None)


async def test_las_plantillas_de_la_cuenta(transport: FakeTransport, client: WhatsAppClient) -> None:
    transport.on(
        "GET",
        "102290129340398/message_templates",
        {
            "data": [
                {"name": "recordatorio", "language": "es_AR", "status": "APPROVED", "category": "UTILITY"},
                {"name": "promo", "language": "es_AR", "status": "REJECTED"},
                {"name": "sin idioma"},
            ]
        },
    )
    lookups = WhatsAppLookups(client)
    found = await lookups.choices(NUMBER, TOKEN, lookup="templates", query=None, parent=None)
    assert found == [
        Choice(
            "recordatorio",
            "recordatorio",
            detail="es_AR",
            data={"language": "es_AR", "status": "APPROVED", "category": "UTILITY"},
        ),
        Choice("promo", "promo", detail="es_AR", data={"language": "es_AR", "status": "REJECTED"}),
    ]
    orphan = Asset("a1", "c1", NUMBER.provider, "dueño", NUMBER.kind, "n1")
    with pytest.raises(ProviderError, match="sincronizarlo"):
        await lookups.choices(orphan, TOKEN, lookup="templates", query=None, parent=None)


# ── De punta a punta ────────────────────────────────────────────────────────────────────────────


async def test_conectar_con_un_token_de_sistema_recibir_y_responder() -> None:  # noqa: PLR0915  # un recorrido
    transport = FakeTransport(base="https://graph.facebook.com/v26.0/")
    clock = FakeClock()
    social = Omnisocial.build(
        providers=[whatsapp_provider(config(), transport, clock=clock)],
        connections=InMemoryConnectionRepository(),
        assets=InMemoryAssetRepository(),
        states=InMemoryAuthorizationStateStore(clock),
        webhook_events=AsyncMemoryIdempotencyStore(),
        redirect_uri_for=lambda _: "https://api.ejemplo.com/cb",
        return_urls=ReturnUrlPolicy.of("https://app.ejemplo.com"),
        clock=clock,
    )
    transport.on("GET", "me", ME)
    transport.on("GET", "debug_token", INSPECTED)
    transport.on("GET", "102290129340398/phone_numbers", NUMBERS)
    connected = await social.register_system_connection.execute("whatsapp", owner="cliente-1", token=TOKEN)
    assert isinstance(connected, Connected)
    [number] = connected.assets

    arrived: list[object] = []

    async def on_events(events: object) -> None:
        arrived.extend(events)  # type: ignore[arg-type]

    received = await social.handle_webhook.execute(
        "whatsapp", request=signed(webhook(INBOUND)), on_events=on_events
    )
    assert (received.outcome, len(received.events)) == ("ok", 4)
    first = received.events[0]
    assert [asset.id for asset in first.assets] == [number.id]
    item = from_event(first.event)
    assert item is not None
    assert (item.kind, item.author_name, item.text) == (InboxKind.MESSAGE, "Ana", "Hola")

    # Lo que la app guardó del aviso alcanza para responder dentro de la ventana.
    to = Recipient(first.event.conversation_external_id or "", first.event.occurred_at)
    clock.current = (first.event.occurred_at or NOW) + timedelta(hours=1)
    transport.on("POST", "106540352242922/messages", SENT)
    assert await social.send_message.execute(number.id, text="¡Hola, Ana!", to=to) == Done("wamid.HBgL1")
    clock.current += timedelta(hours=24)
    late = await social.send_message.execute(number.id, text="¿Seguís ahí?", to=to)
    assert late == Refused(Refusal.OUTSIDE_REPLY_WINDOW)
    template = OutboundMessage(template=TemplateRef("recordatorio", "es_AR"))
    assert await social.send_message.execute(number.id, message=template, to=to) == Done("wamid.HBgL1")
    listed = await social.list_conversations.execute(number.id)
    assert isinstance(listed, Refused)
    assert listed.reason is Refusal.NOT_SUPPORTED
    templates = await social.list_choices.available(number.id)
    assert isinstance(templates, Done)
    assert [spec.name for spec in templates.value] == ["templates"]


# ── Avisos ──────────────────────────────────────────────────────────────────────────────────────


def test_el_saludo_confirma_la_url_solo_con_el_texto_acordado() -> None:
    parser = WhatsAppWebhookParser(config())
    hello = {"hub.mode": "subscribe", "hub.verify_token": "saludo", "hub.challenge": "1158201444"}
    assert parser.handshake(hello) == "1158201444"
    assert parser.handshake({**hello, "hub.verify_token": "otro"}) is None
    assert parser.handshake({**hello, "hub.mode": "unsubscribe"}) is None
    assert WhatsAppWebhookParser(config(webhook_verify_token=None)).handshake(hello) is None


def test_la_firma_acepta_el_secreto_anterior_mientras_se_rota() -> None:
    parser = WhatsAppWebhookParser(config(previous_app_secrets=("viejo",)))
    assert parser.verifier.verify(signed(webhook(INBOUND))).outcome == "ok"
    assert parser.verifier.verify(signed(webhook(INBOUND), "viejo")).outcome == "ok"
    assert parser.verifier.verify(signed(webhook(INBOUND), "ajeno")).outcome != "ok"
    unsigned = IncomingRequest(headers=[], query=[], body=b"{}")
    assert parser.verifier.verify(unsigned).outcome != "ok"


def test_los_mensajes_que_llegan_con_sus_adjuntos() -> None:
    text, image, document, location = WhatsAppWebhookParser(config()).parse(signed(webhook(INBOUND)).body)
    assert (text.kind, text.action, text.asset_external_id, text.object_external_id) == (
        EventKind.MESSAGE,
        EventAction.CREATED,
        "106540352242922",
        "wamid.A",
    )
    assert (text.actor_id, text.actor_name, text.conversation_external_id, text.text) == (
        "5491155550199",
        "Ana",
        "5491155550199",
        "Hola",
    )
    assert text.occurred_at == datetime.fromtimestamp(1795000000, UTC)
    # Sin teléfono, el remitente es su id de usuario, y el nombre se encuentra igual.
    assert (image.actor_id, image.actor_name, image.text) == ("AR.1349", "Ana", "Mirá")
    [photo] = image.attachments
    assert (photo.kind, photo.media_id, photo.mime_type) == (AttachmentKind.IMAGE, "media-1", "image/jpeg")
    assert (document.attachments[0].kind, document.attachments[0].name, document.occurred_at) == (
        AttachmentKind.FILE,
        "factura.pdf",
        None,
    )
    assert (location.attachments[0].kind, location.attachments[0].name) == (
        AttachmentKind.LOCATION,
        "El local",
    )


def test_el_estado_de_lo_que_se_mando() -> None:
    statuses = {
        "statuses": [
            {
                "id": "wamid.X",
                "status": "delivered",
                "timestamp": "1795000100",
                "recipient_id": "5491155550199",
            },
            {"id": "wamid.X", "status": "played", "timestamp": "1795000200", "recipient_user_id": "AR.1349"},
            {
                "id": "wamid.Y",
                "status": "failed",
                "timestamp": "1795000300",
                "recipient_id": "5491155550199",
                "errors": [
                    {
                        "code": 131047,
                        "title": "Re-engagement message",
                        "error_data": {"details": "More than 24 hours have passed"},
                    }
                ],
            },
            {
                "id": "wamid.Z",
                "status": "failed",
                "errors": [{"code": 131026, "title": "Message undeliverable"}],
            },
            {"id": "wamid.W", "status": "desconocido"},
            {"status": "sent"},
        ]
    }
    delivered, played, failed, undeliverable = WhatsAppWebhookParser(config()).parse(
        signed(webhook(statuses)).body
    )
    assert (delivered.kind, delivered.action, delivered.object_external_id, delivered.status) == (
        EventKind.MESSAGE,
        EventAction.UPDATED,
        "wamid.X",
        DeliveryStatus.DELIVERED,
    )
    assert (played.status, played.actor_id) == (DeliveryStatus.READ, "AR.1349")
    # Muchas veces WhatsApp acepta el mensaje y avisa después que no salió, y por qué.
    assert (failed.status, failed.text) == (DeliveryStatus.FAILED, "More than 24 hours have passed")
    assert undeliverable.text == "Message undeliverable"
    # El estado de un mensaje enviado no es algo que alguien escribió: no va a la bandeja.
    assert from_event(delivered) is None


def test_lo_que_no_es_un_aviso_de_mensajes_se_ignora() -> None:
    parser = WhatsAppWebhookParser(config())
    assert parser.parse(b"<html>") == []
    assert parser.parse(b'{"object": "page", "entry": []}') == []
    assert parser.parse(signed(webhook(INBOUND, field="account_update")).body) == []
    no_number = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "messages", "value": {}}]}],
    }
    assert parser.parse(signed(no_number).body) == []


# ── Errores ─────────────────────────────────────────────────────────────────────────────────────


async def test_los_errores_se_clasifican_por_su_codigo(
    transport: FakeTransport, client: WhatsAppClient
) -> None:
    transport.on(
        "GET",
        "me",
        failure(401, 190),
        failure(403, 10),
        failure(403, 294),
        failure(429, 131056),
        failure(400, 131047, "Re-engagement message", "More than 24 hours have passed"),
        failure(500, 131000),
    )
    with pytest.raises(TokenRejected):
        await client.get("me", "t")
    for _ in range(2):
        with pytest.raises(PermissionMissing):
            await client.get("me", "t")
    with pytest.raises(RateLimited):
        await client.get("me", "t")
    with pytest.raises(ProviderError, match=r"Re-engagement message \(More than 24 hours") as outside:
        await client.get("me", "t")
    assert (outside.value.kind.value, outside.value.code) == ("invalid_request", "131047")
    with pytest.raises(ProviderError) as unknown:
        await client.get("me", "t")
    assert unknown.value.kind.value == "transient"
