"""Transporte con httpx."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from omnisocial.adapters.http.transport import HttpResponse, Params

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class HttpxTransport:
    """Usa un `httpx.AsyncClient` propio o el que se le pase (para compartir el pool)."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Params | None = None,
        json: Mapping[str, object] | None = None,
    ) -> HttpResponse:
        response = await self._client.request(method, url, params=params, json=json)
        data: Any
        try:
            data = response.json()
        except ValueError:
            data = None
        return HttpResponse(status=response.status_code, data=data, text=response.text)

    async def aclose(self) -> None:
        await self._client.aclose()
