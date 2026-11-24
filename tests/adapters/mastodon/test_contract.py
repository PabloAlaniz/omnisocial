"""Mastodon y Pixelfed cumplen el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.mastodon.config import MastodonConfig, PixelfedConfig
from omnisocial.adapters.providers.mastodon.provider import mastodon_provider, pixelfed_provider
from omnisocial.adapters.providers.mastodon.spec import PIXELFED_SPEC, SPEC
from omnisocial.adapters.stores.memory import InMemoryServerAppStore
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.mastodon.conftest import APP, BASE, ME, SERVER, failure

_ERRORS = {
    ErrorKind.TOKEN_DEAD: failure(401, "The access token is invalid"),
    ErrorKind.MISSING_PERMISSION: failure(403, "This action is outside the authorized scopes"),
    ErrorKind.RATE_LIMITED: failure(429, "Too many requests"),
}


class MastodonHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)
        self.apps = InMemoryServerAppStore()

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return mastodon_provider(MastodonConfig(), self.transport, apps=self.apps)

    @override
    def server(self) -> str | None:
        return SERVER

    @override
    def script_connection(self) -> None:
        self.transport.on("POST", "api/v1/apps", APP)
        self.transport.on(
            "POST", "oauth/token", {"access_token": "acceso-1", "scope": "read:accounts", "created_at": 1}
        )
        self.transport.on("GET", "api/v1/accounts/verify_credentials", ME)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return _ERRORS.get(kind)


class PixelfedHarness(MastodonHarness):
    @property
    @override
    def spec(self) -> NetworkSpec:
        return PIXELFED_SPEC

    @override
    def provider(self) -> Provider:
        return pixelfed_provider(PixelfedConfig(), self.transport, apps=self.apps)


class TestMastodonCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return MastodonHarness()


class TestPixelfedCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return PixelfedHarness()
