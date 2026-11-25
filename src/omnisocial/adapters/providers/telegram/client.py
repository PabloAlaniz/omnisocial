"""Cliente mínimo de la Bot API.

El token del bot va en la URL de cada pedido. Por eso los errores se arman solo con lo que respondió
Telegram, nunca con la URL.
"""

from __future__ import annotations

import json as jsonlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport
from omnisocial.adapters.providers.telegram.config import TELEGRAM, TelegramConfig
from omnisocial.adapters.providers.telegram.spec import ERRORS
from omnisocial.domain.errors import OmnisocialError, ProviderError, TokenRejected

_CLIENT_ERROR = 400
TOKEN = re.compile(r"\d+:[A-Za-z0-9_-]{30,}")
"""La forma de un token de bot: el id del bot, dos puntos y una clave."""


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def from_epoch(value: object) -> datetime | None:
    seconds = as_int(value)
    return datetime.fromtimestamp(seconds, UTC) if seconds is not None else None


@dataclass(frozen=True, slots=True)
class Upload:
    """Un archivo que viaja en el pedido, con el nombre del campo donde va."""

    field: str
    data: bytes
    content_type: str


def multipart(boundary: str, fields: Mapping[str, str], files: Sequence[Upload]) -> bytes:
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    parts.extend(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file.field}"; filename="{file.field}"\r\n'
        f"Content-Type: {file.content_type}\r\n\r\n".encode()
        + file.data
        + b"\r\n"
        for file in files
    )
    return b"".join(parts) + f"--{boundary}--\r\n".encode()


def api_error(response: HttpResponse) -> OmnisocialError:
    body = as_dict(response.data)
    status = as_int(body.get("error_code")) or response.status
    message = as_str(body.get("description")) or f"HTTP {response.status}"
    retry_after = as_int(as_dict(body.get("parameters")).get("retry_after"))
    return ERRORS.error(
        TELEGRAM,
        message,
        status=status,
        retry_after=float(retry_after) if retry_after is not None else response.retry_after(),
    )


def unwrap(response: HttpResponse) -> object:
    """El `result` de una respuesta. Telegram dice si salió bien en `ok`, además de en el estado."""
    body = as_dict(response.data)
    if response.status >= _CLIENT_ERROR or body.get("ok") is not True:
        raise api_error(response)
    return body.get("result")


class TelegramClient:
    def __init__(self, config: TelegramConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = transport

    @property
    def config(self) -> TelegramConfig:
        return self._config

    def _url(self, token: str, method: str) -> str:
        if not TOKEN.fullmatch(token):
            # Va en la URL: lo que no tiene forma de token no se manda a ningún lado.
            raise TokenRejected(TELEGRAM, "Eso no tiene la forma de un token de bot de Telegram.")
        return f"{self._config.api_base}/bot{token}/{method}"

    async def call(
        self, token: str, method: str, params: Mapping[str, object] | None = None, *, read: bool = False
    ) -> HttpResponse:
        """`read` marca un pedido que no manda nada a nadie y se puede repetir."""
        return await self._transport.request(
            "POST",
            self._url(token, method),
            json=dict(params or {}),
            retry_safe="no manda nada a ningún chat" if read else None,
        )

    async def upload(
        self, token: str, method: str, params: Mapping[str, object], *, files: Sequence[Upload], boundary: str
    ) -> HttpResponse:
        """Un pedido con archivos. Los valores que no son texto van como JSON."""
        fields = {
            name: value if isinstance(value, str) else jsonlib.dumps(value) for name, value in params.items()
        }
        return await self._transport.request(
            "POST",
            self._url(token, method),
            content=multipart(boundary, fields, files),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    async def get(
        self, token: str, method: str, params: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        result = unwrap(await self.call(token, method, params, read=True))
        if not isinstance(result, dict):
            raise ProviderError(TELEGRAM, f"Telegram respondió `{method}` con algo inesperado.")
        return result
