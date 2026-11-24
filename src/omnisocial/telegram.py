"""Telegram. `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.telegram.config import (
    TELEGRAM,
    TELEGRAM_BOT,
    TelegramConfig,
    TelegramOptions,
)
from omnisocial.adapters.providers.telegram.provider import telegram_provider, telegram_webhooks
from omnisocial.adapters.providers.telegram.spec import BOT_LIMITS, ERRORS, MESSAGE_LIMITS, SPEC
from omnisocial.adapters.providers.telegram.webhooks import (
    ALLOWED_UPDATES,
    BOT_PARAM,
    SECRET_HEADER,
    TelegramWebhooks,
    secret_for,
)

__all__ = [
    "ALLOWED_UPDATES",
    "BOT_LIMITS",
    "BOT_PARAM",
    "ERRORS",
    "MESSAGE_LIMITS",
    "SECRET_HEADER",
    "SPEC",
    "TELEGRAM",
    "TELEGRAM_BOT",
    "TelegramConfig",
    "TelegramOptions",
    "TelegramWebhooks",
    "secret_for",
    "telegram_provider",
    "telegram_webhooks",
]
