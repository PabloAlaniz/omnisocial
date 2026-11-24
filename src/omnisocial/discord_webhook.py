"""Discord por webhook de canal: sin app y sin bot. Comparte el adaptador de Discord."""

from omnisocial.adapters.providers.discord.config import (
    DISCORD_WEBHOOK,
    DISCORD_WEBHOOK_CHANNEL,
    DiscordWebhookConfig,
    DiscordWebhookOptions,
)
from omnisocial.adapters.providers.discord.provider import discord_webhook_provider
from omnisocial.adapters.providers.discord.spec import WEBHOOK_ERRORS as ERRORS
from omnisocial.adapters.providers.discord.spec import WEBHOOK_SPEC as SPEC

__all__ = [
    "DISCORD_WEBHOOK",
    "DISCORD_WEBHOOK_CHANNEL",
    "ERRORS",
    "SPEC",
    "DiscordWebhookConfig",
    "DiscordWebhookOptions",
    "discord_webhook_provider",
]
