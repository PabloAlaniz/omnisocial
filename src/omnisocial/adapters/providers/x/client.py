"""Cliente mínimo de la API v2 de X: autenticación, errores y paginación."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport
from omnisocial.adapters.providers.x.config import X, XConfig
from omnisocial.adapters.providers.x.spec import ERRORS
from omnisocial.application.ports import Clock
from omnisocial.domain.errors import OmnisocialError, ProviderError

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
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _problem(body: dict[str, object]) -> tuple[str | None, str | None]:
    """El código y el mensaje de un error. X tiene dos formas: la nueva (`type`, `detail`) y la vieja
    (`errors[0].message`)."""
    kind = as_str(body.get("type")) or ""
    code = kind.rstrip("/").rsplit("/", 1)[-1] if "/problems/" in kind else None
    legacy = as_list(body.get("errors"))
    message = (
        as_str(body.get("detail"))
        or (as_str(legacy[0].get("message")) if legacy else None)
        or as_str(body.get("title"))
    )
    return code, message


class XClient:
    def __init__(self, config: XConfig, transport: HttpTransport, clock: Clock) -> None:
        self._config = config
        self._transport = transport
        self._clock = clock

    @property
    def config(self) -> XConfig:
        return self._config

    @property
    def transport(self) -> HttpTransport:
        return self._transport

    def _url(self, path: str) -> str:
        return f"{self._config.api_base}/{path.lstrip('/')}"

    def error(self, response: HttpResponse) -> OmnisocialError:
        code, message = _problem(as_dict(response.data))
        return ERRORS.error(
            X,
            message or response.text[:300] or f"HTTP {response.status}",
            status=response.status,
            code=code,
            retry_after=self._retry_after(response),
        )

    def _retry_after(self, response: HttpResponse) -> float | None:
        """X dice cuándo vuelve el límite con una hora (`x-rate-limit-reset`), no con una espera."""
        reset = response.header("x-rate-limit-reset") or ""
        if response.status != _TOO_MANY_REQUESTS or not reset.isdigit():
            return response.retry_after()
        return max(0.0, int(reset) - self._clock.now().timestamp())

    def unwrap(self, response: HttpResponse) -> dict[str, object]:
        if response.status >= _CLIENT_ERROR:
            raise self.error(response)
        return as_dict(response.data)

    async def call(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: Query | None = None,
        json: Mapping[str, object] | None = None,
        read: bool = False,
    ) -> HttpResponse:
        """`read` marca un POST que no publica nada (una parte de un medio, por ejemplo)."""
        return await self._transport.request(
            method,
            self._url(path),
            params=params,
            json=json,
            headers=bearer(token),
            retry_safe="no publica nada en la cuenta" if read else None,
        )

    async def get(self, path: str, token: str, params: Query | None = None) -> dict[str, object]:
        return self.unwrap(await self.call("GET", path, token, params=params))

    async def get_public(self, path: str, params: Query) -> dict[str, object]:
        """Con el token de la app, sin usuario: solo datos públicos."""
        if not self._config.bearer_token:
            raise ProviderError(X, "Hace falta el token de la app de X.")
        return await self.get(path, self._config.bearer_token, params)

    async def pages(self, path: str, token: str, params: Query) -> AsyncIterator[dict[str, object]]:
        """Recorre `meta.next_token`. Devuelve la página entera: los autores vienen aparte, en `includes`."""
        query = dict(params)
        while True:
            page = await self.get(path, token, query)
            yield page
            next_token = as_str(as_dict(page.get("meta")).get("next_token"))
            if next_token is None:
                return
            query["pagination_token" if "search" not in path else "next_token"] = next_token
