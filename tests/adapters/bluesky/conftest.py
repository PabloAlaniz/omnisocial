from __future__ import annotations

import base64
import json

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.bluesky.client import BlueskyClient
from omnisocial.adapters.providers.bluesky.config import BLUESKY, BLUESKY_ACCOUNT, BlueskyConfig
from omnisocial.adapters.providers.bluesky.spec import ACCOUNT_CAPABILITIES
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport
from tests.fakes import NOW, FakeClock

BASE = "https://bsky.social/xrpc/"
PUBLIC = "https://public.api.bsky.app/xrpc/"
DID = "did:plc:abc123"
CREATE_SESSION = "com.atproto.server.createSession"
GET_SESSION = "com.atproto.server.getSession"
CREATE_RECORD = "com.atproto.repo.createRecord"
UPLOAD = "com.atproto.repo.uploadBlob"


def jwt(expires_in: int = 7200) -> str:
    """Un token con la forma de los de Bluesky: lo único que se lee es cuándo vence."""
    payload = json.dumps({"exp": int(NOW.timestamp()) + expires_in, "sub": DID}).encode()
    return "cabecera." + base64.urlsafe_b64encode(payload).rstrip(b"=").decode() + ".firma"


TOKEN = Token(TokenKind.USER, "acceso-1", refresh_token="renovar-1", server="bsky.social")
ACCOUNT = Asset("a1", "c1", BLUESKY, "dueño", BLUESKY_ACCOUNT, DID, capabilities=ACCOUNT_CAPABILITIES)
SESSION = {"did": DID, "handle": "ana.bsky.social", "email": "ana@ejemplo.com"}
CREDENTIALS = {"identifier": "@ana.bsky.social", "password": "abcd-efgh-ijkl-mnop"}


def failure(name: str, status: int = 400, message: str = "no", **headers: str) -> HttpResponse:
    return HttpResponse(status, {"error": name, "message": message}, "", headers)


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def client(transport: FakeTransport) -> BlueskyClient:
    return BlueskyClient(BlueskyConfig(), transport, FakeClock())
