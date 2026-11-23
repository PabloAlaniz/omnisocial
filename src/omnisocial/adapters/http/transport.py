"""El transporte que usan los adaptadores de redes. Se reemplaza en tests sin red de verdad."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

Params = Mapping[str, str | int]


class TransportError(Exception):
    """No hubo respuesta: la conexión falló, se cortó o venció el tiempo de espera."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    data: object = None
    """El cuerpo ya decodificado como JSON, o `None` si no era JSON."""
    text: str = field(default="", repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    def header(self, name: str) -> str | None:
        """Las cabeceras HTTP no distinguen mayúsculas."""
        wanted = name.lower()
        return next((value for key, value in self.headers.items() if key.lower() == wanted), None)


class HttpTransport(Protocol):
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
        """Hace el pedido.

        `retry_safe` marca un POST que se puede repetir sin efectos (una lectura que la red obliga a pedir
        por POST, el canje de un código). Va el motivo, para que quien lea el código no tenga que adivinarlo.
        Lanza `TransportError` si no hubo respuesta.
        """
        ...
