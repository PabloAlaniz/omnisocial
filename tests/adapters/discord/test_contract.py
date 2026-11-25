"""Discord, por bot y por webhook, cumple el contrato común de las redes."""

from __future__ import annotations

from collections.abc import Mapping

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.discord.config import DiscordOptions
from omnisocial.adapters.providers.discord.provider import discord_provider, discord_webhook_provider
from omnisocial.adapters.providers.discord.spec import SPEC, WEBHOOK_SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishOptions
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.discord.conftest import (
    BASE,
    BOT_GUILDS,
    CHANNELS,
    HOOK_INFO,
    MY_GUILDS,
    USER,
    WEBHOOK,
    WEBHOOK_URL,
    config,
    failure,
    webhook_config,
)

_ERRORS = {
    ErrorKind.TOKEN_DEAD: failure(401, 0, "401: Unauthorized"),
    ErrorKind.MISSING_PERMISSION: failure(403, 50013, "Missing Permissions"),
    ErrorKind.RATE_LIMITED: failure(429, 0, "You are being rate limited.", retry_after=1.5),
}


class DiscordHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return discord_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        token = {"access_token": "acceso-de-ana", "refresh_token": "renovar-1", "expires_in": 604800}
        self.transport.on("POST", "oauth2/token", token)
        self.transport.on("GET", "users/@me", USER)
        # Primero pregunta la persona qué administra; después el bot, dónde está.
        self.transport.on("GET", "users/@me/guilds", MY_GUILDS, BOT_GUILDS)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return _ERRORS.get(kind)

    @override
    def options(self, kind: str) -> PublishOptions | None:
        return DiscordOptions("500")

    @override
    def app_token_capabilities(self) -> frozenset[Capability]:
        # Publica el bot de la app: si su token deja de valer, la conexión de la persona sigue sana.
        return frozenset({Capability.PUBLISHING})

    @override
    def script_lookups(self) -> None:
        self.transport.on("GET", "guilds/900/channels", CHANNELS)


class DiscordWebhookHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return WEBHOOK_SPEC

    @override
    def provider(self) -> Provider:
        return discord_webhook_provider(webhook_config(), self.transport)

    @override
    def script_connection(self) -> None:
        self.transport.on("GET", WEBHOOK, HOOK_INFO)

    @override
    def credentials(self) -> Mapping[str, str]:
        return {"webhook_url": WEBHOOK_URL}

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        if kind is ErrorKind.TOKEN_DEAD:
            return failure(404, 10015, "Unknown Webhook")
        return _ERRORS.get(kind)


class TestDiscordCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return DiscordHarness()


class TestDiscordPorWebhookCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return DiscordWebhookHarness()
