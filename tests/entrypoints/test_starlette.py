from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import parse_qs, urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient

from omnisocial.application.results import AuthorizationStarted, LoggedIn
from omnisocial.application.use_cases.webhooks import RoutedEvent
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.provider import Capability
from omnisocial.entrypoints.starlette import oauth_routes, webhook_routes
from tests.application.conftest import World, build_world


def _app(world: World, *, with_login: bool = True) -> tuple[TestClient, list[RoutedEvent]]:
    received: list[RoutedEvent] = []

    async def on_logged_in(request: Request, result: LoggedIn) -> Response:
        return JSONResponse({"hola": result.identity.name})

    async def on_events(events: Sequence[RoutedEvent]) -> None:
        received.extend(events)

    app = Starlette(
        routes=[
            *oauth_routes(world.social, on_logged_in=on_logged_in if with_login else None),
            *webhook_routes(world.social, on_events=on_events),
        ]
    )
    return TestClient(app, follow_redirects=False), received


async def _start(world: World, purpose: Purpose, **kwargs: str) -> str:
    started = await world.social.start_authorization.execute("falsa", purpose=purpose, **kwargs)
    assert isinstance(started, AuthorizationStarted)
    return started.state


async def test_conectar_vuelve_a_la_app_con_el_id() -> None:
    world = build_world()
    client, _ = _app(world)
    state = await _start(
        world, Purpose.CONNECT, owner="c", return_url="https://app.ejemplo.com/listo?tab=redes"
    )
    response = client.get("/oauth/falsa/callback", params={"state": state, "code": "abc"})
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.netloc == "app.ejemplo.com"
    assert parse_qs(location.query) == {"tab": ["redes"], "status": ["connected"], "connection_id": ["id1"]}


async def test_conectar_sin_return_url_responde_json() -> None:
    world = build_world()
    client, _ = _app(world)
    state = await _start(world, Purpose.CONNECT, owner="c")
    response = client.get("/oauth/falsa/callback", params={"state": state, "code": "abc"})
    assert response.json() == {"status": "connected", "connection_id": "id1"}


async def test_login_delega_en_la_app() -> None:
    world = build_world()
    client, _ = _app(world)
    state = await _start(world, Purpose.LOGIN)
    assert client.get("/oauth/falsa/callback", params={"state": state, "code": "abc"}).json() == {
        "hola": "Persona"
    }
    client_sin_login, _ = _app(world, with_login=False)
    state = await _start(world, Purpose.LOGIN)
    assert (
        client_sin_login.get("/oauth/falsa/callback", params={"state": state, "code": "x"}).status_code == 500
    )


async def test_negativas() -> None:
    world = build_world()
    client, _ = _app(world)
    assert client.get("/oauth/falsa/callback", params={"state": "nada"}).json() == {"error": "unknown_state"}
    state = await _start(world, Purpose.LOGIN, return_url="https://app.ejemplo.com/")
    response = client.get("/oauth/falsa/callback", params={"state": state, "error": "access_denied"})
    assert response.headers["location"] == "https://app.ejemplo.com/?status=error&reason=provider_denied"
    assert client.get("/oauth/otra/callback").status_code == 404


def test_saludo_de_webhooks() -> None:
    client, _ = _app(build_world())
    assert client.get("/webhooks/falsa", params={"clave": "ok", "desafio": "42"}).text == "42"
    assert client.get("/webhooks/falsa", params={"clave": "mal"}).status_code == 403
    assert client.get("/webhooks/otra").status_code == 404


async def test_avisos_de_webhooks() -> None:
    world = build_world()
    client, received = _app(world)
    assert client.post("/webhooks/falsa", content=b"pag-1", headers={"X-Firma": "valida"}).text == "ok"
    assert [e.event.asset_external_id for e in received] == ["pag-1"]
    assert client.post("/webhooks/falsa", content=b"pag-1", headers={"X-Firma": "mala"}).status_code == 401
    assert client.post("/webhooks/otra", content=b"").status_code == 404
    assert len(received) == 1


def test_una_red_sin_webhooks_responde_404() -> None:
    client, _ = _app(build_world(only=frozenset({Capability.LOGIN})))
    assert client.get("/webhooks/falsa").status_code == 404
    assert client.post("/webhooks/falsa", content=b"").status_code == 404
