"""Reddit cumple el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.reddit.config import RedditOptions
from omnisocial.adapters.providers.reddit.provider import reddit_provider
from omnisocial.adapters.providers.reddit.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.publishing import PublishOptions
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.reddit.conftest import BASE, COMMUNITIES, FLAIRS, ME, TOKEN_URL, config, failure

_ERRORS = {
    ErrorKind.TOKEN_DEAD: failure(401, "invalid_token"),
    ErrorKind.MISSING_PERMISSION: failure(403, "insufficient_scope"),
    ErrorKind.RATE_LIMITED: failure(429, **{"X-Ratelimit-Reset": "45"}),
}


class RedditHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return reddit_provider(config(), self.transport, pace=None)

    @override
    def script_connection(self) -> None:
        self.transport.on(
            "POST", TOKEN_URL, {"access_token": "acceso-1", "refresh_token": "renovar-1", "expires_in": 3600}
        )
        self.transport.on("GET", "api/v1/me", ME)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return _ERRORS.get(kind)

    @override
    def options(self, kind: str) -> PublishOptions | None:
        return RedditOptions(subreddit="argentina", title="Hola")

    @override
    def script_lookups(self) -> None:
        self.transport.on("GET", "subreddits/mine/subscriber", COMMUNITIES)
        self.transport.on("GET", "r/padre/api/link_flair_v2", FLAIRS)


class TestRedditCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return RedditHarness()
