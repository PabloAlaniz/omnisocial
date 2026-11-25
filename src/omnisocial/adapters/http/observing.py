"""Qué pasa con cada pedido HTTP a una red, sin que se escape un secreto.

Los tokens viajan en cabeceras, en la query y, en algunas redes, en la ruta (el token de un bot de
Telegram, la clave de un webhook de Discord). Por eso de un pedido solo se informa el método, el servidor
y una ruta sin nada que identifique: cada tramo que parece un id o una clave se reemplaza por `:id`.
Eso además deja pocas rutas distintas, que es lo que una métrica necesita.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params

_OPAQUE = ":id"
_MAX_PLAIN = 40
_WORD = re.compile(r"@?[A-Za-z_.]+")
"""Un tramo que es solo un nombre: `messages`, `user_account`, `com.atproto.repo.createRecord`. Sin
dígitos ni guiones: las claves que viajan en una ruta los tienen."""
_KNOWN = re.compile(r"v\d+(?:\.\d+)?|oauth2")
"""Los únicos tramos con dígitos que se dejan: una versión de API y `oauth2`."""


def _segment(segment: str) -> str:
    if not segment or _KNOWN.fullmatch(segment):
        return segment
    if len(segment) <= _MAX_PLAIN and _WORD.fullmatch(segment):
        return segment
    return _OPAQUE


def route_of(url: str) -> tuple[str, str]:
    """El servidor y la ruta de una URL, sin query y sin ids ni secretos.

    Un tramo queda solo si es un nombre (letras, puntos, guiones bajos). Lo que lleva dígitos o guiones,
    o es largo, se reemplaza: puede ser un id, y puede ser un token.
    """
    parts = urlsplit(url)
    route = "/".join(_segment(segment) for segment in parts.path.split("/"))
    return parts.hostname or "", route or "/"


@dataclass(frozen=True, slots=True)
class HttpObservation:
    network: str
    method: str
    host: str
    route: str
    """La ruta sin ids ni claves: `/:id/messages`."""
    status: int | None
    """`None` si no hubo respuesta."""
    duration: float
    """Segundos."""


class HttpObserver(Protocol):
    def request(self, observation: HttpObservation) -> None:
        """Se llama después de cada pedido. No debe tardar ni lanzar: si lanza, se ignora."""
        ...


class ObservedTransport(HttpTransport):
    """Avisa de cada pedido. Va por fuera de los reintentos para ver uno por operación, o por dentro
    para ver cada intento."""

    def __init__(
        self,
        inner: HttpTransport,
        observer: HttpObserver,
        *,
        network: str,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._observer = observer
        self._network = network
        self._timer = timer

    def _tell(self, method: str, url: str, status: int | None, started: float) -> None:
        host, route = route_of(url)
        observation = HttpObservation(self._network, method, host, route, status, self._timer() - started)
        # Un observador roto no puede romper un pedido.
        with contextlib.suppress(Exception):
            self._observer.request(observation)

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
        started = self._timer()
        status: int | None = None
        try:
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
            status = response.status
            return response
        finally:
            self._tell(method, url, status, started)
