"""El transporte que usan los adaptadores de redes. Se reemplaza en tests sin red de verdad."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

Params = Mapping[str, str | int]


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    data: object = None
    """El cuerpo ya decodificado como JSON, o `None` si no era JSON."""
    text: str = field(default="", repr=False)


class HttpTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Params | None = None,
        json: Mapping[str, object] | None = None,
    ) -> HttpResponse: ...
