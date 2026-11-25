"""X cumple el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.x.provider import x_provider
from omnisocial.adapters.providers.x.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.x.conftest import BASE, ME, TOKEN_URL, config, problem

_ERRORS = {
    ErrorKind.TOKEN_DEAD: problem(401, detail="Unauthorized"),
    ErrorKind.MISSING_PERMISSION: problem(403, "client-forbidden"),
    ErrorKind.RATE_LIMITED: problem(429, "rate-limit-exceeded"),
    ErrorKind.QUOTA_EXHAUSTED: problem(403, "usage-capped"),
}


class XHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return x_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        granted = {"access_token": "acceso-x", "refresh_token": "renovar-1", "expires_in": 7200}
        self.transport.on("POST", TOKEN_URL, granted)
        self.transport.on("GET", "users/me", ME)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return _ERRORS[kind]


class TestXCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return XHarness()
