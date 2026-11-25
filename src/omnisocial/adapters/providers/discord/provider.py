"""Arma los proveedores de Discord: por bot y por webhook."""

from __future__ import annotations

from omnisocial.adapters.http.pacing import paced
from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.discord.bot import (
    DiscordAssetDirectory,
    DiscordBot,
    DiscordIdentity,
    DiscordLookups,
    DiscordPublisher,
    discord_oauth,
)
from omnisocial.adapters.providers.discord.client import DiscordClient
from omnisocial.adapters.providers.discord.config import (
    DISCORD,
    DISCORD_WEBHOOK,
    DiscordConfig,
    DiscordWebhookConfig,
)
from omnisocial.adapters.providers.discord.spec import ERRORS, SPEC, WEBHOOK_ERRORS, WEBHOOK_SPEC
from omnisocial.adapters.providers.discord.webhook import (
    DiscordWebhookAssets,
    DiscordWebhookIdentity,
    DiscordWebhookPublisher,
    DiscordWebhookSession,
)
from omnisocial.adapters.system import SystemClock, UuidGenerator
from omnisocial.application.ports import Clock, IdGenerator, RateLimitStore
from omnisocial.application.registry import Provider
from omnisocial.domain.spec import Pace


def discord_provider(
    config: DiscordConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    pace: Pace | None = SPEC.pace,
    rate_limits: RateLimitStore | None = None,
) -> Provider:
    """La persona autoriza y suma el bot de la app a un servidor que administra; después publica el
    bot. `pace` es el ritmo de los pedidos dentro de este proceso."""
    client = DiscordClient(
        paced(transport, pace, store=rate_limits, key=DISCORD),
        api_base=config.api_base,
        user_agent=config.user_agent,
        provider=DISCORD,
        errors=ERRORS,
    )
    bot = DiscordBot(client, config)
    return Provider(
        id=DISCORD,
        oauth=discord_oauth(client, config, clock or SystemClock()),
        identity=DiscordIdentity(client),
        assets=DiscordAssetDirectory(bot),
        publisher=DiscordPublisher(bot, ids or UuidGenerator()),
        lookups=DiscordLookups(bot),
        spec=SPEC,
    )


def discord_webhook_provider(
    config: DiscordWebhookConfig,
    transport: HttpTransport,
    *,
    pace: Pace | None = WEBHOOK_SPEC.pace,
    rate_limits: RateLimitStore | None = None,
) -> Provider:
    """Cada canal se conecta pegando la URL de su webhook (`social.connect_with_credentials`)."""
    client = DiscordClient(
        paced(transport, pace, store=rate_limits, key=DISCORD_WEBHOOK),
        api_base=config.api_base,
        user_agent=config.user_agent,
        provider=DISCORD_WEBHOOK,
        errors=WEBHOOK_ERRORS,
    )
    return Provider(
        id=DISCORD_WEBHOOK,
        credentials=DiscordWebhookSession(client),
        identity=DiscordWebhookIdentity(client),
        assets=DiscordWebhookAssets(client),
        publisher=DiscordWebhookPublisher(client),
        spec=WEBHOOK_SPEC,
    )
