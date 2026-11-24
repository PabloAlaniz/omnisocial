"""Publicar en un chat y escribirle a una persona. Para Telegram es lo mismo: mandar a un chat.

- Sin medios: un mensaje.
- Con un medio: una foto o un video con el texto al pie.
- Con varios: un álbum de 2 a 10, con el texto al pie del primero.

Lo que entra al pie de un medio es menos que lo que entra en un mensaje. Si el texto es más largo, sale
aparte, como respuesta a lo que se publicó.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.telegram.client import (
    TelegramClient,
    Upload,
    api_error,
    as_dict,
    as_int,
    as_list,
    as_str,
    unwrap,
)
from omnisocial.adapters.providers.telegram.config import TELEGRAM, TelegramOptions
from omnisocial.adapters.providers.telegram.spec import MAX_CAPTION, MESSAGE_LIMITS, REPLY_WINDOW
from omnisocial.application.ports import IdGenerator, MessagingGateway, Publisher
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ErrorKind, NotPublished, OmnisocialError, ProviderError, TokenRejected
from omnisocial.domain.messaging import Conversation, Message, MessagingLimits, OutboundMessage
from omnisocial.domain.publishing import Draft, Media, MediaKind, Outcome, PublicationStatus
from omnisocial.domain.token import Token

_CLIENT_ERROR = 400
_SERVER_ERROR = 500
# Errores que ya dicen por qué no salió: el núcleo los traduce a su propia negativa.
_SAYS_WHY = frozenset({ErrorKind.RATE_LIMITED, ErrorKind.INVALID_REQUEST})
_NO_HISTORY = "Telegram no deja leer los mensajes pasados: llegan por avisos."


def _not_published(error: OmnisocialError, status: int | None = None) -> OmnisocialError:
    if isinstance(error, TokenRejected) or (isinstance(error, ProviderError) and error.kind in _SAYS_WHY):
        return error
    return NotPublished(TELEGRAM, str(error), status=status)


@dataclass(frozen=True, slots=True)
class Sent:
    chat_id: str
    message_ids: tuple[int, ...]
    username: str | None
    """El nombre público del chat, si tiene: con él se arma la dirección de la publicación."""

    @property
    def url(self) -> str | None:
        return f"https://t.me/{self.username}/{self.message_ids[0]}" if self.username else None

    @property
    def post_id(self) -> str:
        return f"{self.chat_id}:{','.join(str(i) for i in self.message_ids)}"


def _chat(chat_id: str) -> str | int:
    """El id de un chat es un número; `@canal` va como texto."""
    stripped = chat_id.strip()
    return int(stripped) if stripped.lstrip("-").isdigit() else stripped


def _kind(media: Media) -> str:
    return "video" if media.kind is MediaKind.VIDEO else "photo"


class _Sender:
    """Lo que comparten publicar y escribirle a alguien."""

    def __init__(self, client: TelegramClient, ids: IdGenerator) -> None:
        self._client = client
        self._ids = ids

    async def _request(
        self, token: str, method: str, params: Mapping[str, object], files: Sequence[Upload]
    ) -> HttpResponse:
        if not files:
            return await self._client.call(token, method, params)
        boundary = f"omnisocial-{self._ids.new_id()}"
        return await self._client.upload(token, method, params, files=files, boundary=boundary)

    async def _media(self, media: Sequence[Media]) -> tuple[list[str], list[Upload]]:
        """Para cada medio, su URL o la referencia al archivo que viaja en el mismo pedido."""
        references: list[str] = []
        files: list[Upload] = []
        for position, item in enumerate(media):
            if item.url is not None:
                references.append(item.url)
                continue
            file = item.upload
            name = f"file{position}"
            files.append(Upload(name, await file.read(0, file.size), file.content_type))
            references.append(f"attach://{name}")
        return references, files

    async def send(
        self, token: str, base: Mapping[str, object], text: str, media: Sequence[Media]
    ) -> HttpResponse:
        """Manda el texto, un medio o un álbum al chat de `base`. El texto va al pie si entra."""
        if not media:
            return await self._request(token, "sendMessage", {**base, "text": text}, [])
        references, files = await self._media(media)
        caption = {"caption": text} if text and len(text) <= MAX_CAPTION else {}
        if "parse_mode" in base and not caption:
            base = {key: value for key, value in base.items() if key != "parse_mode"}
        if len(media) == 1:
            kind = _kind(media[0])
            return await self._request(
                token, f"send{kind.capitalize()}", {**base, kind: references[0], **caption}, files
            )
        album: list[dict[str, object]] = [
            {"type": _kind(item), "media": reference}
            for item, reference in zip(media, references, strict=True)
        ]
        album[0].update(caption)
        if "parse_mode" in base and caption:
            album[0]["parse_mode"] = base["parse_mode"]
        params = {key: value for key, value in base.items() if key != "parse_mode"}
        return await self._request(token, "sendMediaGroup", {**params, "media": album}, files)


def _sent(result: object, chat_id: str) -> Sent | None:
    messages = as_list(result) if isinstance(result, list) else [as_dict(result)]
    ids = tuple(i for i in (as_int(message.get("message_id")) for message in messages) if i is not None)
    if not ids:
        return None
    return Sent(chat_id, ids, as_str(as_dict(messages[0].get("chat")).get("username")))


class TelegramPublisher(Publisher):
    def __init__(self, client: TelegramClient, ids: IdGenerator) -> None:
        self._client = client
        self._sender = _Sender(client, ids)

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options
        if not isinstance(options, TelegramOptions):
            raise ProviderError(
                TELEGRAM, "Un bot publica en un chat: faltan las opciones.", kind=ErrorKind.INVALID_REQUEST
            )
        base = self._base(options)
        # Si el pedido sale y no hay respuesta, no se sabe si se publicó: el error sigue como vino.
        response = await self._sender.send(token.access_token, base, draft.text, draft.media)
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            # Un 4xx es un rechazo: Telegram no publicó nada.
            raise _not_published(api_error(response), response.status)
        sent = _sent(unwrap(response), options.chat_id)
        if sent is None:
            raise ProviderError(TELEGRAM, "Telegram aceptó la publicación pero no devolvió su id.")
        if draft.media and len(draft.text) > MAX_CAPTION:
            return await self._rest(token.access_token, base, draft.text, sent)
        return Outcome(PublicationStatus.PUBLISHED, post_id=sent.post_id, url=sent.url)

    @staticmethod
    def _base(options: TelegramOptions) -> dict[str, object]:
        fields: dict[str, object | None] = {
            "chat_id": _chat(options.chat_id),
            "parse_mode": options.parse_mode,
            "disable_notification": options.silent or None,
            "protect_content": options.protect or None,
            "message_thread_id": options.thread_id,
            "link_preview_options": {"is_disabled": True} if options.disable_preview else None,
        }
        return {name: value for name, value in fields.items() if value is not None}

    async def _rest(self, token: str, base: Mapping[str, object], text: str, sent: Sent) -> Outcome:
        """El texto no entraba al pie: sale como respuesta a lo publicado. Si falla, lo primero ya salió."""
        params = {**base, "text": text, "reply_parameters": {"message_id": sent.message_ids[0]}}
        try:
            more = _sent(unwrap(await self._client.call(token, "sendMessage", params)), sent.chat_id)
        except (ProviderError, TokenRejected, TransportError) as error:
            return Outcome(
                PublicationStatus.PUBLISHED_WITH_ERROR,
                post_id=sent.post_id,
                url=sent.url,
                error=f"El texto no salió: {error}",
            )
        ids = sent.message_ids + (more.message_ids if more else ())
        whole = Sent(sent.chat_id, ids, sent.username)
        return Outcome(PublicationStatus.PUBLISHED, post_id=whole.post_id, url=whole.url)

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        raise ProviderError(TELEGRAM, "Telegram publica en una sola etapa: no hay nada para retomar.")

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        """Borra todos los mensajes de la publicación. Telegram deja borrar hasta 48 horas después."""
        chat_id, _, ids = post_id.partition(":")
        for message_id in ids.split(","):
            params = {"chat_id": _chat(chat_id), "message_id": int(message_id)}
            unwrap(await self._client.call(token.access_token, "deleteMessage", params))


class TelegramMessagingGateway(MessagingGateway):
    reply_window = REPLY_WINDOW

    def __init__(self, client: TelegramClient, ids: IdGenerator) -> None:
        self._sender = _Sender(client, ids)

    @override
    def limits_for(self, asset: Asset) -> MessagingLimits:
        return MESSAGE_LIMITS

    @override
    async def list_conversations(
        self, asset: Asset, token: Token, *, limit: int | None
    ) -> Sequence[Conversation]:
        raise ProviderError(TELEGRAM, _NO_HISTORY)

    @override
    async def list_messages(
        self, asset: Asset, token: Token, *, conversation_id: str, limit: int | None
    ) -> Sequence[Message]:
        raise ProviderError(TELEGRAM, _NO_HISTORY)

    @override
    async def send(self, asset: Asset, token: Token, *, recipient_id: str, message: OutboundMessage) -> str:
        """`recipient_id` es el chat de la persona, que viene en el aviso de su mensaje. `reply_to` es el
        id de un mensaje de ese chat, con o sin el chat por delante."""
        if message.attachments and len(message.text) > MAX_CAPTION:
            raise ProviderError(
                TELEGRAM,
                f"El texto que acompaña a un adjunto tiene hasta {MAX_CAPTION} caracteres.",
                kind=ErrorKind.INVALID_REQUEST,
            )
        base: dict[str, object] = {"chat_id": _chat(recipient_id)}
        if message.reply_to:
            base["reply_parameters"] = {"message_id": int(message.reply_to.rpartition(":")[2])}
        response = await self._sender.send(token.access_token, base, message.text, message.attachments)
        sent = _sent(unwrap(response), recipient_id)
        if sent is None:
            raise ProviderError(TELEGRAM, "Telegram no devolvió el id del mensaje.")
        return f"{sent.chat_id}:{sent.message_ids[0]}"
