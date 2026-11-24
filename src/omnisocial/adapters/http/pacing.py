"""El ritmo que una red tolera, envolviendo cualquier transporte.

Cada red declara cuántos pedidos simultáneos acepta y cuánto tiene que pasar entre uno y otro (`Pace`).
Este transporte hace esperar a los pedidos en vez de dejar que la red los rechace.

Vale dentro de un proceso: dos procesos con la misma app suman sus ritmos. Si hay varios, conviene bajar
el ritmo de cada uno o aceptar que la red responda con un límite de uso, que el núcleo ya sabe traducir.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params
from omnisocial.domain.spec import Pace

Sleep = Callable[[float], Awaitable[None]]
Now = Callable[[], float]


class PacedTransport(HttpTransport):
    def __init__(
        self, inner: HttpTransport, pace: Pace, *, sleep: Sleep = asyncio.sleep, now: Now = time.monotonic
    ) -> None:
        self._inner = inner
        self._pace = pace
        self._sleep = sleep
        self._now = now
        self._slots = asyncio.Semaphore(pace.max_concurrent) if pace.max_concurrent else None
        self._turn = asyncio.Lock()
        self._next = 0.0

    async def _wait_turn(self) -> None:
        """Los pedidos salen de a uno y separados: el que llega espera a que le toque."""
        if not self._pace.min_interval:
            return
        async with self._turn:
            wait = self._next - self._now()
            if wait > 0:
                await self._sleep(wait)
            self._next = self._now() + self._pace.min_interval

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
            await self._wait_turn()
            return await self._inner.request(
                method,
                url,
                params=params,
                json=json,
                form=form,
                headers=headers,
                retry_safe=retry_safe,
                content=content,
            )

        if self._slots is None:
            return await send()
        async with self._slots:
            return await send()


def paced(transport: HttpTransport, pace: Pace | None) -> HttpTransport:
    """El transporte con el ritmo de la red, o el mismo si la red no declara uno."""
    return PacedTransport(transport, pace) if pace is not None else transport
