"""Bluesky cumple el contrato común de las redes."""

from __future__ import annotations

from collections.abc import Mapping

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.bluesky.config import BlueskyConfig
from omnisocial.adapters.providers.bluesky.provider import bluesky_provider
from omnisocial.adapters.providers.bluesky.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.bluesky.conftest import (
    BASE,
    CREATE_SESSION,
    CREDENTIALS,
    GET_SESSION,
    SESSION,
    failure,
    jwt,
)

_ERRORS = {
    ErrorKind.TOKEN_DEAD: failure("InvalidToken"),
    ErrorKind.RATE_LIMITED: failure("RateLimitExceeded", 429),
}


class BlueskyHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return bluesky_provider(BlueskyConfig(), self.transport)

    @override
    def credentials(self) -> Mapping[str, str]:
        return CREDENTIALS

    @override
    def script_connection(self) -> None:
        # El contrato corre con el reloj de verdad: el token de prueba vence lejos.
        self.transport.on(
            "POST", CREATE_SESSION, {**SESSION, "accessJwt": jwt(10**9), "refreshJwt": "renovar-1"}
        )
        self.transport.on("GET", GET_SESSION, SESSION)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return _ERRORS.get(kind)


class TestBlueskyCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return BlueskyHarness()
