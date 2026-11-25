"""YouTube cumple el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.youtube.provider import youtube_provider
from omnisocial.adapters.providers.youtube.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.youtube.conftest import BASE, OWN_CHANNEL, TOKEN_URL, config, failure

_REASONS = {
    ErrorKind.TOKEN_DEAD: ("authError", 401),
    ErrorKind.MISSING_PERMISSION: ("insufficientPermissions", 403),
    ErrorKind.RATE_LIMITED: ("rateLimitExceeded", 403),
    ErrorKind.QUOTA_EXHAUSTED: ("quotaExceeded", 403),
}


class YouTubeHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return youtube_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        granted = {"access_token": "ya29.acceso", "refresh_token": "1//renovar", "expires_in": 3599}
        self.transport.on("POST", TOKEN_URL, granted)
        self.transport.on("GET", "channels", OWN_CHANNEL)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        reason, status = _REASONS[kind]
        return failure(reason, status)


class TestYouTubeCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return YouTubeHarness()
