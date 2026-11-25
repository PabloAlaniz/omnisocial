"""Cabeceras que una red pide en todos los pedidos, envolviendo cualquier transporte."""

from __future__ import annotations

from collections.abc import Mapping

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params


class HeaderTransport(HttpTransport):
    """Le suma cabeceras fijas a todo pedido (un `User-Agent` propio, por ejemplo), también a los que
    arma el OAuth estándar. Las del pedido mandan si coinciden."""

    def __init__(self, inner: HttpTransport, headers: Mapping[str, str]) -> None:
        self._inner = inner
        self._headers = dict(headers)

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
        content: bytes | None = None,
    ) -> HttpResponse:
        return await self._inner.request(
            method,
            url,
            params=params,
            json=json,
            form=form,
            headers={**self._headers, **(headers or {})},
            retry_safe=retry_safe,
            content=content,
        )
