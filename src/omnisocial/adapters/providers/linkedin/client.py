"""Cliente mínimo de la API de LinkedIn: la versión, el protocolo Rest.li y los errores.

Las URLs se arman a mano. Rest.li 2.0 quiere los URN codificados (`urn%3Ali%3Ashare%3A1`) pero los
paréntesis y las comas de `List(...)` sin codificar, y un cliente HTTP común codifica todo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from urllib.parse import quote

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport
from omnisocial.adapters.providers.linkedin.config import LINKEDIN, LinkedInConfig
from omnisocial.adapters.providers.linkedin.spec import ERRORS
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


def from_millis(value: object) -> datetime | None:
    millis = as_int(value)
    return datetime.fromtimestamp(millis / 1000, UTC) if millis is not None else None


def encode(value: str) -> str:
    """Un URN para ir en la ruta o en la query."""
    return quote(value, safe="")


def api_error(response: HttpResponse) -> OmnisocialError:
    body = as_dict(response.data)
    code = as_str(body.get("code"))
    if code is None and as_int(body.get("serviceErrorCode")) is not None:
        # Las respuestas viejas no traen `code`: queda el número.
        code = str(body["serviceErrorCode"])
    message = as_str(body.get("message")) or response.text[:300] or f"HTTP {response.status}"
    return ERRORS.error(
        LINKEDIN, message, status=response.status, code=code, retry_after=response.retry_after()
    )


def unwrap(response: HttpResponse) -> dict[str, object]:
    if response.status >= _CLIENT_ERROR:
        raise api_error(response)
    return as_dict(response.data)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class LinkedInClient:
    def __init__(self, config: LinkedInConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = transport

    @property
    def config(self) -> LinkedInConfig:
        return self._config

    @property
    def transport(self) -> HttpTransport:
        return self._transport

    def _headers(self, token: str, method: str | None) -> dict[str, str]:
        headers = {
            **bearer(token),
            "LinkedIn-Version": self._config.api_version,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        if method is not None:
            headers["X-RestLi-Method"] = method
        return headers

    async def userinfo(self, token: str) -> dict[str, object]:
        """La identidad, por OpenID Connect. No es parte de la API con versión."""
        response = await self._transport.request(
            "GET", f"{self._config.api_base}/v2/userinfo", headers=bearer(token)
        )
        return unwrap(response)

    async def call(
        self,
        method: str,
        path: str,
        token: str,
        *,
        json: Mapping[str, object] | None = None,
        restli_method: str | None = None,
        read: bool = False,
    ) -> HttpResponse:
        """`path` ya trae la query armada. `read` marca un POST que es una lectura o no crea nada."""
        return await self._transport.request(
            method,
            f"{self._config.api_base}/rest/{path.lstrip('/')}",
            json=json,
            headers=self._headers(token, restli_method),
            retry_safe="no crea nada visible en LinkedIn" if read else None,
        )

    async def get(self, path: str, token: str, *, finder: bool = False) -> dict[str, object]:
        return unwrap(await self.call("GET", path, token, restli_method="FINDER" if finder else None))

    async def pages(self, path: str, token: str) -> AsyncIterator[list[dict[str, object]]]:
        """Recorre un buscador con `start` y `count`. Una página puede traer menos de lo pedido: se sigue
        mientras LinkedIn diga que hay otra."""
        count = self._config.page_size
        start = 0
        while True:
            page = await self.get(f"{path}&count={count}&start={start}", token, finder=True)
            elements = as_list(page.get("elements"))
            yield elements
            links = as_list(as_dict(page.get("paging")).get("links"))
            if not elements or not any(link.get("rel") == "next" for link in links):
                return
            start += count
