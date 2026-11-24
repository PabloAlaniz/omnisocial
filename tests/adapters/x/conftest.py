from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.x.client import XClient
from omnisocial.adapters.providers.x.config import X_ACCOUNT, X, XConfig
from omnisocial.adapters.providers.x.spec import ACCOUNT_CAPABILITIES
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport
from tests.fakes import FakeClock

BASE = "https://api.x.com/2/"
TOKEN_URL = "oauth2/token"
"""La ruta del token, sin la base: queda bajo la misma API."""
PROBLEMS = "https://api.x.com/2/problems"

TOKEN = Token(TokenKind.USER, "acceso-x")
ACCOUNT = Asset(
    "a1",
    "c1",
    X,
    "dueño",
    X_ACCOUNT,
    "2244994945",
    capabilities=ACCOUNT_CAPABILITIES,
    metadata={"username": "mimarca"},
)
ME = {
    "data": {
        "id": "2244994945",
        "name": "Mi Marca",
        "username": "mimarca",
        "profile_image_url": "https://pbs.twimg.com/a.jpg",
        "description": "Hacemos cosas",
        "verified": True,
        "url": "https://ejemplo.com",
        "public_metrics": {
            "followers_count": 5200,
            "following_count": 120,
            "tweet_count": 980,
            "listed_count": 7,
        },
    }
}


def config(**overrides: object) -> XConfig:
    values: dict[str, object] = {"client_id": "app", "client_secret": "secreto", "bearer_token": "token-app"}
    values.update(overrides)
    return XConfig(**values)  # type: ignore[arg-type]


def problem(status: int, kind: str | None = None, detail: str = "no", **headers: str) -> HttpResponse:
    body = {
        "title": "Error",
        "detail": detail,
        "type": f"{PROBLEMS}/{kind}" if kind else "about:blank",
        "status": status,
    }
    return HttpResponse(status, body, "", headers)


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def client(transport: FakeTransport) -> XClient:
    return XClient(config(), transport, FakeClock())
