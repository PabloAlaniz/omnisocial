"""Discord, con el bot de la app. `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.discord.config import (
    CONNECT_SCOPES,
    DISCORD,
    DISCORD_GUILD,
    LOGIN_SCOPES,
    PUBLISH_PERMISSIONS,
    DiscordConfig,
    DiscordOptions,
)
from omnisocial.adapters.providers.discord.provider import discord_provider
from omnisocial.adapters.providers.discord.spec import CHANNELS, ERRORS, SPEC

__all__ = [
    "CHANNELS",
    "CONNECT_SCOPES",
    "DISCORD",
    "DISCORD_GUILD",
    "ERRORS",
    "LOGIN_SCOPES",
    "PUBLISH_PERMISSIONS",
    "SPEC",
    "DiscordConfig",
    "DiscordOptions",
    "discord_provider",
]
