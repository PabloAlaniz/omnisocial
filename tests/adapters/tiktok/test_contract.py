"""TikTok cumple el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.tiktok.provider import tiktok_provider
from omnisocial.adapters.providers.tiktok.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.tiktok.conftest import BASE, config, failure, ok
from tests.adapters.tiktok.test_client_oauth import TOKENS

_CODES = {
    ErrorKind.TOKEN_DEAD: "access_token_invalid",
    ErrorKind.MISSING_PERMISSION: "scope_not_authorized",
    ErrorKind.RATE_LIMITED: "rate_limit_exceeded",
}


class TikTokHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return tiktok_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        self.transport.on("POST", "oauth/token/", TOKENS)
        self.transport.on("GET", "user/info/", ok({"user": {"open_id": "oid-1", "display_name": "Marca"}}))

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        code = _CODES.get(kind)
        return HttpResponse(401, failure(code, "no"), "") if code else None


class TestTikTokCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return TikTokHarness()
