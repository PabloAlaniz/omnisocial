"""Avisos de Telegram: el secreto de cada bot y la traducción.

Telegram no firma los avisos: manda, en una cabecera, el secreto que se le dio al registrar la URL. Y el
aviso no dice de qué bot es. Por eso la URL de cada bot lleva su id (`?bot=<id>`) y su secreto sale de
ese id y del secreto de la configuración: el de un bot no sirve para hacerse pasar por otro.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator, Mapping, Sequence
from urllib.parse import urlencode, urlsplit, urlunsplit

from omniwebhook import IncomingRequest, Rejected, Verification, Verified, Verifier
from typing_extensions import override

from omnisocial.adapters.providers.telegram.client import (
    TelegramClient,
    as_dict,
    as_int,
    as_list,
    as_str,
    from_epoch,
    unwrap,
)
from omnisocial.adapters.providers.telegram.config import TELEGRAM
from omnisocial.adapters.providers.telegram.session import bot
from omnisocial.application.ports import WebhookParser
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.messaging import Attachment, AttachmentKind
from omnisocial.domain.token import Token
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent

SECRET_HEADER = "x-telegram-bot-api-secret-token"  # noqa: S105  # es el nombre de la cabecera
BOT_PARAM = "bot"
ALLOWED_UPDATES = ("message", "edited_message", "channel_post", "edited_channel_post", "my_chat_member")
_PRIVATE = "private"
_CHANNEL = "channel"
_FILES = {
    "video": AttachmentKind.VIDEO,
    "audio": AttachmentKind.AUDIO,
    "voice": AttachmentKind.AUDIO,
    "document": AttachmentKind.FILE,
    "sticker": AttachmentKind.STICKER,
    "animation": AttachmentKind.VIDEO,
}
_UPDATES = {
    "message": EventAction.CREATED,
    "edited_message": EventAction.UPDATED,
    "channel_post": EventAction.CREATED,
    "edited_channel_post": EventAction.UPDATED,
}


def secret_for(webhook_secret: str, bot_id: str) -> str:
    """El secreto que Telegram manda en los avisos de ese bot."""
    return hmac.new(webhook_secret.encode(), bot_id.encode(), hashlib.sha256).hexdigest()


def _field(fields: Sequence[tuple[str, str]], name: str) -> list[str]:
    return [str(value) for key, value in fields if str(key).lower() == name]


class TelegramVerifier(Verifier):
    def __init__(self, webhook_secret: str | None) -> None:
        self._secret = webhook_secret

    @override
    def verify(self, request: IncomingRequest) -> Verification:
        given, bots = _field(request.headers, SECRET_HEADER), _field(request.query, BOT_PARAM)
        problem = self._problem(given, bots)
        if problem is not None:
            return problem
        try:
            update = as_int(as_dict(json.loads(request.body)).get("update_id"))
        except ValueError:
            return Rejected("malformed")
        # Telegram repite un aviso con el mismo número hasta que se le responde bien.
        key = str(update) if update is not None else hashlib.sha256(request.body).hexdigest()
        return Verified(f"telegram:{bots[0]}:{key}", None)

    def _problem(self, given: Sequence[str], bots: Sequence[str]) -> Rejected | None:
        if not self._secret:
            return Rejected("unconfigured")
        if not given or not bots:
            return Rejected("missing")
        if not (_one(given) and _one(bots)):
            return Rejected("ambiguous")
        if not hmac.compare_digest(given[0].encode(), secret_for(self._secret, bots[0]).encode()):
            return Rejected("invalid")
        return None


def _one(values: Sequence[str]) -> bool:
    return len(values) == 1


def _attachments(message: dict[str, object]) -> tuple[Attachment, ...]:
    found: list[Attachment] = []
    sizes = as_list(message.get("photo"))
    if sizes:
        # Una foto viene en varios tamaños: el último es el más grande.
        found.append(Attachment(AttachmentKind.IMAGE, media_id=as_str(sizes[-1].get("file_id"))))
    for name, kind in _FILES.items():
        file = as_dict(message.get(name))
        if file:
            found.append(
                Attachment(
                    kind,
                    media_id=as_str(file.get("file_id")),
                    mime_type=as_str(file.get("mime_type")),
                    name=as_str(file.get("file_name")),
                )
            )
    if message.get("location"):
        found.append(Attachment(AttachmentKind.LOCATION))
    return tuple(found)


def _name(sender: dict[str, object]) -> str | None:
    parts = [as_str(sender.get("first_name")), as_str(sender.get("last_name"))]
    return " ".join(p for p in parts if p) or as_str(sender.get("username")) or as_str(sender.get("title"))


def _message(bot_id: str, action: EventAction, message: dict[str, object]) -> SocialEvent | None:
    chat = as_dict(message.get("chat"))
    chat_id, message_id = as_int(chat.get("id")), as_int(message.get("message_id"))
    if chat_id is None or message_id is None:
        return None
    kind_of_chat = as_str(chat.get("type"))
    # En un canal publica el canal; en un grupo, lo que se escribe es parte de una charla de varios.
    if kind_of_chat == _CHANNEL:
        kind = EventKind.POST
    elif kind_of_chat == _PRIVATE:
        kind = EventKind.MESSAGE
    else:
        kind = EventKind.COMMENT
    sender = as_dict(message.get("from")) or as_dict(message.get("sender_chat"))
    sender_id = as_int(sender.get("id"))
    return SocialEvent(
        provider=TELEGRAM,
        kind=kind,
        action=action,
        asset_external_id=bot_id,
        object_external_id=f"{chat_id}:{message_id}",
        occurred_at=from_epoch(message.get("edit_date")) or from_epoch(message.get("date")),
        actor_id=str(sender_id) if sender_id is not None else None,
        actor_name=_name(sender),
        text=as_str(message.get("text")) or as_str(message.get("caption")),
        conversation_external_id=str(chat_id),
        attachments=_attachments(message),
        raw=message,
    )


def _membership(bot_id: str, change: dict[str, object]) -> SocialEvent | None:
    """Sumaron o sacaron al bot de un chat, o una persona lo bloqueó. `text` dice cómo quedó: `member`,
    `administrator`, `left` o `kicked`. De acá sale en qué chats puede publicar."""
    chat_id = as_int(as_dict(change.get("chat")).get("id"))
    if chat_id is None:
        return None
    actor = as_dict(change.get("from"))
    actor_id = as_int(actor.get("id"))
    return SocialEvent(
        provider=TELEGRAM,
        kind=EventKind.OTHER,
        action=EventAction.UPDATED,
        asset_external_id=bot_id,
        object_external_id=None,
        occurred_at=from_epoch(change.get("date")),
        actor_id=str(actor_id) if actor_id is not None else None,
        actor_name=_name(actor),
        text=as_str(as_dict(change.get("new_chat_member")).get("status")),
        conversation_external_id=str(chat_id),
        raw=change,
    )


class TelegramWebhookParser(WebhookParser):
    def __init__(self, webhook_secret: str | None) -> None:
        self._verifier = TelegramVerifier(webhook_secret)

    @override
    def handshake(self, query: Mapping[str, str]) -> str | None:
        """Telegram no confirma la URL con un pedido aparte."""
        return None

    @property
    @override
    def verifier(self) -> Verifier:
        return self._verifier

    @override
    def parse(self, body: bytes, *, query: Mapping[str, str] | None = None) -> Sequence[SocialEvent]:
        bot_id = (query or {}).get(BOT_PARAM)
        try:
            update = as_dict(json.loads(body))
        except ValueError:
            return []
        if not bot_id:
            return []
        return list(self._events(bot_id, update))

    @staticmethod
    def _events(bot_id: str, update: dict[str, object]) -> Iterator[SocialEvent]:
        for name, action in _UPDATES.items():
            event = _message(bot_id, action, as_dict(update.get(name))) if name in update else None
            if event is not None:
                yield event
        if "my_chat_member" in update:
            event = _membership(bot_id, as_dict(update.get("my_chat_member")))
            if event is not None:
                yield event


class TelegramWebhooks:
    """Le dice a Telegram a dónde mandar los avisos de un bot."""

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def register(self, token: Token, url: str) -> str:
        """Registra `url` para ese bot, con su id en la query y su secreto. Devuelve la URL que quedó.

        Hay que llamarlo una vez por bot, después de conectarlo. Mientras haya una URL registrada,
        Telegram no entrega los avisos de ninguna otra forma.
        """
        secret = self._client.config.webhook_secret
        if not secret:
            raise ProviderError(TELEGRAM, "Falta `webhook_secret` en la configuración.")
        bot_id, _, _ = await bot(self._client, token)
        parts = urlsplit(url)
        query = "&".join(part for part in (parts.query, urlencode({BOT_PARAM: bot_id})) if part)
        target = urlunsplit(parts._replace(query=query))
        params = {
            "url": target,
            "secret_token": secret_for(secret, bot_id),
            "allowed_updates": list(ALLOWED_UPDATES),
        }
        unwrap(await self._client.call(token.access_token, "setWebhook", params, read=True))
        return target

    async def remove(self, token: Token) -> None:
        unwrap(await self._client.call(token.access_token, "deleteWebhook", {}, read=True))
