from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from omnisocial.adapters.http.retrying import RetryingTransport, RetryPolicy
from omnisocial.adapters.http.transport import HttpResponse, Params, TransportError


@dataclass
class Script:
    """Devuelve las respuestas en orden; una `TransportError` en la lista se lanza."""

    steps: list[HttpResponse | TransportError]
    calls: list[str] = field(default_factory=list)

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
        self.calls.append(method)
        step = self.steps.pop(0)
        if isinstance(step, TransportError):
            raise step
        return step


@dataclass
class Sleeps:
    waited: list[float] = field(default_factory=list)

    async def __call__(self, seconds: float) -> None:
        self.waited.append(seconds)


def retrying(script: Script, sleeps: Sleeps, **policy: float) -> RetryingTransport:
    return RetryingTransport(
        script,
        policy=RetryPolicy(**policy),  # type: ignore[arg-type]
        sleep=sleeps,
        jitter=lambda ceiling: ceiling,
    )


OK = HttpResponse(200, {"ok": True})


async def test_reintenta_un_5xx_y_devuelve_el_exito() -> None:
    script, sleeps = Script([HttpResponse(503), HttpResponse(502), OK]), Sleeps()
    response = await retrying(script, sleeps).request("GET", "https://api/x")
    assert response is OK
    assert sleeps.waited == [0.5, 1.0]


async def test_respeta_retry_after() -> None:
    script, sleeps = Script([HttpResponse(429, headers={"retry-after": "3"}), OK]), Sleeps()
    assert await retrying(script, sleeps).request("GET", "https://api/x") is OK
    assert sleeps.waited == [3.0]


async def test_un_retry_after_excesivo_no_se_espera() -> None:
    limited = HttpResponse(429, headers={"Retry-After": "1800"})
    script, sleeps = Script([limited, OK]), Sleeps()
    assert await retrying(script, sleeps).request("GET", "https://api/x") is limited
    assert sleeps.waited == []


async def test_un_retry_after_ilegible_cae_al_backoff() -> None:
    script, sleeps = Script([HttpResponse(429, headers={"Retry-After": "mañana"}), OK]), Sleeps()
    assert await retrying(script, sleeps).request("GET", "https://api/x") is OK
    assert sleeps.waited == [0.5]


async def test_se_rinde_despues_de_los_intentos_y_devuelve_la_ultima_respuesta() -> None:
    script, sleeps = Script([HttpResponse(500), HttpResponse(500), HttpResponse(500), OK]), Sleeps()
    response = await retrying(script, sleeps).request("GET", "https://api/x")
    assert response.status == 500
    assert len(script.calls) == 3


async def test_los_errores_de_red_se_reintentan_y_el_ultimo_se_lanza() -> None:
    script = Script([TransportError("caído"), OK])
    assert await retrying(script, Sleeps()).request("DELETE", "https://api/x") is OK
    failing = Script([TransportError("1"), TransportError("2"), TransportError("3")])
    with pytest.raises(TransportError, match="3"):
        await retrying(failing, Sleeps()).request("GET", "https://api/x")


async def test_un_post_sin_marca_no_se_reintenta() -> None:
    script, sleeps = Script([HttpResponse(503), OK]), Sleeps()
    response = await retrying(script, sleeps).request("POST", "https://api/x", json={"a": 1})
    assert response.status == 503
    assert script.calls == ["POST"]
    broken = Script([TransportError("cortado"), OK])
    with pytest.raises(TransportError):
        await retrying(broken, Sleeps()).request("POST", "https://api/x")


async def test_un_post_marcado_como_seguro_se_reintenta() -> None:
    script = Script([HttpResponse(503), OK])
    transport = retrying(script, Sleeps())
    assert await transport.request("POST", "https://api/x", retry_safe="es una lectura") is OK


async def test_un_4xx_no_se_reintenta() -> None:
    script = Script([HttpResponse(404), OK])
    assert (await retrying(script, Sleeps()).request("GET", "https://api/x")).status == 404


async def test_el_backoff_tiene_tope() -> None:
    script, sleeps = Script([*[HttpResponse(503)] * 5, OK]), Sleeps()
    await retrying(script, sleeps, attempts=6, base=1.0, cap=3.0).request("GET", "https://api/x")
    assert sleeps.waited == [1.0, 2.0, 3.0, 3.0, 3.0]


def test_la_politica_valida_sus_valores() -> None:
    with pytest.raises(ValueError, match="intento"):
        RetryPolicy(attempts=0)


async def test_los_valores_por_defecto_usan_el_azar_y_el_reloj_de_verdad() -> None:
    script = Script([HttpResponse(503), OK])
    transport = RetryingTransport(script, policy=RetryPolicy(base=0.001, cap=0.001))
    assert await transport.request("GET", "https://api/x") is OK
