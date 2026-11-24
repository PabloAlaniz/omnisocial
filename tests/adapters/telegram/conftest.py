from __future__ import annotations

import json

import pytest
from omniwebhook import IncomingRequest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.telegram.client import TelegramClient
from omnisocial.adapters.providers.telegram.config import TELEGRAM, TELEGRAM_BOT, TelegramConfig
from omnisocial.adapters.providers.telegram.spec import BOT_CAPABILITIES
from omnisocial.adapters.providers.telegram.webhooks import secret_for
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport

BOT_TOKEN = "7001234567:" + "AAHk-" * 7
BASE = f"https://api.telegram.org/bot{BOT_TOKEN}/"
WEBHOOK_SECRET = "un-secreto-largo-y-al-azar"
BOT_ID = "7001234567"

TOKEN = Token(TokenKind.USER, BOT_TOKEN)
BOT = Asset(
    "a1", "c1", TELEGRAM, "dueño", TELEGRAM_BOT, BOT_ID, name="@mitienda_bot", capabilities=BOT_CAPABILITIES
)
ME = {"id": 7001234567, "is_bot": True, "first_name": "Mi Tienda", "username": "mitienda_bot"}


def ok(result: object) -> dict[str, object]:
    return {"ok": True, "result": result}


def failure(code: int, description: str = "no", **parameters: int) -> HttpResponse:
    body: dict[str, object] = {"ok": False, "error_code": code, "description": description}
    if parameters:
        body["parameters"] = parameters
    return HttpResponse(code, body, "")


def message(message_id: int, chat: dict[str, object] | None = None, **extra: object) -> dict[str, object]:
    where = chat or {"id": -1001234567890, "type": "channel", "title": "Mi Canal", "username": "micanal"}
    return {"message_id": message_id, "date": 1795000000, "chat": where, **extra}


def update(payload: dict[str, object], *, bot: str = BOT_ID, secret: str | None = None) -> IncomingRequest:
    given = secret if secret is not None else secret_for(WEBHOOK_SECRET, bot)
    return IncomingRequest(
        headers=[("X-Telegram-Bot-Api-Secret-Token", given)],
        query=[("bot", bot)],
        body=json.dumps(payload).encode(),
    )


def config(**overrides: object) -> TelegramConfig:
    values: dict[str, object] = {"webhook_secret": WEBHOOK_SECRET}
    values.update(overrides)
    return TelegramConfig(**values)  # type: ignore[arg-type]


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def client(transport: FakeTransport) -> TelegramClient:
    return TelegramClient(config(), transport)
