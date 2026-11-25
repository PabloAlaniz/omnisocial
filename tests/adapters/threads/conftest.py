from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.threads.client import ThreadsClient
from omnisocial.adapters.providers.threads.config import THREADS, THREADS_ACCOUNT, ThreadsConfig
from omnisocial.adapters.providers.threads.spec import ACCOUNT_CAPABILITIES
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport

BASE = "https://graph.threads.com/v1.0/"
SHORT_TOKEN_URL = "https://graph.threads.com/oauth/access_token"
LONG_TOKEN_URL = "https://graph.threads.com/access_token"
REFRESH_URL = "https://graph.threads.com/refresh_access_token"

TOKEN = Token(TokenKind.USER, "THQ-largo")
ACCOUNT = Asset(
    "a1", "c1", THREADS, "dueño", THREADS_ACCOUNT, "17841400000", capabilities=ACCOUNT_CAPABILITIES
)
ME = {
    "id": "17841400000",
    "username": "mimarca",
    "name": "Mi Marca",
    "threads_profile_picture_url": "https://scontent/a.jpg",
    "threads_biography": "Hacemos cosas",
}


def config(**overrides: object) -> ThreadsConfig:
    values: dict[str, object] = {"client_id": "app", "client_secret": "secreto"}
    values.update(overrides)
    return ThreadsConfig(**values)  # type: ignore[arg-type]


def failure(code: int, message: str = "no", status: int = 400) -> HttpResponse:
    error = {"message": message, "type": "OAuthException", "code": code, "fbtrace_id": "x"}
    return HttpResponse(status, {"error": error}, "")


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def client(transport: FakeTransport) -> ThreadsClient:
    return ThreadsClient(config(), transport)
