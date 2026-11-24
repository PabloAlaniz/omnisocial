"""Un transporte que responde lo que se le dijo y anota lo que le pidieron."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params


@dataclass(frozen=True, slots=True)
class RecordedCall:
    method: str
    path: str
    """La URL sin la base del transporte."""
    params: Mapping[str, str | int]
    json: Mapping[str, object] | None
    form: Mapping[str, str] | None
    headers: Mapping[str, str] | None
    retry_safe: str | None


@dataclass
class FakeTransport(HttpTransport):
    """Responde por método y ruta. Cada ruta puede tener varias respuestas, que se entregan en orden; la
    última se repite.

    `base` es el prefijo de las URLs de la red: las rutas se escriben sin él. Una URL que no empieza con la
    base se busca entera.
    """

    base: str = ""
    routes: dict[tuple[str, str], list[HttpResponse | Exception]] = field(default_factory=dict)
    calls: list[RecordedCall] = field(default_factory=list)
    failing: HttpResponse | None = None
    """Si está, es la respuesta a todo. Sirve para simular que la red empezó a fallar."""

    def on(self, method: str, path: str, *responses: object, status: int = 200) -> None:
        """Agrega respuestas para esa ruta. Un valor que no es `HttpResponse` es el cuerpo JSON; una
        excepción (un `TransportError`, por ejemplo) se lanza en vez de responder."""
        self.routes.setdefault((method, path), []).extend(
            r if isinstance(r, HttpResponse | Exception) else HttpResponse(status, r, "") for r in responses
        )

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
        path = url.removeprefix(self.base) if self.base else url
        self.calls.append(RecordedCall(method, path, dict(params or {}), json, form, headers, retry_safe))
        if self.failing is not None:
            return self.failing
        queue = self.routes.get((method, path))
        if not queue:
            raise AssertionError(f"Sin respuesta para {method} {path}")
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer
