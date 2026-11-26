"""Cliente mínimo de la API de Reddit.

Dos cosas propias: todo pedido lleva el User-Agent de la app, y los errores llegan por tres lados (el
estado HTTP, la cabecera `WWW-Authenticate` y, en las escrituras, una lista en el cuerpo de un 200).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params
from omnisocial.adapters.providers.reddit.config import REDDIT, RedditConfig
from omnisocial.adapters.providers.reddit.spec import ERRORS
from omnisocial.domain.errors import ErrorKind, OmnisocialError, ProviderError

_CLIENT_ERROR = 400
_AUTH_ERROR = re.compile(r'error="([a-z_]+)"')
_WAIT = re.compile(r"(\d+)\s+(second|minute|hour)")
_SECONDS = {"second": 1, "minute": 60, "hour": 3600}


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def from_epoch(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value, UTC)


class UserAgentTransport(HttpTransport):
    """Le pone a todo pedido el User-Agent de la app, también al canje del código."""

    def __init__(self, inner: HttpTransport, user_agent: str) -> None:
        self._inner = inner
        self._user_agent = user_agent

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
            headers={**(headers or {}), "User-Agent": self._user_agent},
            retry_safe=retry_safe,
            content=content,
        )


def _retry_after(response: HttpResponse) -> float | None:
    """`X-Ratelimit-Reset` dice en cuántos segundos termina el período."""
    value = response.header("x-ratelimit-reset")
    try:
        return max(0.0, float(value)) if value is not None else response.retry_after()
    except ValueError:
        return response.retry_after()


def api_error(response: HttpResponse) -> OmnisocialError:
    found = _AUTH_ERROR.search(response.header("www-authenticate") or "")
    body = as_dict(response.data)
    message = as_str(body.get("message")) or response.text[:300] or f"HTTP {response.status}"
    if reason := as_str(body.get("reason")):
        message = f"{message} ({reason})"
    return ERRORS.error(
        REDDIT,
        message,
        status=response.status,
        code=found.group(1) if found else None,
        retry_after=_retry_after(response),
    )


def _wait(message: str) -> float | None:
    """Reddit dice cuánto esperar en el mensaje: "try again in 9 minutes"."""
    found = _WAIT.search(message)
    return float(int(found.group(1)) * _SECONDS[found.group(2)]) if found else None


def refusal(body: Mapping[str, object]) -> OmnisocialError | None:
    """El error que trae el cuerpo de una escritura que respondió 200, si trae uno."""
    errors = as_dict(body.get("json")).get("errors")
    first = errors[0] if isinstance(errors, list) and errors else None
    if not isinstance(first, list) or not first:
        return None
    code = str(first[0])
    message = str(first[1]) if len(first) > 1 else code
    if code in ERRORS.codes:
        return ERRORS.error(REDDIT, message, code=code, retry_after=_wait(message))
    # Reddit dijo que no y por qué: la comunidad no existe, no acepta links, el título es largo…
    return ProviderError(REDDIT, message, code=code, kind=ErrorKind.INVALID_REQUEST)


def unwrap(response: HttpResponse) -> object:
    if response.status >= _CLIENT_ERROR:
        raise api_error(response)
    return response.data


class RedditClient:
    def __init__(self, config: RedditConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = UserAgentTransport(transport, config.user_agent)

    @property
    def config(self) -> RedditConfig:
        return self._config

    @property
    def transport(self) -> HttpTransport:
        """El transporte que ya lleva el User-Agent."""
        return self._transport

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"bearer {token}"}

    async def get(self, path: str, token: str, params: Params | None = None) -> object:
        """`raw_json=1`: sin él, Reddit devuelve los textos con `&amp;` y `&lt;`."""
        response = await self._transport.request(
            "GET",
            f"{self._config.api_base}/{path.lstrip('/')}",
            params={**(params or {}), "raw_json": 1},
            headers=self._headers(token),
        )
        return unwrap(response)

    async def post(self, path: str, token: str, form: Mapping[str, str]) -> HttpResponse:
        return await self._transport.request(
            "POST",
            f"{self._config.api_base}/{path.lstrip('/')}",
            form={**form, "api_type": "json", "raw_json": "1"},
            headers=self._headers(token),
        )

    async def act(self, path: str, token: str, form: Mapping[str, str]) -> dict[str, object]:
        """Una escritura: lanza si Reddit la rechazó, por el estado o en el cuerpo."""
        body = as_dict(unwrap(await self.post(path, token, form)))
        error = refusal(body)
        if error is not None:
            raise error
        return as_dict(as_dict(body.get("json")).get("data"))

    async def listing(
        self, path: str, token: str, params: Params | None = None
    ) -> AsyncIterator[list[dict[str, object]]]:
        """Recorre un listado con `after`. Cada elemento es el `data` de una cosa."""
        query: dict[str, str | int] = {**(params or {}), "limit": self._config.page_size}
        for _ in range(self._config.max_pages):
            data = as_dict(as_dict(await self.get(path, token, query)).get("data"))
            yield [as_dict(child.get("data")) for child in as_list(data.get("children"))]
            after = as_str(data.get("after"))
            if after is None:
                return
            query["after"] = after
