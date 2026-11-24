"""Reintentos con backoff exponencial y jitter, envolviendo cualquier transporte.

Qué se reintenta:

- Respuestas 429 y 5xx, y fallas de red (`TransportError`).
- Sólo pedidos que se pueden repetir sin efectos: GET, HEAD, OPTIONS, PUT y DELETE, o un POST marcado con
  `retry_safe`. Un POST que publica algo no se repite solo: si la red lo procesó y se perdió la respuesta,
  repetirlo duplica la publicación.

El jitter es completo (uniforme entre 0 y el tope del intento): sin él, muchas cuentas que fallan a la vez
reintentan a la vez y vuelven a chocar contra el mismo límite.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params, TransportError
from omnisocial.adapters.system import uniform_jitter

Sleep = Callable[[float], Awaitable[None]]
Jitter = Callable[[float], float]

_REPEATABLE = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_TOO_MANY_REQUESTS = 429
_SERVER_ERROR = 500


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    """Intentos en total, contando el primero."""
    base: float = 0.5
    cap: float = 8.0
    max_retry_after: float = 60.0
    """Un `Retry-After` más largo no se espera: conviene fallar y que el próximo ciclo lo intente."""

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("Hace falta al menos un intento.")

    def ceiling(self, retry: int) -> float:
        return min(self.cap, self.base * float(2**retry))


def _retryable_status(status: int) -> bool:
    return status == _TOO_MANY_REQUESTS or status >= _SERVER_ERROR


class RetryingTransport(HttpTransport):
    def __init__(
        self,
        inner: HttpTransport,
        *,
        policy: RetryPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
        jitter: Jitter = uniform_jitter,
    ) -> None:
        self._inner = inner
        self._policy = policy or RetryPolicy()
        self._sleep = sleep
        self._jitter = jitter

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
        repeatable = method.upper() in _REPEATABLE or retry_safe is not None
        last_attempt = self._policy.attempts - 1 if repeatable else 0
        retry = 0
        while True:
            try:
                response = await self._inner.request(
                    method, url, params=params, json=json, form=form, headers=headers, retry_safe=retry_safe
                )
            except TransportError:
                if retry >= last_attempt:
                    raise
                await self._sleep(self._jitter(self._policy.ceiling(retry)))
            else:
                delay = self._delay(response, retry=retry, last_attempt=last_attempt)
                if delay is None:
                    return response
                await self._sleep(delay)
            retry += 1

    def _delay(self, response: HttpResponse, *, retry: int, last_attempt: int) -> float | None:
        """Cuánto esperar antes del próximo intento, o `None` si hay que devolver esta respuesta."""
        if retry >= last_attempt or not _retryable_status(response.status):
            return None
        asked = response.retry_after()
        if asked is None:
            return self._jitter(self._policy.ceiling(retry))
        return asked if asked <= self._policy.max_retry_after else None
