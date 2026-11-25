"""Publicar en X: un post o un hilo, con hasta 4 fotos o un video por parte.

1. Cada medio se sube por partes y queda un id. Un video, además, se procesa: hasta que X termina no se
   puede usar.
2. Se crea el primer post, y cada parte del hilo como respuesta a la anterior.

Hasta el paso 2 no hay nada publicado. Si los videos siguen en proceso, la publicación queda pendiente con
el plan de lo que falta crear, y se retoma después.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.x.client import XClient, as_dict, as_list, as_str
from omnisocial.adapters.providers.x.config import X, XOptions
from omnisocial.adapters.providers.x.content import permalink
from omnisocial.application.ports import Publisher
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ErrorKind, NotPublished, OmnisocialError, ProviderError, TokenRejected
from omnisocial.domain.publishing import Draft, Media, MediaKind, Outcome, PublicationStatus
from omnisocial.domain.token import Token

_PLAN = "plan"
_REPLY_TO = "reply_to"
_WAITING = "waiting"
_CLIENT_ERROR = 400
_SERVER_ERROR = 500
_SUCCEEDED = "succeeded"
_FAILED = "failed"
# Errores que ya dicen por qué no salió: el núcleo los traduce a su propia negativa.
_SAYS_WHY = frozenset(
    {
        ErrorKind.MISSING_PERMISSION,
        ErrorKind.RATE_LIMITED,
        ErrorKind.QUOTA_EXHAUSTED,
        ErrorKind.INVALID_REQUEST,
    }
)


@dataclass(frozen=True, slots=True)
class _Part:
    """Una parte del hilo, con sus medios ya subidos."""

    text: str
    media: tuple[str, ...]

    def body(self, reply_to: str | None) -> dict[str, object]:
        body: dict[str, object] = {}
        if self.text:
            body["text"] = self.text
        if self.media:
            body["media"] = {"media_ids": list(self.media)}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        return body


def _dump(parts: Sequence[_Part]) -> str:
    return json.dumps([{"text": part.text, "media": list(part.media)} for part in parts])


def _load(plan: str) -> list[_Part]:
    parts: list[_Part] = []
    for item in as_list(json.loads(plan)):
        media = item.get("media")
        ids = tuple(m for m in media if isinstance(m, str)) if isinstance(media, list) else ()
        parts.append(_Part(as_str(item.get("text")) or "", ids))
    return parts


def _not_published(error: OmnisocialError, status: int | None = None) -> OmnisocialError:
    """Un error antes de crear el post: con certeza no salió."""
    if isinstance(error, TokenRejected) or (isinstance(error, ProviderError) and error.kind in _SAYS_WHY):
        return error
    return NotPublished(X, str(error), status=status)


def _category(media: Media) -> str:
    if media.kind is MediaKind.VIDEO:
        return "tweet_video"
    return "tweet_gif" if media.upload.content_type == "image/gif" else "tweet_image"


def _state(response_data: dict[str, object]) -> str:
    """El estado del procesamiento de un medio. Sin `processing_info`, ya está listo."""
    info = as_dict(as_dict(response_data.get("data")).get("processing_info"))
    return as_str(info.get("state")) or _SUCCEEDED


class XPublisher(Publisher):
    def __init__(self, client: XClient) -> None:
        self._client = client

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options if isinstance(draft.options, XOptions) else XOptions()
        parts: list[_Part] = []
        waiting: list[str] = []
        for item in (draft, *draft.thread):
            uploaded = [await self._upload(token.access_token, media) for media in item.media]
            parts.append(_Part(item.text, tuple(media_id for media_id, _ in uploaded)))
            waiting.extend(media_id for media_id, ready in uploaded if not ready)
        if waiting:
            resume = {_PLAN: _dump(parts), _REPLY_TO: options.reply_to or "", _WAITING: ",".join(waiting)}
            return Outcome(PublicationStatus.PENDING, resume=resume)
        return await self._post_all(token.access_token, parts, options.reply_to)

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        plan = resume.get(_PLAN)
        if not plan:
            raise ProviderError(X, "La publicación no tiene nada para retomar.")
        for media_id in filter(None, resume.get(_WAITING, "").split(",")):
            data = await self._client.get("media/upload", token.access_token, {"media_id": media_id})
            state = _state(data)
            if state == _FAILED:
                return Outcome(PublicationStatus.FAILED, error="X no pudo procesar el video.")
            if state != _SUCCEEDED:
                return Outcome(PublicationStatus.PENDING, resume=resume)
        try:
            return await self._post_all(token.access_token, _load(plan), resume.get(_REPLY_TO) or None)
        except NotPublished as error:
            # X lo rechazó: reintentar con los mismos medios daría lo mismo.
            return Outcome(PublicationStatus.FAILED, error=str(error))

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        self._client.unwrap(await self._client.call("DELETE", f"tweets/{post_id}", token.access_token))

    # ── Los posts ───────────────────────────────────────────────────────────────────────────────

    async def _post_all(self, token: str, parts: Sequence[_Part], reply_to: str | None) -> Outcome:
        first = await self._create(token, parts[0], reply_to)
        previous = first
        for number, part in enumerate(parts[1:], start=2):
            try:
                previous = await self._create(token, part, previous)
            except (TokenRejected, ProviderError, TransportError) as error:
                # El comienzo del hilo ya salió: no es un fracaso, y repetirlo lo duplicaría.
                return Outcome(
                    PublicationStatus.PUBLISHED_WITH_ERROR,
                    post_id=first,
                    url=permalink(first),
                    error=f"El hilo quedó cortado en la parte {number}: {error}",
                )
        return Outcome(PublicationStatus.PUBLISHED, post_id=first, url=permalink(first))

    async def _create(self, token: str, part: _Part, reply_to: str | None) -> str:
        response = await self._client.call("POST", "tweets", token, json=part.body(reply_to))
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            # Un 4xx es un rechazo: X no creó nada.
            raise _not_published(self._client.error(response), response.status)
        created = as_dict(self._client.unwrap(response).get("data"))
        post_id = as_str(created.get("id"))
        if post_id is None:
            # Respondió bien: el post existe. No se puede decir que no salió.
            raise ProviderError(X, "X creó el post pero no devolvió su id.")
        return post_id

    # ── Los medios ──────────────────────────────────────────────────────────────────────────────

    async def _upload(self, token: str, media: Media) -> tuple[str, bool]:
        """El id del medio, y si ya está listo para usar."""
        try:
            return await self._send(token, media)
        except TransportError as error:
            raise NotPublished(X, f"La subida se cortó: {error}") from error
        except (TokenRejected, ProviderError) as error:
            raise _not_published(error) from error

    async def _step(
        self, token: str, path: str, body: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        response: HttpResponse = await self._client.call("POST", path, token, json=body, read=True)
        return self._client.unwrap(response)

    async def _send(self, token: str, media: Media) -> tuple[str, bool]:
        file = media.upload
        started = await self._step(
            token,
            "media/upload/initialize",
            {"media_type": file.content_type, "total_bytes": file.size, "media_category": _category(media)},
        )
        media_id = as_str(as_dict(started.get("data")).get("id"))
        if media_id is None:
            raise ProviderError(X, "X no devolvió el id del medio.")
        segment = self._client.config.media_segment_bytes
        for index, offset in enumerate(range(0, file.size, segment)):
            data = await file.read(offset, segment)
            encoded = base64.b64encode(data).decode()
            await self._step(
                token, f"media/upload/{media_id}/append", {"media": encoded, "segment_index": index}
            )
        finished = await self._step(token, f"media/upload/{media_id}/finalize")
        if media.alt_text:
            metadata = {"id": media_id, "metadata": {"alt_text": {"text": media.alt_text}}}
            await self._step(token, "media/metadata", metadata)
        return media_id, _state(finished) == _SUCCEEDED
