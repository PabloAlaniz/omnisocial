"""Pinterest cumple el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.pinterest.config import PinterestOptions
from omnisocial.adapters.providers.pinterest.provider import pinterest_provider
from omnisocial.adapters.providers.pinterest.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.publishing import PublishOptions
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.pinterest.conftest import BASE, BOARDS, SECTIONS, TOKEN_URL, USER, config, failure

_ERRORS = {
    ErrorKind.TOKEN_DEAD: failure(401, 2, "Authentication failed."),
    ErrorKind.MISSING_PERMISSION: failure(403, 29, "Not authorized to access the board or pin."),
    ErrorKind.RATE_LIMITED: failure(429, 8, "Rate limit exceeded.", **{"x-ratelimit-reset": "30"}),
}


class PinterestHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return pinterest_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        self.transport.on(
            "POST",
            TOKEN_URL,
            {"access_token": "pina-acceso", "refresh_token": "pinr-renovar", "expires_in": 2592000},
        )
        self.transport.on("GET", "user_account", USER)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return _ERRORS.get(kind)

    @override
    def options(self, kind: str) -> PublishOptions | None:
        return PinterestOptions(board_id="b1")

    @override
    def script_lookups(self) -> None:
        self.transport.on("GET", "boards", BOARDS)
        self.transport.on("GET", "boards/padre/sections", SECTIONS)


class TestPinterestCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return PinterestHarness()
