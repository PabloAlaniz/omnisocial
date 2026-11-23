from __future__ import annotations

import httpx

from omnisocial.adapters.http.httpx_transport import HttpxTransport
from omnisocial.adapters.system import SystemClock, SystemSecrets, UuidGenerator


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
