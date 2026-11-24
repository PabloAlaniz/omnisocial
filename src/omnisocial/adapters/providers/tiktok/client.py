"""Cliente mínimo de la API de TikTok: autenticación, el sobre de errores y los dos estilos de respuesta.

- Los endpoints de OAuth (`/oauth/token/`, `/oauth/revoke/`) son el estándar: los atiende `StandardOAuth`.
- Los de datos (`/user/info/`, `/video/list/`) responden siempre `{"data": ..., "error": {"code": "ok"}}`;
  un `code` distinto de `ok` es un error. `fields` va en la query, también en los POST.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport
from omnisocial.adapters.providers.tiktok.config import TIKTOK, TikTokConfig
from omnisocial.adapters.providers.tiktok.spec import ERRORS
from omnisocial.domain.errors import ErrorKind


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


class TikTokClient:
    def __init__(self, config: TikTokConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = transport

    @property
    def config(self) -> TikTokConfig:
        return self._config

    @property
    def transport(self) -> HttpTransport:
        return self._transport

    def _url(self, path: str) -> str:
        return f"{self._config.api_base}/{path.strip('/')}/"

    async def get(self, path: str, token: str, *, fields: Sequence[str]) -> dict[str, object]:
        response = await self._transport.request(
            "GET", self._url(path), params={"fields": ",".join(fields)}, headers=self._bearer(token)
        )
        return self._unwrap(response)

    async def query(
        self, path: str, token: str, *, fields: Sequence[str], body: Mapping[str, object]
    ) -> dict[str, object]:
        """Las lecturas que TikTok pide por POST (listar videos, por ejemplo)."""
        response = await self._transport.request(
            "POST",
            self._url(path),
            params={"fields": ",".join(fields)},
            json=body,
            headers=self._bearer(token),
            retry_safe="es una lectura: TikTok la pide por POST",
        )
        return self._unwrap(response)

    @staticmethod
    def _bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _unwrap(response: HttpResponse) -> dict[str, object]:
        body = as_dict(response.data)
        error = as_dict(body.get("error"))
        code = as_str(error.get("code"))
        if code == "ok":
            return as_dict(body.get("data"))
        message = as_str(error.get("message")) or response.text[:300] or f"HTTP {response.status}"
        if ERRORS.classify(status=response.status, code=code) is ErrorKind.TOKEN_DEAD:
            message = f"TikTok rechazó el token: {message}"
        raise ERRORS.error(
            TIKTOK, message, status=response.status, code=code, retry_after=response.retry_after()
        )
