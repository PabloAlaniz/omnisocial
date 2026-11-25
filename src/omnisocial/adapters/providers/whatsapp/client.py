"""Cliente mínimo de la Graph API para WhatsApp Business."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params
from omnisocial.adapters.providers.whatsapp.config import WHATSAPP, WhatsAppConfig
from omnisocial.adapters.providers.whatsapp.spec import ERRORS, PERMISSION
from omnisocial.domain.errors import OmnisocialError

_CLIENT_ERROR = 400
_PERMISSION_CODES = range(200, 300)
_GENERAL_PERMISSION = 10
_MAX_PAGES = 20


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def from_epoch(value: object) -> datetime | None:
    """Los avisos traen la hora en segundos, como texto."""
    try:
        return datetime.fromtimestamp(int(str(value)), UTC) if value is not None else None
    except ValueError:
        return None


def api_error(response: HttpResponse) -> OmnisocialError:
    error = as_dict(as_dict(response.data).get("error"))
    number = as_int(error.get("code"))
    code = str(number) if number is not None else None
    if number == _GENERAL_PERMISSION or (number is not None and number in _PERMISSION_CODES):
        code = PERMISSION
    details = as_str(as_dict(error.get("error_data")).get("details"))
    message = as_str(error.get("message")) or response.text[:300] or f"HTTP {response.status}"
    return ERRORS.error(
        WHATSAPP,
        f"{message} ({details})" if details else message,
        status=response.status,
        code=code,
        retry_after=response.retry_after(),
    )


def unwrap(response: HttpResponse) -> dict[str, object]:
    if response.status >= _CLIENT_ERROR:
        raise api_error(response)
    return as_dict(response.data)


class WhatsAppClient:
    def __init__(self, config: WhatsAppConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = transport

    @property
    def config(self) -> WhatsAppConfig:
        return self._config

    @property
    def transport(self) -> HttpTransport:
        return self._transport

    async def get(self, path: str, token: str, params: Params | None = None) -> dict[str, object]:
        response = await self._transport.request(
            "GET",
            f"{self._config.api_base}/{path.lstrip('/')}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        return unwrap(response)

    async def post(self, path: str, token: str, json: Mapping[str, object]) -> dict[str, object]:
        response = await self._transport.request(
            "POST",
            f"{self._config.api_base}/{path.lstrip('/')}",
            json=json,
            headers={"Authorization": f"Bearer {token}"},
        )
        return unwrap(response)

    async def inspect(self, token: str) -> dict[str, object]:
        """Lo que Meta dice del token: a qué cuentas tiene acceso con cada permiso. Se pide con las
        credenciales de la app."""
        app_token = f"{self._config.app_id}|{self._config.app_secret}"
        data = await self.get("debug_token", app_token, {"input_token": token})
        return as_dict(data.get("data"))

    async def pages(
        self, path: str, token: str, params: Params | None = None
    ) -> AsyncIterator[list[dict[str, object]]]:
        query: dict[str, str | int] = {**(params or {}), "limit": 100}
        for _ in range(_MAX_PAGES):
            page = await self.get(path, token, query)
            yield as_list(page.get("data"))
            paging = as_dict(page.get("paging"))
            after = as_str(as_dict(paging.get("cursors")).get("after"))
            if after is None or not paging.get("next"):
                return
            query["after"] = after
