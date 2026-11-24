"""El kit de pruebas, probado con redes mínimas: una de solo login y otras que no cumplen."""

from __future__ import annotations

import pytest
from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.application.ports import IdentityReader
from omnisocial.application.registry import Provider
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.identity import Identity
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.spec import NetworkSpec, OAuthSpec
from omnisocial.domain.token import Token
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.fakes import FakeClock, FakeNetwork

RED = ProviderId("solo_login")
TOKEN_URL = "https://red.ejemplo/token"
SPEC = NetworkSpec(
    id=RED,
    name="Solo login",
    capabilities=frozenset({Capability.LOGIN}),
    oauth=OAuthSpec(authorize_url="https://red.ejemplo/authorize", token_url=TOKEN_URL),
    docs="docs/solo-login.md",
)


class Quien(IdentityReader):
    @override
    async def identity(self, token: Token) -> Identity:
        return Identity(RED, "u1")


class SoloLogin(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport()

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        app = OAuthApp("app", "secreto", scopes={Purpose.LOGIN: ("perfil",), Purpose.CONNECT: ("perfil",)})
        oauth = StandardOAuth(SPEC, app, transport=self.transport, clock=FakeClock(), identity=Quien())
        return Provider(id=RED, oauth=oauth, spec=SPEC)

    @override
    def script_connection(self) -> None:
        self.transport.on("POST", TOKEN_URL, {"access_token": "a1"})

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return HttpResponse(401, {"error": "x"}, "") if kind is ErrorKind.TOKEN_DEAD else None


class TestUnaRedDeSoloLoginCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return SoloLogin()


class SinOAuth(SoloLogin):
    @override
    def provider(self) -> Provider:
        return Provider(id=RED, spec=SPEC)


class NoSabeDeTokensMuertos(SoloLogin):
    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return None


class SinDescripcion(SoloLogin):
    @override
    def provider(self) -> Provider:
        return FakeNetwork().provider()


class Contrato(ProviderContract):
    def __init__(self, harness: NetworkHarness) -> None:
        self._harness = harness

    @override
    def harness(self) -> NetworkHarness:
        return self._harness


def test_sin_oauth_no_hay_url_que_revisar() -> None:
    Contrato(SinOAuth()).test_la_url_de_autorizacion_lleva_lo_que_manda_el_nucleo()


def test_el_contrato_detecta_a_la_red_que_no_cumple() -> None:
    with pytest.raises(AssertionError, match="capacidades declaradas"):
        Contrato(SinOAuth()).test_la_descripcion_dice_la_verdad()
    with pytest.raises(AssertionError, match="descripción"):
        Contrato(SinDescripcion()).test_la_descripcion_dice_la_verdad()
    with pytest.raises(AssertionError, match="no hereda"):
        Contrato(SinDescripcion()).test_cada_adaptador_hereda_de_su_puerto()
    with pytest.raises(AssertionError, match="token murió"):
        Contrato(NoSabeDeTokensMuertos()).test_los_errores_se_traducen_igual_en_toda_capacidad()
    with pytest.raises(NotImplementedError):
        ProviderContract().harness()


async def test_el_transporte_falso_avisa_lo_que_no_esperaba() -> None:
    transport = FakeTransport(base="https://red.ejemplo/")
    transport.on("GET", "uno", {"n": 1}, {"n": 2})
    assert [(await transport.request("GET", "https://red.ejemplo/uno")).data for _ in range(3)] == [
        {"n": 1},
        {"n": 2},
        {"n": 2},
    ]
    assert transport.calls[0].path == "uno"
    with pytest.raises(AssertionError, match="Sin respuesta para POST otra"):
        await transport.request("POST", "https://red.ejemplo/otra")
