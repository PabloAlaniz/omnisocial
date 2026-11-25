"""Cliente mínimo de la YouTube Data API v3: autenticación, cuota, errores y paginación."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport
from omnisocial.adapters.providers.youtube.config import YOUTUBE, YouTubeConfig
from omnisocial.adapters.providers.youtube.spec import ERRORS
from omnisocial.application.quota import QuotaBudget
from omnisocial.domain.errors import OmnisocialError, ProviderError, QuotaExhausted

_CLIENT_ERROR = 400
LOCAL_BUDGET = "local_budget"
"""El código de la negativa cuando corta el presupuesto propio y no YouTube."""

# Lo que cuesta cada llamada, en unidades de cuota.
READ = 1
WRITE = 50

Query = Mapping[str, str | int]


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def as_int(value: object) -> int | None:
    """Los contadores vienen como texto."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.isdigit() else None


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def error_reason(response: HttpResponse) -> str | None:
    errors = as_list(as_dict(as_dict(response.data).get("error")).get("errors"))
    return as_str(errors[0].get("reason")) if errors else None


def api_error(response: HttpResponse) -> OmnisocialError:
    """La excepción que corresponde a una respuesta de error de YouTube."""
    error = as_dict(as_dict(response.data).get("error"))
    message = as_str(error.get("message")) or response.text[:300] or f"HTTP {response.status}"
    return ERRORS.error(
        YOUTUBE,
        message,
        status=response.status,
        code=error_reason(response),
        retry_after=response.retry_after(),
    )


class YouTubeClient:
    def __init__(
        self,
        config: YouTubeConfig,
        transport: HttpTransport,
        *,
        units: QuotaBudget | None = None,
        uploads: QuotaBudget | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._units = units
        self._uploads = uploads

    @property
    def config(self) -> YouTubeConfig:
        return self._config

    @property
    def transport(self) -> HttpTransport:
        return self._transport

    def _url(self, path: str) -> str:
        return f"{self._config.api_base}/{path.lstrip('/')}"

    async def spend(self, cost: int) -> None:
        """Anota el gasto antes de llamar. Si no entra en el presupuesto del día, no se llama."""
        if self._units is not None and not await self._units.spend(cost):
            raise QuotaExhausted(
                YOUTUBE, "El presupuesto de cuota de YouTube para hoy está agotado.", code=LOCAL_BUDGET
            )

    async def spend_upload(self) -> None:
        if self._uploads is not None and not await self._uploads.spend(1):
            raise QuotaExhausted(
                YOUTUBE, "El cupo de subidas a YouTube para hoy está agotado.", code=LOCAL_BUDGET
            )

    async def call(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: Query | None = None,
        json: Mapping[str, object] | None = None,
        cost: int = READ,
    ) -> HttpResponse:
        """La respuesta tal cual, para quien necesita mirar el error antes de decidir."""
        await self.spend(cost)
        return await self._transport.request(
            method, self._url(path), params=params, json=json, headers=bearer(token)
        )

    async def get(self, path: str, token: str, params: Query) -> dict[str, object]:
        return unwrap(await self.call("GET", path, token, params=params))

    async def get_public(self, path: str, params: Query) -> dict[str, object]:
        """Con la clave de API, sin token: solo datos públicos."""
        if not self._config.api_key:
            raise ProviderError(YOUTUBE, "Hace falta una clave de API de YouTube.")
        await self.spend(READ)
        response = await self._transport.request(
            "GET", self._url(path), params={**params, "key": self._config.api_key}
        )
        return unwrap(response)

    async def write(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: Query,
        json: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return unwrap(await self.call(method, path, token, params=params, json=json, cost=WRITE))

    async def pages(self, path: str, token: str, params: Query) -> AsyncIterator[list[dict[str, object]]]:
        """Recorre `nextPageToken` página por página. Quien llama decide cuándo cortar."""
        query = dict(params)
        while True:
            page = await self.get(path, token, query)
            yield as_list(page.get("items"))
            next_token = as_str(page.get("nextPageToken"))
            if next_token is None:
                return
            query["pageToken"] = next_token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def unwrap(response: HttpResponse) -> dict[str, object]:
    if response.status >= _CLIENT_ERROR:
        raise api_error(response)
    # Moderar y borrar responden 204, sin cuerpo.
    return as_dict(response.data)
