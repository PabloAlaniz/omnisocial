"""Publicar un pin.

- Con imágenes es un solo pedido: van por URL o dentro del pedido, en base64.
- Con un video son etapas: se registra la subida, se manda el archivo, Pinterest lo procesa y recién
  entonces se crea el pin. Mientras procesa, la publicación queda pendiente y se retoma.

Hasta que se crea el pin no hay nada publicado: si algo falla antes, con certeza no salió.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping

from typing_extensions import override

from omnisocial.adapters.http.transport import TransportError
from omnisocial.adapters.providers.pinterest.client import (
    PinterestClient,
    api_error,
    as_dict,
    as_str,
    unwrap,
)
from omnisocial.adapters.providers.pinterest.config import PINTEREST, PinterestOptions
from omnisocial.adapters.providers.pinterest.reading import pin_url
from omnisocial.application.ports import IdGenerator, Publisher
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ErrorKind, NotPublished, OmnisocialError, ProviderError, TokenRejected
from omnisocial.domain.publishing import Draft, Media, MediaKind, Outcome, PublicationStatus
from omnisocial.domain.token import Token

_CLIENT_ERROR = 400
_SERVER_ERROR = 500
# Errores que ya dicen por qué no salió: el núcleo los traduce a su propia negativa.
_SAYS_WHY = frozenset(
    {
        ErrorKind.MISSING_PERMISSION,
        ErrorKind.RATE_LIMITED,
        ErrorKind.QUOTA_EXHAUSTED,
        ErrorKind.INVALID_REQUEST,
    }
)
_READY, _FAILED = "succeeded", "failed"


def _not_published(error: OmnisocialError, status: int | None = None) -> OmnisocialError:
    """Un error antes de crear el pin: con certeza no salió."""
    if isinstance(error, TokenRejected) or (isinstance(error, ProviderError) and error.kind in _SAYS_WHY):
        return error
    return NotPublished(PINTEREST, str(error), status=status)


def multipart(boundary: str, fields: Mapping[str, str], file: bytes, content_type: str) -> bytes:
    """El formulario de la subida: los campos que dio Pinterest y, al final, el archivo."""
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="media"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode()
        + file
        + b"\r\n"
    )
    return b"".join(parts) + f"--{boundary}--\r\n".encode()


async def _image(media: Media) -> dict[str, object]:
    if media.url is not None:
        return {"url": media.url}
    file = media.upload
    data = await file.read(0, file.size)
    return {"content_type": file.content_type, "data": base64.b64encode(data).decode()}


async def _images(media: tuple[Media, ...]) -> dict[str, object]:
    """Una imagen, o un carrusel de 2 a 5. En un carrusel todas van por URL o todas como archivo."""
    by_url = media[0].url is not None
    if any((item.url is not None) != by_url for item in media):
        raise ProviderError(
            PINTEREST,
            "En un carrusel todas las imágenes van por URL o todas como archivo.",
            kind=ErrorKind.INVALID_REQUEST,
        )
    kind = "url" if by_url else "base64"
    if len(media) == 1:
        return {"source_type": f"image_{kind}", **await _image(media[0])}
    plural = "urls" if by_url else "base64"
    return {"source_type": f"multiple_image_{plural}", "items": [await _image(item) for item in media]}


def _pin(draft: Draft, options: PinterestOptions, source: Mapping[str, object]) -> dict[str, object]:
    fields: dict[str, object | None] = {
        "board_id": options.board_id,
        "board_section_id": options.board_section_id,
        "title": options.title,
        "description": draft.text or None,
        "link": options.link,
        "alt_text": next((media.alt_text for media in draft.media if media.alt_text), None),
        "media_source": dict(source),
    }
    return {name: value for name, value in fields.items() if value is not None}


def _video_source(media_id: str, options: PinterestOptions) -> dict[str, object]:
    if options.cover_image_url:
        return {"source_type": "video_id", "media_id": media_id, "cover_image_url": options.cover_image_url}
    return {
        "source_type": "video_id",
        "media_id": media_id,
        "cover_image_key_frame_time": options.cover_second,
    }


class PinterestPublisher(Publisher):
    def __init__(self, client: PinterestClient, ids: IdGenerator) -> None:
        self._client = client
        self._ids = ids

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options
        if not isinstance(options, PinterestOptions):
            raise ProviderError(
                PINTEREST, "Un pin va a un tablero: faltan las opciones.", kind=ErrorKind.INVALID_REQUEST
            )
        video = next((media for media in draft.media if media.kind is MediaKind.VIDEO), None)
        if video is None:
            return await self._create(token.access_token, _pin(draft, options, await _images(draft.media)))
        media_id = await self._upload(token.access_token, video)
        pin = _pin(draft, options, _video_source(media_id, options))
        return await self._when_ready(token.access_token, media_id, json.dumps(pin))

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        media_id, pin = resume.get("media_id"), resume.get("pin")
        if not media_id or not pin:
            raise ProviderError(PINTEREST, "No hay con qué retomar esta publicación.")
        return await self._when_ready(token.access_token, media_id, pin)

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        unwrap(await self._client.call("DELETE", f"pins/{post_id}", token.access_token))

    async def _create(self, token: str, pin: Mapping[str, object]) -> Outcome:
        response = await self._client.call("POST", "pins", token, json=pin)
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            # Un 4xx es un rechazo: Pinterest no creó nada.
            raise _not_published(api_error(response), response.status)
        pin_id = as_str(unwrap(response).get("id"))
        if pin_id is None:
            # Respondió bien: el pin existe. No se puede decir que no salió.
            raise ProviderError(PINTEREST, "Pinterest creó el pin pero no devolvió su id.")
        return Outcome(PublicationStatus.PUBLISHED, post_id=pin_id, url=pin_url(pin_id))

    async def _when_ready(self, token: str, media_id: str, pin: str) -> Outcome:
        """Crea el pin si el video ya se procesó; si no, la publicación sigue pendiente."""
        try:
            status = as_str((await self._client.get(f"media/{media_id}", token)).get("status"))
        except TransportError as error:
            raise NotPublished(PINTEREST, f"No se pudo ver cómo va el video: {error}") from error
        except (TokenRejected, ProviderError) as error:
            raise _not_published(error) from error
        if status == _FAILED:
            return Outcome(PublicationStatus.FAILED, error="Pinterest no pudo procesar el video.")
        if status != _READY:
            return Outcome(PublicationStatus.PENDING, resume={"media_id": media_id, "pin": pin})
        return await self._create(token, as_dict(json.loads(pin)))

    async def _upload(self, token: str, video: Media) -> str:
        try:
            return await self._send(token, video)
        except TransportError as error:
            raise NotPublished(PINTEREST, f"La subida se cortó: {error}") from error
        except (TokenRejected, ProviderError) as error:
            raise _not_published(error) from error

    async def _send(self, token: str, video: Media) -> str:
        registered = unwrap(
            await self._client.call("POST", "media", token, json={"media_type": "video"}, read=True)
        )
        media_id, upload_url = as_str(registered.get("media_id")), as_str(registered.get("upload_url"))
        if media_id is None or upload_url is None:
            raise ProviderError(PINTEREST, "Pinterest no dijo dónde subir el video.")
        fields = {
            name: value
            for name, value in as_dict(registered.get("upload_parameters")).items()
            if isinstance(value, str)
        }
        file = video.upload
        boundary = f"omnisocial-{self._ids.new_id()}"
        body = multipart(boundary, fields, await file.read(0, file.size), file.content_type)
        # La subida va al almacenamiento que indicó Pinterest, sin el token.
        sent = await self._client.transport.request(
            "POST",
            upload_url,
            content=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            retry_safe="subir el mismo archivo otra vez no crea nada",
        )
        if sent.status >= _CLIENT_ERROR:
            raise ProviderError(PINTEREST, f"La subida del video falló (HTTP {sent.status}).")
        return media_id
