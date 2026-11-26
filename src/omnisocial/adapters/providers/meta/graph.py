"""Cliente mínimo de la Graph API: firma, errores y paginación."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params
from omnisocial.adapters.providers.meta.config import META, MetaConfig
from omnisocial.adapters.providers.meta.spec import ERRORS, TOKEN_DEAD_CODES
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.provider import ProviderId
from omnisocial.domain.window import TimeWindow

_SUCCESS = range(200, 300)

PERMISSION_CODE = "10"
"""Falta un permiso para un campo. A veces conviene reintentar sin ese campo."""


def parse_time(value: object) -> datetime | None:
    """Fechas de la Graph API: ISO con `+0000` o segundos desde 1970."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        seconds = value / 1000 if value > 10**11 else value
        return datetime.fromtimestamp(seconds, UTC)
    if not isinstance(value, str) or not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(value, fmt).astimezone(UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def unix(moment: datetime) -> int:
    return int(moment.timestamp())


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def as_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def summary_count(node: object, key: str = "total_count") -> int | None:
    """`likes.summary(true)` devuelve `{"summary": {"total_count": n}}`."""
    return as_int(as_dict(as_dict(node).get("summary")).get(key))


def _table_code(code: int | None, subcode: int | None) -> str | None:
    """El código con el que se busca en la tabla: `código/subcódigo` si la tabla lo distingue."""
    if code is None:
        return None
    precise = f"{code}/{subcode}"
    return precise if subcode is not None and precise in ERRORS.codes else str(code)


class GraphClient:
    def __init__(self, config: MetaConfig, transport: HttpTransport, *, provider: ProviderId = META) -> None:
        """`provider`: a nombre de qué red van los errores. La misma API sirve a Meta y a Instagram con
        login propio."""
        self._config = config
        self._transport = transport
        self._provider = provider

    @property
    def config(self) -> MetaConfig:
        return self._config

    def _url(self, path: str) -> str:
        return f"{self._config.base}/{path.lstrip('/')}"

    def _auth(self, access_token: str) -> dict[str, str | int]:
        params: dict[str, str | int] = {"access_token": access_token}
        if self._config.use_appsecret_proof and self._config.app_secret:
            params["appsecret_proof"] = hmac.new(
                self._config.app_secret.encode(), access_token.encode(), hashlib.sha256
            ).hexdigest()
        return params

    async def get(self, path: str, token: str, params: Params | None = None) -> dict[str, object]:
        response = await self._transport.request(
            "GET", self._url(path), params={**(params or {}), **self._auth(token)}
        )
        return self._unwrap(response)

    async def get_app(self, path: str, params: Params) -> dict[str, object]:
        """Llamadas firmadas con la app y no con un token de usuario (el canje del código, por ejemplo)."""
        response = await self._transport.request("GET", self._url(path), params=params)
        return self._unwrap(response)

    async def post(
        self,
        path: str,
        token: str,
        *,
        params: Params | None = None,
        json: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        response = await self._transport.request(
            "POST", self._url(path), params={**(params or {}), **self._auth(token)}, json=json
        )
        return self._unwrap(response)

    async def post_video(self, path: str, token: str, *, json: Mapping[str, object]) -> dict[str, object]:
        """Los videos se crean en un servidor aparte de la Graph API."""
        url = f"{self._config.video_base}/{path.lstrip('/')}"
        response = await self._transport.request("POST", url, params=self._auth(token), json=json)
        return self._unwrap(response)

    async def delete(self, path: str, token: str) -> dict[str, object]:
        response = await self._transport.request("DELETE", self._url(path), params=self._auth(token))
        return self._unwrap(response)

    async def paginate(
        self, path: str, token: str, params: Params | None = None
    ) -> AsyncIterator[list[dict[str, object]]]:
        """Recorre `paging.next` página por página. Quien llama decide cuándo cortar."""
        page = await self.get(path, token, params)
        while True:
            yield as_list(page.get("data"))
            next_url = as_str(as_dict(page.get("paging")).get("next"))
            if not next_url:
                return
            # `next` ya trae el token y la firma.
            page = self._unwrap(await self._transport.request("GET", next_url))

    async def collect(
        self,
        path: str,
        token: str,
        params: Params | None,
        *,
        time_field: str | None = None,
        window: TimeWindow = TimeWindow(),
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        """Junta items aplicando la ventana y el tope por código.

        Algunos edges ignoran `since`/`until` (el de media de Instagram, por ejemplo), así que el corte por
        código es la única garantía. Los edges vienen del más nuevo al más viejo: cuando una página entera
        quedó antes de la ventana, no hay nada más adelante.
        """
        items: list[dict[str, object]] = []
        # Solo se corta por fecha si los items la traen y la ventana tiene comienzo.
        cuts_by_date = bool(time_field) and window.since is not None
        async for page in self.paginate(path, token, params):
            any_recent = False
            for item in page:
                moment = parse_time(item.get(time_field)) if time_field else None
                if window.is_before(moment):
                    continue
                any_recent = True
                if not window.contains(moment):
                    continue
                items.append(item)
                if limit is not None and len(items) >= limit:
                    return items
            if page and cuts_by_date and not any_recent:
                break
        return items

    def _unwrap(self, response: HttpResponse) -> dict[str, object]:
        body = as_dict(response.data)
        if response.status in _SUCCESS and "error" not in body:
            if isinstance(response.data, dict):
                return body
            if response.data is True or response.text.strip() in {"", "true"}:
                return {"success": True}
            raise ProviderError(self._provider, "La Graph API no devolvió JSON.", status=response.status)
        error = as_dict(body.get("error"))
        code = as_int(error.get("code"))
        subcode = as_int(error.get("error_subcode"))
        message = as_str(error.get("message")) or response.text[:300] or f"HTTP {response.status}"
        if code in TOKEN_DEAD_CODES:
            message = f"Meta rechazó el token: {message}"
        raise ERRORS.error(
            self._provider,
            message,
            status=response.status,
            code=_table_code(code, subcode),
            retry_after=response.retry_after(),
        )
