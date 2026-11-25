"""Cliente mínimo de la API de Mastodon: el servidor del token, los errores y la paginación."""

from __future__ import annotations

import html
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params
from omnisocial.adapters.providers.mastodon.config import Flavor
from omnisocial.adapters.providers.mastodon.spec import ERRORS, OUT_OF_SCOPE
from omnisocial.application.ports import Clock
from omnisocial.domain.errors import OmnisocialError, ProviderError
from omnisocial.domain.token import Token

_CLIENT_ERROR = 400
_TOO_MANY_REQUESTS = 429
_BREAK = re.compile(r"<br\s*/?>|</p>\s*<p>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def as_str(value: object) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def plain(content: object) -> str | None:
    """El texto de una publicación. Viene como HTML: se sacan las etiquetas y se conservan los saltos."""
    if not isinstance(content, str) or not content:
        return None
    return html.unescape(_TAG.sub("", _BREAK.sub("\n", content))).strip() or None


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass(frozen=True, slots=True)
class Payload:
    """Lo que lleva un POST con cabeceras propias."""

    headers: Mapping[str, str]
    repeatable: str
    """Por qué se puede repetir sin efectos."""
    json: Mapping[str, object] | None = None
    content: bytes | None = field(default=None, repr=False)


class MastodonClient:
    def __init__(self, flavor: Flavor, transport: HttpTransport, clock: Clock) -> None:
        self._flavor = flavor
        self._transport = transport
        self._clock = clock

    @property
    def flavor(self) -> Flavor:
        return self._flavor

    @property
    def transport(self) -> HttpTransport:
        return self._transport

    @staticmethod
    def url(server: str, path: str) -> str:
        return f"https://{server}/{path.lstrip('/')}"

    def server_of(self, token: Token) -> str:
        if token.server is None:
            raise ProviderError(self._flavor.provider, "El token no dice de qué servidor es.")
        return token.server

    def error(self, response: HttpResponse) -> OmnisocialError:
        body = as_dict(response.data)
        message = (
            as_str(body.get("error_description"))
            or as_str(body.get("error"))
            or response.text[:300]
            or f"HTTP {response.status}"
        )
        # El protocolo no tiene códigos de error: el permiso faltante se reconoce por el mensaje.
        code = OUT_OF_SCOPE if "outside the authorized scopes" in message else None
        return ERRORS.error(
            self._flavor.provider,
            message,
            status=response.status,
            code=code,
            retry_after=self._retry_after(response),
        )

    def _retry_after(self, response: HttpResponse) -> float | None:
        """El límite dice cuándo vuelve con una fecha (`X-RateLimit-Reset`), no con una espera."""
        reset = parse_time(response.header("x-ratelimit-reset"))
        if response.status != _TOO_MANY_REQUESTS or reset is None:
            return response.retry_after()
        return max(0.0, (reset - self._clock.now()).total_seconds())

    def unwrap(self, response: HttpResponse) -> dict[str, object]:
        if response.status >= _CLIENT_ERROR:
            raise self.error(response)
        return as_dict(response.data)

    async def call(
        self,
        method: str,
        path: str,
        token: Token,
        *,
        params: Params | None = None,
        json: Mapping[str, object] | None = None,
        repeatable: str | None = None,
    ) -> HttpResponse:
        """La respuesta tal cual. `repeatable` dice por qué un POST se puede repetir sin efectos."""
        return await self._transport.request(
            method,
            self.url(self.server_of(token), path),
            params=params,
            json=json,
            headers=bearer(token.access_token),
            retry_safe=repeatable,
        )

    async def send(self, path: str, token: Token, payload: Payload) -> HttpResponse:
        """Un POST con cabeceras propias: una subida, o una publicación con su clave de idempotencia."""
        return await self._transport.request(
            "POST",
            self.url(self.server_of(token), path),
            json=payload.json,
            content=payload.content,
            headers={**bearer(token.access_token), **payload.headers},
            retry_safe=payload.repeatable,
        )

    async def get(self, path: str, token: Token, params: Params | None = None) -> dict[str, object]:
        return self.unwrap(await self.call("GET", path, token, params=params))

    async def items(self, path: str, token: Token, params: Params) -> AsyncIterator[list[dict[str, object]]]:
        """Recorre una lista con `max_id`: cada página pide lo anterior al último de la página previa."""
        query = dict(params)
        while True:
            response = await self.call("GET", path, token, params=query)
            if response.status >= _CLIENT_ERROR:
                raise self.error(response)
            page = as_list(response.data)
            yield page
            last = as_str(page[-1].get("id")) if page else None
            if last is None:
                return
            query["max_id"] = last
