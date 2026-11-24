"""Cliente mínimo de las APIs de Google Business Profile. Son cuatro, cada una en su dominio."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import datetime

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params
from omnisocial.adapters.providers.google_business.config import GOOGLE_BUSINESS, GoogleBusinessConfig
from omnisocial.adapters.providers.google_business.spec import ERRORS
from omnisocial.domain.errors import OmnisocialError

_CLIENT_ERROR = 400


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def as_time(value: object) -> datetime | None:
    text = as_str(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _code(error: Mapping[str, object]) -> str | None:
    """El motivo más preciso que la tabla conozca: el de los detalles o, si no, el estado."""
    reasons = [reason for detail in as_list(error.get("details")) if (reason := as_str(detail.get("reason")))]
    known = next((reason for reason in reasons if reason in ERRORS.codes), None)
    return known or as_str(error.get("status")) or (reasons[0] if reasons else None)


def api_error(response: HttpResponse) -> OmnisocialError:
    error = as_dict(as_dict(response.data).get("error"))
    message = as_str(error.get("message")) or response.text[:300] or f"HTTP {response.status}"
    return ERRORS.error(
        GOOGLE_BUSINESS,
        message,
        status=response.status,
        code=_code(error),
        retry_after=response.retry_after(),
    )


def unwrap(response: HttpResponse) -> dict[str, object]:
    if response.status >= _CLIENT_ERROR:
        raise api_error(response)
    return as_dict(response.data)


class GoogleBusinessClient:
    def __init__(self, config: GoogleBusinessConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = transport

    @property
    def config(self) -> GoogleBusinessConfig:
        return self._config

    @property
    def transport(self) -> HttpTransport:
        return self._transport

    async def call(
        self,
        method: str,
        url: str,
        token: str,
        *,
        params: Params | None = None,
        json: Mapping[str, object] | None = None,
    ) -> HttpResponse:
        return await self._transport.request(
            method, url, params=params, json=json, headers={"Authorization": f"Bearer {token}"}
        )

    async def get(self, url: str, token: str, params: Params | None = None) -> dict[str, object]:
        return unwrap(await self.call("GET", url, token, params=params))

    async def pages(
        self, url: str, token: str, key: str, params: Params | None = None
    ) -> AsyncIterator[dict[str, object]]:
        """Recorre una lista con `pageToken`. Devuelve cada página entera: algunas traen totales además
        de los elementos, que están en `key`."""
        query: dict[str, str | int] = dict(params or {})
        for _ in range(self._config.max_pages):
            page = await self.get(url, token, query)
            yield page
            following = as_str(page.get("nextPageToken"))
            if following is None or not as_list(page.get(key)):
                return
            query["pageToken"] = following
