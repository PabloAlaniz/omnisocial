"""Rutas para Starlette y FastAPI: el callback de OAuth y los webhooks.

El inicio de la autorización no va acá a propósito: el dueño de la conexión sale de la sesión de la app,
y eso lo resuelve la app antes de llamar a `social.start_authorization`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import urlencode, urlsplit, urlunsplit

from omniwebhook.starlette import to_incoming_request
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from omnisocial.application.results import Connected, LoggedIn, Refused
from omnisocial.application.use_cases.webhooks import OnEvents
from omnisocial.domain.errors import CapabilityNotSupported, UnknownProvider
from omnisocial.entrypoints.hub import Omnisocial

OnLoggedIn = Callable[[Request, LoggedIn], Awaitable[Response]]


def _with_query(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = "&".join(q for q in (parts.query, urlencode(params)) if q)
    return urlunsplit(parts._replace(query=query))


def _not_found() -> Response:
    return JSONResponse({"error": "unknown_provider"}, status_code=404)


def _finish(result: Connected | Refused) -> Response:
    """Vuelve a la app con el resultado, o responde JSON si no hay a dónde volver."""
    if isinstance(result, Refused):
        params = {"status": "error", "reason": result.reason.value}
        payload: dict[str, str] = {"error": result.reason.value}
        status = 400
    else:
        params = {"status": "connected", "connection_id": result.connection.id}
        payload = params
        status = 200
    if result.return_url:
        return RedirectResponse(_with_query(result.return_url, **params), 303)
    return JSONResponse(payload, status_code=status)


def oauth_routes(
    social: Omnisocial,
    *,
    on_logged_in: OnLoggedIn | None = None,
    path: str = "/oauth/{provider}/callback",
) -> list[Route]:
    """`GET /oauth/{provider}/callback`.

    - Conexión: vuelve a `return_url` con `status=connected&connection_id=...`.
    - Login: llama a `on_logged_in`, que crea la sesión de la app y devuelve la respuesta.
    - Negativa: vuelve a `return_url` con `status=error&reason=...`, o responde 400 si no hay a dónde volver.
    """

    async def callback(request: Request) -> Response:
        if request.path_params["provider"] not in social.registry:
            return _not_found()
        query = request.query_params
        result = await social.complete_authorization.execute(
            state=query.get("state", ""), code=query.get("code"), error=query.get("error")
        )
        if isinstance(result, LoggedIn):
            if on_logged_in is None:
                return JSONResponse({"error": "login_not_configured"}, status_code=500)
            return await on_logged_in(request, result)
        return _finish(result)

    return [Route(path, callback, methods=["GET"])]


def webhook_routes(
    social: Omnisocial, *, on_events: OnEvents, path: str = "/webhooks/{provider}"
) -> list[Route]:
    """`GET` para el saludo de suscripción y `POST` para los avisos.

    Los avisos los recibe omniwebhook: se verifican, se reservan y recién ahí se traducen. Una firma inválida
    responde 401; un aviso repetido, 200 sin volver a llamar a `on_events`; si `on_events` falla, 500 y la
    red reintenta.
    """

    async def handshake(request: Request) -> Response:
        try:
            parser = social.registry.get(request.path_params["provider"]).require_webhooks()
        except (UnknownProvider, CapabilityNotSupported):
            return _not_found()
        challenge = parser.handshake(dict(request.query_params))
        if challenge is None:
            return PlainTextResponse("forbidden", status_code=403)
        return PlainTextResponse(challenge)

    async def receive(request: Request) -> Response:
        try:
            result = await social.handle_webhook.execute(
                request.path_params["provider"],
                request=await to_incoming_request(request),
                on_events=on_events,
            )
        except (UnknownProvider, CapabilityNotSupported):
            return _not_found()
        # Como en omniwebhook, el cuerpo no dice qué falló.
        return Response(status_code=result.status)

    return [Route(path, handshake, methods=["GET"]), Route(path, receive, methods=["POST"])]
