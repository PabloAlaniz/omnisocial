"""Cliente mínimo del protocolo de Bluesky (XRPC): el servidor del token, los errores y la paginación."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport
from omnisocial.adapters.providers.bluesky.config import BLUESKY, BlueskyConfig
from omnisocial.adapters.providers.bluesky.spec import ERRORS
from omnisocial.application.ports import Clock
from omnisocial.domain.errors import OmnisocialError
from omnisocial.domain.token import Token

_CLIENT_ERROR = 400
_TOO_MANY_REQUESTS = 429

Query = Mapping[str, str | int]


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


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


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class BlueskyClient:
    def __init__(self, config: BlueskyConfig, transport: HttpTransport, clock: Clock) -> None:
        self._config = config
        self._transport = transport
        self._clock = clock

    @property
    def config(self) -> BlueskyConfig:
        return self._config

    @property
    def clock(self) -> Clock:
        return self._clock

    def url(self, server: str | None, method: str) -> str:
        return f"https://{server or self._config.default_server}/xrpc/{method}"

    def error(self, response: HttpResponse) -> OmnisocialError:
        body = as_dict(response.data)
        message = as_str(body.get("message")) or response.text[:300] or f"HTTP {response.status}"
        return ERRORS.error(
            BLUESKY,
            message,
            status=response.status,
            code=as_str(body.get("error")),
            retry_after=self._retry_after(response),
        )

    def _retry_after(self, response: HttpResponse) -> float | None:
        """Bluesky dice cuándo vuelve el límite con una hora (`ratelimit-reset`), no con una espera."""
        reset = response.header("ratelimit-reset") or ""
        if response.status != _TOO_MANY_REQUESTS or not reset.isdigit():
            return response.retry_after()
        return max(0.0, int(reset) - self._clock.now().timestamp())

    def unwrap(self, response: HttpResponse) -> dict[str, object]:
        if response.status >= _CLIENT_ERROR:
            raise self.error(response)
        return as_dict(response.data)

    async def transport_request(
        self,
        server: str,
        method: str,
        *,
        json: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Un procedimiento de sesión: no lleva el token de acceso, y no crea nada en la cuenta."""
        return await self._transport.request(
            "POST",
            self.url(server, method),
            json=json,
            headers=headers,
            retry_safe="es de sesión: no publica nada en la cuenta",
        )

    async def get(self, method: str, token: Token, params: Query) -> dict[str, object]:
        response = await self._transport.request(
            "GET", self.url(token.server, method), params=params, headers=bearer(token.access_token)
        )
        return self.unwrap(response)

    async def get_public(self, method: str, params: Query) -> HttpResponse:
        """Sin token: solo datos públicos."""
        return await self._transport.request("GET", f"{self._config.public_api}/xrpc/{method}", params=params)

    async def call(
        self, method: str, token: Token, body: Mapping[str, object], *, read: bool = False
    ) -> HttpResponse:
        """Un procedimiento (POST). `read` marca uno que no crea nada visible."""
        return await self._transport.request(
            "POST",
            self.url(token.server, method),
            json=body,
            headers=bearer(token.access_token),
            retry_safe="no crea nada visible en la cuenta" if read else None,
        )

    async def upload(self, token: Token, data: bytes, content_type: str) -> dict[str, object]:
        """Sube un archivo y devuelve su referencia. Hasta que un post la usa, no se ve en ningún lado."""
        response = await self._transport.request(
            "POST",
            self.url(token.server, "com.atproto.repo.uploadBlob"),
            content=data,
            headers={**bearer(token.access_token), "Content-Type": content_type},
            retry_safe="sube un archivo; no publica nada",
        )
        return as_dict(self.unwrap(response).get("blob"))

    async def pages(
        self, method: str, token: Token, params: Query, key: str
    ) -> AsyncIterator[list[dict[str, object]]]:
        """Recorre `cursor`. Quien llama decide cuándo cortar."""
        query = dict(params)
        while True:
            page = await self.get(method, token, query)
            yield as_list(page.get(key))
            cursor = as_str(page.get("cursor"))
            if cursor is None or not page.get(key):
                return
            query["cursor"] = cursor
