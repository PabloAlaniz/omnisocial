"""El ritmo que una red tolera, envolviendo cualquier transporte.

Cada red declara cuántos pedidos simultáneos acepta y cuánto tiene que pasar entre uno y otro (`Pace`).
Este transporte hace esperar a los pedidos en vez de dejar que la red los rechace.

Sin un almacén, vale dentro de un proceso. Con uno compartido (`RateLimitStore`), los turnos se reparten
entre todos los procesos, y cuando la red pide esperar, esperan todos: el pedido que se haría antes de
tiempo se responde acá con un 429, sin molestar a la red. El tope de pedidos simultáneos sigue siendo de
cada proceso.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params
from omnisocial.application.ports import RateLimitStore
from omnisocial.domain.spec import Pace

Sleep = Callable[[float], Awaitable[None]]
Now = Callable[[], float]

_TOO_MANY_REQUESTS = 429
_WAIT_HEADERS = ("retry-after", "x-ratelimit-reset-after", "x-ratelimit-reset")
_MAX_RELATIVE = 86_400.0
"""Un valor más grande que un día no son segundos a esperar: es una fecha."""
DEFAULT_MAX_WAIT = 30.0


def asked_to_wait(response: HttpResponse) -> float | None:
    """Los segundos que la red pidió esperar, si lo dijo en una cabecera."""
    for name in _WAIT_HEADERS:
        value = response.header(name)
        try:
            seconds = float(value) if value is not None else None
        except ValueError:
            continue
        if seconds is not None and 0 <= seconds <= _MAX_RELATIVE:
            return seconds
    return None


class _LocalTurns(RateLimitStore):
    """Los turnos dentro de este transporte, cuando no hay un almacén compartido."""

    def __init__(self, now: Now) -> None:
        self._now = now
        self._next = 0.0

    @override
    async def reserve(self, key: str, interval: float) -> float:
        now = self._now()
        turn = max(self._next, now)
        self._next = turn + interval
        return turn - now

    @override
    async def pause(self, key: str, seconds: float) -> None:
        self._next = max(self._next, self._now() + seconds)


@dataclass(frozen=True, slots=True)
class SharedTurns:
    """Los turnos compartidos entre procesos."""

    store: RateLimitStore
    key: str
    """Bajo qué nombre se guardan: la red, o la red y la app si hay más de una."""


class PacedTransport(HttpTransport):
    def __init__(
        self,
        inner: HttpTransport,
        pace: Pace,
        *,
        sleep: Sleep = asyncio.sleep,
        now: Now = time.monotonic,
        shared: SharedTurns | None = None,
        max_wait: float = DEFAULT_MAX_WAIT,
    ) -> None:
        """Si para el próximo turno falta más de `max_wait` segundos, el pedido no se hace: se responde
        un 429 con lo que falta."""
        self._inner = inner
        self._pace = pace
        self._sleep = sleep
        self._shared = shared is not None
        self._store = shared.store if shared else _LocalTurns(now)
        self._key = shared.key if shared else ""
        self._max_wait = max_wait
        self._slots = asyncio.Semaphore(pace.max_concurrent) if pace.max_concurrent else None

    async def _turn(self) -> HttpResponse | None:
        """Espera el turno. Si falta demasiado, devuelve la respuesta con que se contesta sin pedir."""
        if not self._pace.min_interval and not self._shared:
            return None
        wait = await self._store.reserve(self._key, self._pace.min_interval)
        if wait > self._max_wait:
            seconds = str(math.ceil(wait))
            return HttpResponse(
                _TOO_MANY_REQUESTS,
                None,
                f"La red pidió esperar: faltan {seconds} segundos.",
                {"Retry-After": seconds},
            )
        if wait > 0:
            await self._sleep(wait)
        return None

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
        async def send() -> HttpResponse:
            held = await self._turn()
            if held is not None:
                return held
            response = await self._inner.request(
                method,
                url,
                params=params,
                json=json,
                form=form,
                headers=headers,
                retry_safe=retry_safe,
                content=content,
            )
            if response.status == _TOO_MANY_REQUESTS and (wait := asked_to_wait(response)):
                # La red pidió esperar: que lo sepan todos los que comparten el almacén.
                await self._store.pause(self._key, wait)
            return response

        if self._slots is None:
            return await send()
        async with self._slots:
            return await send()


def paced(
    transport: HttpTransport, pace: Pace | None, *, store: RateLimitStore | None = None, key: str = ""
) -> HttpTransport:
    """El transporte con el ritmo de la red, o el mismo si la red no declara uno. Con `store`, los
    turnos se comparten entre procesos bajo `key`."""
    if pace is None:
        return transport
    return PacedTransport(transport, pace, shared=SharedTurns(store, key) if store is not None else None)
