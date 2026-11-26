"""Cliente mínimo de la API de Discord, y cómo se arma un mensaje."""

from __future__ import annotations

import hashlib
import json as jsonlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from omnisocial.adapters.http.headers import HeaderTransport
from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params
from omnisocial.domain.errors import OmnisocialError
from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import Media, MediaKind
from omnisocial.domain.spec import ErrorTable

_CLIENT_ERROR = 400
SUPPRESS_EMBEDS = 1 << 2
SUPPRESS_NOTIFICATIONS = 1 << 12
_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class Upload:
    filename: str
    data: bytes
    content_type: str


def multipart(boundary: str, payload: Mapping[str, object], files: Sequence[Upload]) -> bytes:
    """El mensaje (`payload_json`) y sus archivos (`files[n]`), en un formulario."""
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        "Content-Type: application/json\r\n\r\n".encode()
        + jsonlib.dumps(payload).encode()
        + b"\r\n"
    ]
    parts.extend(
        f'--{boundary}\r\nContent-Disposition: form-data; name="files[{number}]"; '
        f'filename="{file.filename}"\r\nContent-Type: {file.content_type}\r\n\r\n'.encode()
        + file.data
        + b"\r\n"
        for number, file in enumerate(files)
    )
    return b"".join(parts) + f"--{boundary}--\r\n".encode()


@dataclass(frozen=True, slots=True)
class Look:
    """Cómo sale un mensaje, más allá de su contenido."""

    mentions: bool = False
    silent: bool = False
    suppress_embeds: bool = False


def _base(text: str, look: Look) -> dict[str, object]:
    body: dict[str, object] = {}
    if text:
        body["content"] = text
    if not look.mentions:
        # Sin esto, un `@everyone` en el texto le avisa a todo el servidor.
        body["allowed_mentions"] = {"parse": []}
    flags = (SUPPRESS_EMBEDS if look.suppress_embeds else 0) | (SUPPRESS_NOTIFICATIONS if look.silent else 0)
    if flags:
        body["flags"] = flags
    return body


async def _upload(item: Media, number: int) -> tuple[Upload, dict[str, object]]:
    """El archivo de un adjunto y cómo se describe en el cuerpo."""
    file = item.upload
    default = "mp4" if item.kind is MediaKind.VIDEO else "jpg"
    name = f"archivo{number}.{_EXTENSIONS.get(file.content_type, default)}"
    described = {"description": item.alt_text} if item.alt_text else {}
    upload = Upload(name, await file.read(0, file.size), file.content_type)
    return upload, {"id": number, "filename": name, **described}


async def message(text: str, media: Sequence[Media], look: Look) -> tuple[dict[str, object], list[Upload]]:
    """El cuerpo de un mensaje y los archivos que lo acompañan. Una imagen por URL va incrustada; lo
    que es un archivo, adjunto."""
    body = _base(text, look)
    embeds: list[dict[str, object]] = []
    attachments: list[dict[str, object]] = []
    files: list[Upload] = []
    for item in media:
        if item.url is not None:
            embeds.append({"image": {"url": item.url}})
            continue
        upload, attachment = await _upload(item, len(files))
        files.append(upload)
        attachments.append(attachment)
    if embeds:
        body["embeds"] = embeds
    if attachments:
        body["attachments"] = attachments
    return body, files


class DiscordClient:
    """Habla con Discord con el `User-Agent` de la app, y traduce los errores con la tabla de su red."""

    def __init__(
        self,
        transport: HttpTransport,
        *,
        api_base: str,
        user_agent: str,
        provider: ProviderId,
        errors: ErrorTable,
    ) -> None:
        self._transport = HeaderTransport(transport, {"User-Agent": user_agent})
        self._api_base = api_base
        self._provider = provider
        self._errors = errors

    @property
    def transport(self) -> HttpTransport:
        """El transporte que ya lleva el `User-Agent`."""
        return self._transport

    @property
    def provider(self) -> ProviderId:
        return self._provider

    def error(self, response: HttpResponse) -> OmnisocialError:
        body = as_dict(response.data)
        code = as_int(body.get("code"))
        message = as_str(body.get("message")) or response.text[:300] or f"HTTP {response.status}"
        wait = body.get("retry_after")
        retry_after = float(wait) if isinstance(wait, int | float) and not isinstance(wait, bool) else None
        return self._errors.error(
            self._provider,
            message,
            status=response.status,
            # El 0 es "error general": no dice nada más que el estado.
            code=str(code) if code else None,
            retry_after=retry_after if retry_after is not None else response.retry_after(),
        )

    def unwrap(self, response: HttpResponse) -> object:
        if response.status >= _CLIENT_ERROR:
            raise self.error(response)
        return response.data

    async def request(
        self,
        method: str,
        path: str,
        *,
        authorization: str | None = None,
        params: Params | None = None,
        json: Mapping[str, object] | None = None,
        retry_safe: str | None = None,
    ) -> HttpResponse:
        return await self._transport.request(
            method,
            f"{self._api_base}/{path.lstrip('/')}",
            params=params,
            json=json,
            headers={"Authorization": authorization} if authorization else None,
            retry_safe=retry_safe,
        )

    async def send(
        self,
        path: str,
        body: Mapping[str, object],
        files: Sequence[Upload],
        *,
        authorization: str | None = None,
        params: Params | None = None,
        retry_safe: str | None = None,
    ) -> HttpResponse:
        """Crea un mensaje, con archivos o sin ellos."""
        # El separador sale del contenido: el mismo pedido, repetido, es idéntico byte a byte.
        digest = hashlib.sha256(b"".join(file.data for file in files)).hexdigest()[:24]
        boundary = f"omnisocial-{digest}"
        if not files:
            return await self.request(
                "POST", path, authorization=authorization, params=params, json=body, retry_safe=retry_safe
            )
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if authorization:
            headers["Authorization"] = authorization
        return await self._transport.request(
            "POST",
            f"{self._api_base}/{path.lstrip('/')}",
            params=params,
            content=multipart(boundary, body, files),
            headers=headers,
            retry_safe=retry_safe,
        )
