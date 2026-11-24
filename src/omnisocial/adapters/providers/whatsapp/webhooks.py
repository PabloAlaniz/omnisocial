"""Avisos de WhatsApp: la confirmación de la URL, la firma y la traducción.

Llegan dos cosas: los mensajes que manda la gente y qué pasó con los que mandó el negocio (enviado,
entregado, leído o fallido). Es la única forma de recibir mensajes: no hay cómo pedirlos después.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Iterator, Mapping, Sequence

from omniwebhook import Verifier, hmac_body_scheme
from typing_extensions import override

from omnisocial.adapters.providers.whatsapp.client import as_dict, as_list, as_str, from_epoch
from omnisocial.adapters.providers.whatsapp.config import WHATSAPP, WhatsAppConfig
from omnisocial.application.ports import WebhookParser
from omnisocial.domain.messaging import Attachment, AttachmentKind, DeliveryStatus
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent

SIGNATURE_HEADER = "x-hub-signature-256"
_OBJECT = "whatsapp_business_account"
_MEDIA = {
    "image": AttachmentKind.IMAGE,
    "video": AttachmentKind.VIDEO,
    "audio": AttachmentKind.AUDIO,
    "document": AttachmentKind.FILE,
    "sticker": AttachmentKind.STICKER,
}
_STATUS = {
    "sent": DeliveryStatus.SENT,
    "delivered": DeliveryStatus.DELIVERED,
    "read": DeliveryStatus.READ,
    # Un audio que la persona escuchó.
    "played": DeliveryStatus.READ,
    "failed": DeliveryStatus.FAILED,
}


def _attachments(message: dict[str, object]) -> tuple[tuple[Attachment, ...], str | None]:
    """Los adjuntos de un mensaje y el texto que los acompaña."""
    kind = as_str(message.get("type")) or ""
    content = as_dict(message.get(kind))
    if kind in _MEDIA:
        attachment = Attachment(
            _MEDIA[kind],
            media_id=as_str(content.get("id")),
            mime_type=as_str(content.get("mime_type")),
            name=as_str(content.get("filename")),
        )
        return (attachment,), as_str(content.get("caption"))
    if kind == "location":
        return (Attachment(AttachmentKind.LOCATION, name=as_str(content.get("name"))),), None
    return (), None


class WhatsAppWebhookParser(WebhookParser):
    def __init__(self, config: WhatsAppConfig) -> None:
        self._verify_token = config.webhook_verify_token
        self._verifier = hmac_body_scheme(
            secrets=[config.app_secret, *config.previous_app_secrets],
            header=SIGNATURE_HEADER,
            prefix="sha256=",
            name="whatsapp",
        )

    @override
    def handshake(self, query: Mapping[str, str]) -> str | None:
        """El GET con que Meta confirma la URL. Devuelve el `hub.challenge` a responder, o `None`."""
        if not self._verify_token or query.get("hub.mode") != "subscribe":
            return None
        given = query.get("hub.verify_token", "")
        if not hmac.compare_digest(given.encode(), self._verify_token.encode()):
            return None
        return query.get("hub.challenge")

    @property
    @override
    def verifier(self) -> Verifier:
        """`X-Hub-Signature-256: sha256=<hex>`: HMAC-SHA256 del cuerpo crudo con el secreto de la app."""
        return self._verifier

    @override
    def parse(self, body: bytes, *, query: Mapping[str, str] | None = None) -> Sequence[SocialEvent]:
        try:
            payload = as_dict(json.loads(body))
        except ValueError:
            return []
        if payload.get("object") != _OBJECT:
            return []
        events: list[SocialEvent] = []
        for entry in as_list(payload.get("entry")):
            for change in as_list(entry.get("changes")):
                value = as_dict(change.get("value"))
                number = as_str(as_dict(value.get("metadata")).get("phone_number_id"))
                if change.get("field") == "messages" and number is not None:
                    events.extend(self._messages(number, value))
                    events.extend(self._statuses(number, value))
        return events

    @staticmethod
    def _messages(number: str, value: dict[str, object]) -> Iterator[SocialEvent]:
        names: dict[str, str] = {}
        for contact in as_list(value.get("contacts")):
            name = as_str(as_dict(contact.get("profile")).get("name"))
            for key in ("wa_id", "user_id"):
                if name and (contact_id := as_str(contact.get(key))):
                    names[contact_id] = name
        for message in as_list(value.get("messages")):
            # El teléfono puede no venir: queda el id de usuario, que también sirve para responder.
            sender = as_str(message.get("from")) or as_str(message.get("from_user_id"))
            message_id = as_str(message.get("id"))
            if sender is None or message_id is None:
                continue
            attachments, caption = _attachments(message)
            yield SocialEvent(
                provider=WHATSAPP,
                kind=EventKind.MESSAGE,
                action=EventAction.CREATED,
                asset_external_id=number,
                object_external_id=message_id,
                occurred_at=from_epoch(message.get("timestamp")),
                actor_id=sender,
                actor_name=names.get(sender),
                text=as_str(as_dict(message.get("text")).get("body")) or caption,
                conversation_external_id=sender,
                attachments=attachments,
                raw=message,
            )

    @staticmethod
    def _statuses(number: str, value: dict[str, object]) -> Iterator[SocialEvent]:
        for status in as_list(value.get("statuses")):
            message_id = as_str(status.get("id"))
            reached = _STATUS.get(as_str(status.get("status")) or "")
            if message_id is None or reached is None:
                continue
            recipient = as_str(status.get("recipient_id")) or as_str(status.get("recipient_user_id"))
            errors = as_list(status.get("errors"))
            problem = errors[0] if errors else {}
            detail = as_str(as_dict(problem.get("error_data")).get("details"))
            yield SocialEvent(
                provider=WHATSAPP,
                kind=EventKind.MESSAGE,
                action=EventAction.UPDATED,
                asset_external_id=number,
                object_external_id=message_id,
                occurred_at=from_epoch(status.get("timestamp")),
                actor_id=recipient,
                # Si falló, por qué: muchas veces WhatsApp acepta el mensaje y avisa después.
                text=detail or as_str(problem.get("title")),
                conversation_external_id=recipient,
                status=reached,
                raw=status,
            )
