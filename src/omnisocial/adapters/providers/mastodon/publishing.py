"""Publicar en Mastodon y en Pixelfed: una publicación o un hilo.

1. Cada imagen o video se sube al servidor de la cuenta. Un video se procesa: hasta que termina no se puede
   usar.
2. Se crea la publicación, y cada parte del hilo como respuesta a la anterior.

Cada publicación lleva una clave de idempotencia que el servidor recuerda una hora: repetir el pedido no
publica dos veces. La clave se guarda con el plan, así que retomar tampoco duplica.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from typing_extensions import override

from omnisocial.adapters.http.transport import TransportError
from omnisocial.adapters.providers.mastodon.client import MastodonClient, Payload, as_dict, as_list, as_str
from omnisocial.adapters.providers.mastodon.config import MastodonOptions
from omnisocial.application.ports import IdGenerator, Publisher
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ErrorKind, NotPublished, OmnisocialError, ProviderError, TokenRejected
from omnisocial.domain.publishing import Draft, Media, Outcome, PublicationStatus
from omnisocial.domain.token import Token

_PLAN = "plan"
_WAITING = "waiting"
_OPTIONS = "options"
_CLIENT_ERROR = 400
_SERVER_ERROR = 500
_PROCESSING = 202
_STILL_PROCESSING = 206
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
    """Una parte del hilo, con sus medios ya subidos y su clave de idempotencia."""

    text: str
    media: tuple[str, ...]
    key: str


def _dump(parts: Sequence[_Part]) -> str:
    return json.dumps([{"text": p.text, "media": list(p.media), "key": p.key} for p in parts])


def _load(plan: str) -> list[_Part]:
    parts: list[_Part] = []
    for item in as_list(json.loads(plan)):
        media = item.get("media")
        ids = tuple(m for m in media if isinstance(m, str)) if isinstance(media, list) else ()
        parts.append(_Part(as_str(item.get("text")) or "", ids, as_str(item.get("key")) or ""))
    return parts


def _settings(options: MastodonOptions) -> dict[str, object]:
    """Lo que vale para todas las partes del hilo."""
    settings: dict[str, object] = {"visibility": options.visibility}
    if options.sensitive:
        settings["sensitive"] = True
    if options.spoiler_text:
        settings["spoiler_text"] = options.spoiler_text
    if options.language:
        settings["language"] = options.language
    return settings


def multipart(boundary: str, file: bytes, content_type: str, description: str | None) -> bytes:
    """El cuerpo de una subida con formulario. El transporte manda bytes: el formulario se arma acá."""
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="media"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode()
        + file
        + b"\r\n"
    ]
    if description:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="description"\r\n\r\n'.encode()
            + description.encode()
            + b"\r\n"
        )
    return b"".join(parts) + f"--{boundary}--\r\n".encode()


class MastodonPublisher(Publisher):
    def __init__(self, client: MastodonClient, ids: IdGenerator) -> None:
        self._client = client
        self._ids = ids

    def _not_published(self, error: OmnisocialError, status: int | None = None) -> OmnisocialError:
        if isinstance(error, TokenRejected) or (isinstance(error, ProviderError) and error.kind in _SAYS_WHY):
            return error
        return NotPublished(self._client.flavor.provider, str(error), status=status)

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options if isinstance(draft.options, MastodonOptions) else MastodonOptions()
        parts: list[_Part] = []
        waiting: list[str] = []
        for item in (draft, *draft.thread):
            uploaded = [await self._upload(token, media) for media in item.media]
            parts.append(_Part(item.text, tuple(media_id for media_id, _ in uploaded), self._ids.new_id()))
            waiting.extend(media_id for media_id, ready in uploaded if not ready)
        settings = {**_settings(options), "reply_to": options.reply_to or ""}
        if waiting:
            resume = {_PLAN: _dump(parts), _OPTIONS: json.dumps(settings), _WAITING: ",".join(waiting)}
            return Outcome(PublicationStatus.PENDING, resume=resume)
        return await self._post_all(token, parts, settings)

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        plan = resume.get(_PLAN)
        if not plan:
            raise ProviderError(self._client.flavor.provider, "La publicación no tiene nada para retomar.")
        for media_id in filter(None, resume.get(_WAITING, "").split(",")):
            response = await self._client.call("GET", f"api/v1/media/{media_id}", token)
            if response.status == _STILL_PROCESSING:
                return Outcome(PublicationStatus.PENDING, resume=resume)
            if response.status >= _CLIENT_ERROR:
                detail = self._client.error(response)
                return Outcome(
                    PublicationStatus.FAILED, error=f"El servidor no pudo procesar el medio: {detail}"
                )
        settings = as_dict(json.loads(resume.get(_OPTIONS, "{}")))
        try:
            return await self._post_all(token, _load(plan), settings)
        except NotPublished as error:
            # El servidor la rechazó: reintentar con los mismos medios daría lo mismo.
            return Outcome(PublicationStatus.FAILED, error=str(error))

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        self._client.unwrap(await self._client.call("DELETE", f"api/v1/statuses/{post_id}", token))

    # ── Las publicaciones ───────────────────────────────────────────────────────────────────────

    async def _post_all(
        self, token: Token, parts: Sequence[_Part], settings: Mapping[str, object]
    ) -> Outcome:
        common = {key: value for key, value in settings.items() if key != "reply_to"}
        first = await self._create(token, parts[0], common, as_str(settings.get("reply_to")))
        previous = first[0]
        for number, part in enumerate(parts[1:], start=2):
            try:
                previous = (await self._create(token, part, common, previous))[0]
            except (TokenRejected, ProviderError, TransportError) as error:
                # El comienzo del hilo ya salió: no es un fracaso, y repetirlo lo duplicaría.
                return Outcome(
                    PublicationStatus.PUBLISHED_WITH_ERROR,
                    post_id=first[0],
                    url=first[1],
                    error=f"El hilo quedó cortado en la parte {number}: {error}",
                )
        return Outcome(PublicationStatus.PUBLISHED, post_id=first[0], url=first[1])

    async def _create(
        self, token: Token, part: _Part, common: Mapping[str, object], reply_to: str | None
    ) -> tuple[str, str | None]:
        body: dict[str, object] = {**common, "status": part.text}
        if part.media:
            body["media_ids"] = list(part.media)
        if reply_to:
            body["in_reply_to_id"] = reply_to
        payload = Payload(
            {"Idempotency-Key": part.key},
            "lleva una clave de idempotencia: el servidor no la publica dos veces",
            json=body,
        )
        response = await self._client.send("api/v1/statuses", token, payload)
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            # Un 4xx es un rechazo: el servidor no creó nada.
            raise self._not_published(self._client.error(response), response.status)
        created = self._client.unwrap(response)
        post_id = as_str(created.get("id"))
        if post_id is None:
            # Respondió bien: la publicación existe. No se puede decir que no salió.
            raise ProviderError(
                self._client.flavor.provider, "El servidor creó la publicación pero no devolvió su id."
            )
        return post_id, as_str(created.get("url"))

    # ── Los medios ──────────────────────────────────────────────────────────────────────────────

    async def _upload(self, token: Token, media: Media) -> tuple[str, bool]:
        """El id del medio, y si ya está listo para usar."""
        try:
            return await self._send(token, media)
        except TransportError as error:
            raise NotPublished(self._client.flavor.provider, f"La subida se cortó: {error}") from error
        except (TokenRejected, ProviderError) as error:
            raise self._not_published(error) from error

    async def _send(self, token: Token, media: Media) -> tuple[str, bool]:
        file = media.upload
        boundary = f"omnisocial-{self._ids.new_id()}"
        body = multipart(boundary, await file.read(0, file.size), file.content_type, media.alt_text)
        payload = Payload(
            {"Content-Type": f"multipart/form-data; boundary={boundary}"},
            "sube un archivo; no publica nada",
            content=body,
        )
        response = await self._client.send("api/v2/media", token, payload)
        media_id = as_str(self._client.unwrap(response).get("id"))
        if media_id is None:
            raise ProviderError(self._client.flavor.provider, "El servidor no devolvió el id del medio.")
        return media_id, response.status != _PROCESSING
