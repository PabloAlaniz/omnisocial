"""Transporte con httpx."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params, TransportError

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class HttpxTransport(HttpTransport):
    """Usa un `httpx.AsyncClient` propio o el que se le pase (para compartir el pool)."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

    @override
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Params | None = None,
        json: Mapping[str, object] | None = None,
        form: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        retry_safe: str | None = None,
    ) -> HttpResponse:
        # `params=None` y no `{}`: con un dict vacío httpx borra la query de la URL, y las URLs de
        # paginación traen ahí el cursor y el token.
        try:
            response = await self._client.request(
                method, url, params=params or None, json=json, data=form, headers=headers
            )
        except httpx.TransportError as error:
            raise TransportError(f"{method} {httpx.URL(url).host}: {type(error).__name__}") from error
        data: Any
        try:
            data = response.json()
        except ValueError:
            data = None
        return HttpResponse(
            status=response.status_code, data=data, text=response.text, headers=dict(response.headers)
        )

    async def aclose(self) -> None:
        await self._client.aclose()
