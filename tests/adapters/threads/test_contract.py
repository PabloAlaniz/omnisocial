"""Threads cumple el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.threads.provider import threads_provider
from omnisocial.adapters.providers.threads.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.threads.conftest import BASE, LONG_TOKEN_URL, ME, SHORT_TOKEN_URL, config, failure

_CODES = {ErrorKind.TOKEN_DEAD: 190, ErrorKind.MISSING_PERMISSION: 10, ErrorKind.RATE_LIMITED: 4}


class ThreadsHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return threads_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        self.transport.on("POST", SHORT_TOKEN_URL, {"access_token": "THQ-corto", "user_id": 17841400000})
        self.transport.on("GET", LONG_TOKEN_URL, {"access_token": "THQ-largo", "expires_in": 5184000})
        self.transport.on("GET", "me", ME)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        code = _CODES.get(kind)
        return failure(code) if code else None


class TestThreadsCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return ThreadsHarness()
