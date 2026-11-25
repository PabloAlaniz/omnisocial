from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.google_business.client import GoogleBusinessClient
from omnisocial.adapters.providers.google_business.config import (
    ACCOUNTS_BASE,
    GOOGLE_BUSINESS,
    GOOGLE_BUSINESS_LOCATION,
    INFORMATION_BASE,
    PERFORMANCE_BASE,
    POSTS_BASE,
    TOKEN_URL,
    USERINFO_URL,
    GoogleBusinessConfig,
)
from omnisocial.adapters.providers.google_business.spec import LOCATION_CAPABILITIES
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport

__all__ = ["TOKEN_URL", "USERINFO_URL"]

LOCATION_NAME = "accounts/111/locations/456"
ACCOUNTS = f"{ACCOUNTS_BASE}/accounts"
LOCATIONS = f"{INFORMATION_BASE}/accounts/111/locations"
POSTS = f"{POSTS_BASE}/{LOCATION_NAME}/localPosts"
REVIEWS = f"{POSTS_BASE}/{LOCATION_NAME}/reviews"
METRICS = f"{PERFORMANCE_BASE}/locations/456:fetchMultiDailyMetricsTimeSeries"

TOKEN = Token(TokenKind.USER, "ya29-acceso")
LOCATION = Asset(
    "a1",
    "c1",
    GOOGLE_BUSINESS,
    "dueño",
    GOOGLE_BUSINESS_LOCATION,
    LOCATION_NAME,
    name="Café Central",
    capabilities=LOCATION_CAPABILITIES,
)
PERSON = {"sub": "1099", "name": "Ana Pérez", "email": "ana@ejemplo.com", "picture": "https://lh3/ana"}
ACCOUNT_LIST = {"accounts": [{"name": "accounts/111", "accountName": "Ana", "type": "PERSONAL"}, {}]}
LOCATION_LIST = {
    "locations": [
        {
            "name": "locations/456",
            "title": "Café Central",
            "websiteUri": "https://cafecentral.ejemplo.com",
            "metadata": {"mapsUri": "https://maps.google.com/?cid=1", "placeId": "ChIJ1"},
        },
        {"title": "sin nombre"},
    ]
}


def config(**overrides: object) -> GoogleBusinessConfig:
    values: dict[str, object] = {"client_id": "app", "client_secret": "secreto"}
    values.update(overrides)
    return GoogleBusinessConfig(**values)  # type: ignore[arg-type]


def failure(status: int, state: str, reason: str | None = None, message: str = "no") -> HttpResponse:
    error: dict[str, object] = {"code": status, "message": message, "status": state}
    if reason is not None:
        error["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}]
    return HttpResponse(status, {"error": error}, "")


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def client(transport: FakeTransport) -> GoogleBusinessClient:
    return GoogleBusinessClient(config(), transport)
