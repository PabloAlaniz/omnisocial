from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.mastodon.client import MastodonClient
from omnisocial.adapters.providers.mastodon.config import (
    MASTODON,
    MASTODON_ACCOUNT,
    MASTODON_FLAVOR,
    PIXELFED,
    PIXELFED_ACCOUNT,
)
from omnisocial.adapters.providers.mastodon.spec import ACCOUNT_CAPABILITIES
from omnisocial.adapters.stores.memory import InMemoryServerAppStore
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport
from tests.fakes import FakeClock

SERVER = "mastodon.social"
BASE = f"https://{SERVER}/"
REDIRECT = "https://api.ejemplo.com/oauth/callback"

TOKEN = Token(TokenKind.USER, "acceso-1", server=SERVER)
ACCOUNT = Asset("a1", "c1", MASTODON, "dueño", MASTODON_ACCOUNT, "109", capabilities=ACCOUNT_CAPABILITIES)
PIXELFED_USER = Asset(
    "a2", "c2", PIXELFED, "dueño", PIXELFED_ACCOUNT, "55", capabilities=ACCOUNT_CAPABILITIES
)
ME = {
    "id": "109",
    "username": "ana",
    "acct": "ana",
    "display_name": "Ana Pérez",
    "avatar": "https://files.mastodon.social/a.png",
    "url": "https://mastodon.social/@ana",
    "note": "<p>Hago cosas</p>",
    "followers_count": 820,
    "following_count": 95,
    "statuses_count": 1340,
}
APP = {"id": "1", "name": "omnisocial", "client_id": "id-app", "client_secret": "secreto-app"}


def failure(status: int, message: str = "no", **headers: str) -> HttpResponse:
    return HttpResponse(status, {"error": message}, "", headers)


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def apps() -> InMemoryServerAppStore:
    return InMemoryServerAppStore()


@pytest.fixture
def client(transport: FakeTransport) -> MastodonClient:
    return MastodonClient(MASTODON_FLAVOR, transport, FakeClock())
