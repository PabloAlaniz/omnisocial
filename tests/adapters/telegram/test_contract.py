"""Telegram cumple el contrato común de las redes."""

from __future__ import annotations

from collections.abc import Mapping

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.telegram.config import TelegramOptions
from omnisocial.adapters.providers.telegram.provider import telegram_provider
from omnisocial.adapters.providers.telegram.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.publishing import PublishOptions
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.telegram.conftest import BASE, BOT_TOKEN, ME, config, failure, ok

_ERRORS = {
    ErrorKind.TOKEN_DEAD: failure(401, "Unauthorized"),
    ErrorKind.RATE_LIMITED: failure(429, "Too Many Requests: retry after 12", retry_after=12),
}


class TelegramHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return telegram_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        self.transport.on("POST", "getMe", ok(ME))

    @override
    def credentials(self) -> Mapping[str, str]:
        return {"token": BOT_TOKEN}

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return _ERRORS.get(kind)

    @override
    def options(self, kind: str) -> PublishOptions | None:
        return TelegramOptions("@micanal")


class TestTelegramCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return TelegramHarness()
