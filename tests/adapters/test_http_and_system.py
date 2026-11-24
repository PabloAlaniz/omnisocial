from __future__ import annotations

import httpx
import pytest

from omnisocial.adapters.http.httpx_transport import HttpxTransport
from omnisocial.adapters.http.transport import TransportError
from omnisocial.adapters.system import SystemClock, SystemSecrets, UuidGenerator, uniform_jitter


async def test_transporte_httpx() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/texto":
            return httpx.Response(200, text="no es json")
        return httpx.Response(201, json={"ok": True})

    transport = HttpxTransport(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    response = await transport.request("POST", "https://api/x", params={"a": 1}, json={"b": 2})
    assert (response.status, response.data) == (201, {"ok": True})
    assert seen[0].url.params["a"] == "1"
    assert seen[0].content == b'{"b":2}'
    text = await transport.request("GET", "https://api/texto")
    assert (text.data, text.text) == (None, "no es json")
    await transport.aclose()
    await HttpxTransport().aclose()


def test_reloj_ids_y_secretos_de_verdad() -> None:
    assert SystemClock().now().tzinfo is not None
    assert UuidGenerator().new_id() != UuidGenerator().new_id()
    secret = SystemSecrets().token(32)
    assert len(secret) >= 40
    assert "/" not in secret


async def test_transporte_httpx_formulario_cabeceras_y_errores_de_red() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "caido":
            raise httpx.ConnectError("sin ruta")
        return httpx.Response(200, json={}, headers={"Retry-After": "2"})

    transport = HttpxTransport(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    response = await transport.request(
        "POST", "https://api/token?x=1", form={"code": "c"}, headers={"Authorization": "Bearer t"}
    )
    assert response.header("retry-after") == "2"
    assert seen[0].content == b"code=c"
    assert seen[0].headers["authorization"] == "Bearer t"
    assert seen[0].url.params["x"] == "1"
    with pytest.raises(TransportError, match="caido") as raised:
        await transport.request("GET", "https://caido/x?access_token=secreto")
    assert "secreto" not in str(raised.value)


def test_jitter_de_verdad() -> None:
    assert 0 <= uniform_jitter(2.0) <= 2.0


async def test_transporte_httpx_cuerpo_binario() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(308, headers={"Range": "bytes=0-3"})

    transport = HttpxTransport(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    response = await transport.request(
        "PUT", "https://subidas/sesion", content=b"\x00\x01\x02\x03", headers={"Content-Range": "bytes 0-3/8"}
    )
    assert (response.status, response.header("range")) == (308, "bytes=0-3")
    assert seen[0].content == b"\x00\x01\x02\x03"
    assert seen[0].headers["content-range"] == "bytes 0-3/8"
