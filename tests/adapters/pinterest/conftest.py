from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.pinterest.client import PinterestClient
from omnisocial.adapters.providers.pinterest.config import PINTEREST, PINTEREST_ACCOUNT, PinterestConfig
from omnisocial.adapters.providers.pinterest.spec import ACCOUNT_CAPABILITIES
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport

BASE = "https://api.pinterest.com/v5/"
TOKEN_URL = "oauth/token"
UPLOAD_URL = "https://pinterest-media-upload.s3.amazonaws.com/"

TOKEN = Token(TokenKind.USER, "pina-acceso")
ACCOUNT = Asset("a1", "c1", PINTEREST, "dueño", PINTEREST_ACCOUNT, "9001", capabilities=ACCOUNT_CAPABILITIES)
USER = {
    "id": "9001",
    "username": "mitienda",
    "account_type": "BUSINESS",
    "business_name": "Mi Tienda",
    "profile_image": "https://i.pinimg.com/mitienda.jpg",
    "follower_count": 1500,
}
BOARDS = {
    "items": [
        {"id": "b1", "name": "Recetas", "description": "Para el finde", "privacy": "PUBLIC"},
        {"id": "b2", "name": "Ideas", "privacy": "SECRET"},
        {"name": "sin id"},
    ],
    "bookmark": None,
}
SECTIONS = {"items": [{"id": "s1", "name": "Postres"}], "bookmark": None}
REGISTERED = {
    "media_id": "m1",
    "media_type": "video",
    "upload_url": UPLOAD_URL,
    "upload_parameters": {"key": "uploads/m1", "policy": "abc", "x-amz-signature": "firma"},
}


def config(**overrides: object) -> PinterestConfig:
    values: dict[str, object] = {"client_id": "app", "client_secret": "secreto"}
    values.update(overrides)
    return PinterestConfig(**values)  # type: ignore[arg-type]


def failure(status: int, code: int = 1, message: str = "no", **headers: str) -> HttpResponse:
    return HttpResponse(status, {"code": code, "message": message}, "", headers)


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def client(transport: FakeTransport) -> PinterestClient:
    return PinterestClient(config(), transport)
