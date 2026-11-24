from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.discord.config import (
    DISCORD,
    DISCORD_GUILD,
    DISCORD_WEBHOOK,
    DISCORD_WEBHOOK_CHANNEL,
    DiscordConfig,
    DiscordWebhookConfig,
)
from omnisocial.adapters.providers.discord.spec import GUILD_CAPABILITIES, WEBHOOK_CAPABILITIES
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport

BASE = "https://discord.com/api/v10/"
AGENT = "DiscordBot (https://miproducto.ejemplo.com, 1.0)"
BOT = "Bot token-del-bot"
WEBHOOK_URL = "https://discord.com/api/webhooks/111222333/clave-del_webhook"
WEBHOOK = "webhooks/111222333/clave-del_webhook"

TOKEN = Token(TokenKind.USER, "acceso-de-ana")
HOOK = Token(TokenKind.USER, "111222333/clave-del_webhook")
GUILD = Asset(
    "a1", "c1", DISCORD, "dueño", DISCORD_GUILD, "900", name="Mi Comunidad", capabilities=GUILD_CAPABILITIES
)
CHANNEL = Asset(
    "a2",
    "c2",
    DISCORD_WEBHOOK,
    "dueño",
    DISCORD_WEBHOOK_CHANNEL,
    "111222333",
    name="Novedades",
    parent_external_id="900",
    capabilities=WEBHOOK_CAPABILITIES,
    metadata={"channel_id": "500", "guild_id": "900"},
)
USER = {"id": "42", "username": "ana", "global_name": "Ana", "avatar": "a1b2", "email": "ana@ejemplo.com"}
MY_GUILDS = [
    {"id": "900", "name": "Mi Comunidad", "owner": True, "permissions": "0"},
    {"id": "901", "name": "Otra donde administro", "owner": False, "permissions": str(1 << 5)},
    {"id": "902", "name": "Donde solo participo", "owner": False, "permissions": "1024"},
    {"id": "903", "name": "Permisos raros", "permissions": "muchos"},
]
BOT_GUILDS = [{"id": "900"}, {"id": "777"}]
CHANNELS = [
    {"id": "501", "type": 5, "name": "anuncios", "position": 2},
    {"id": "500", "type": 0, "name": "general", "position": 1},
    {"id": "502", "type": 15, "name": "ideas", "position": 3, "nsfw": True},
    {"id": "503", "type": 2, "name": "Voz", "position": 0},
    {"id": "504", "type": 4, "name": "Categoría"},
]
HOOK_INFO = {"id": "111222333", "name": "Novedades", "channel_id": "500", "guild_id": "900", "type": 1}


def config(**overrides: object) -> DiscordConfig:
    values: dict[str, object] = {
        "client_id": "app",
        "client_secret": "secreto",
        "bot_token": "token-del-bot",
        "app_url": "https://miproducto.ejemplo.com",
    }
    values.update(overrides)
    return DiscordConfig(**values)  # type: ignore[arg-type]


def webhook_config() -> DiscordWebhookConfig:
    return DiscordWebhookConfig(app_url="https://miproducto.ejemplo.com")


def failure(status: int, code: int = 0, message: str = "no", **extra: object) -> HttpResponse:
    return HttpResponse(status, {"code": code, "message": message, **extra}, "")


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)
