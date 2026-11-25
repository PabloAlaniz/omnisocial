"""Cliente mínimo de la API de Threads: el token, los errores y la paginación.

Es de Meta y se parece a la Graph API, pero es otra: otro servidor, otra app y otros tokens.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params
from omnisocial.adapters.providers.threads.config import THREADS, ThreadsConfig
from omnisocial.adapters.providers.threads.spec import ERRORS
from omnisocial.domain.errors import OmnisocialError

_CLIENT_ERROR = 400


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
    """Fechas con `+0000`, como las de la Graph API."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def api_error(response: HttpResponse) -> OmnisocialError:
    error = as_dict(as_dict(response.data).get("error"))
    message = as_str(error.get("message")) or response.text[:300] or f"HTTP {response.status}"
    return ERRORS.error(
        THREADS,
        message,
        status=response.status,
        code=as_str(error.get("code")),
        retry_after=response.retry_after(),
    )


def unwrap(response: HttpResponse) -> dict[str, object]:
    body = as_dict(response.data)
    if response.status >= _CLIENT_ERROR or "error" in body:
        raise api_error(response)
    return body


class ThreadsClient:
    def __init__(self, config: ThreadsConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = transport

    @property
    def config(self) -> ThreadsConfig:
        return self._config

    @property
    def transport(self) -> HttpTransport:
        return self._transport

    def _url(self, path: str) -> str:
        return f"{self._config.base}/{path.lstrip('/')}"

    async def get(self, path: str, token: str, params: Params | None = None) -> dict[str, object]:
        response = await self._transport.request(
            "GET", self._url(path), params={**(params or {}), "access_token": token}
        )
        return unwrap(response)

    async def post(self, path: str, token: str, fields: Mapping[str, str]) -> HttpResponse:
        """La respuesta tal cual, para quien necesita distinguir un rechazo de una falla. Los datos van
        en el cuerpo: un texto con links no entra bien en una URL."""
        return await self._transport.request("POST", self._url(path), form={**fields, "access_token": token})

    async def delete(self, path: str, token: str) -> dict[str, object]:
        response = await self._transport.request("DELETE", self._url(path), params={"access_token": token})
        return unwrap(response)

    async def pages(self, path: str, token: str, params: Params) -> AsyncIterator[list[dict[str, object]]]:
        """Recorre `paging.cursors.after`. Quien llama decide cuándo cortar."""
        query = dict(params)
        while True:
            page = await self.get(path, token, query)
            yield as_list(page.get("data"))
            after = as_str(as_dict(as_dict(page.get("paging")).get("cursors")).get("after"))
            if after is None or not page.get("data"):
                return
            query["after"] = after
