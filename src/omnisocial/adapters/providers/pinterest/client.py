"""Cliente mínimo de la API v5 de Pinterest."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params
from omnisocial.adapters.providers.pinterest.config import PINTEREST, PinterestConfig
from omnisocial.adapters.providers.pinterest.spec import ERRORS
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


def as_number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def as_time(value: object) -> datetime | None:
    text = as_str(value)
    if text is None:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    # Las fechas de las métricas vienen sin hora ni zona: son días en UTC.
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _retry_after(response: HttpResponse) -> float | None:
    """`x-ratelimit-reset` dice en cuántos segundos vuelve el cupo."""
    value = response.header("x-ratelimit-reset")
    try:
        return max(0.0, float(value)) if value is not None else response.retry_after()
    except ValueError:
        return response.retry_after()


def api_error(response: HttpResponse) -> OmnisocialError:
    body = as_dict(response.data)
    code = as_int(body.get("code"))
    message = as_str(body.get("message")) or response.text[:300] or f"HTTP {response.status}"
    return ERRORS.error(
        PINTEREST,
        message,
        status=response.status,
        code=str(code) if code is not None else None,
        retry_after=_retry_after(response),
    )


def unwrap(response: HttpResponse) -> dict[str, object]:
    if response.status >= _CLIENT_ERROR:
        raise api_error(response)
    return as_dict(response.data)


class PinterestClient:
    def __init__(self, config: PinterestConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = transport

    @property
    def config(self) -> PinterestConfig:
        return self._config

    @property
    def transport(self) -> HttpTransport:
        return self._transport

    async def call(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: Params | None = None,
        json: Mapping[str, object] | None = None,
        read: bool = False,
    ) -> HttpResponse:
        """`read` marca un POST que no crea nada visible (registrar una subida)."""
        return await self._transport.request(
            method,
            f"{self._config.api_base}/{path.lstrip('/')}",
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {token}"},
            retry_safe="no crea nada visible en Pinterest" if read else None,
        )

    async def get(self, path: str, token: str, params: Params | None = None) -> dict[str, object]:
        return unwrap(await self.call("GET", path, token, params=params))

    async def pages(
        self, path: str, token: str, params: Params | None = None
    ) -> AsyncIterator[list[dict[str, object]]]:
        """Recorre una lista con `bookmark`. Una página puede venir vacía y traer igual la marca de la
        siguiente: se sigue mientras haya marca, hasta el tope de páginas."""
        query: dict[str, str | int] = {**(params or {}), "page_size": self._config.page_size}
        for _ in range(self._config.max_pages):
            page = await self.get(path, token, query)
            yield as_list(page.get("items"))
            bookmark = as_str(page.get("bookmark"))
            if bookmark is None:
                return
            query["bookmark"] = bookmark
