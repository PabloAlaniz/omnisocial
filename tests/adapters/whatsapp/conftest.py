from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from omniwebhook import IncomingRequest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.whatsapp.client import WhatsAppClient
from omnisocial.adapters.providers.whatsapp.config import WHATSAPP, WHATSAPP_NUMBER, WhatsAppConfig
from omnisocial.adapters.providers.whatsapp.spec import NUMBER_CAPABILITIES
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport

BASE = "https://graph.facebook.com/v26.0/"
SECRET = "secreto-de-la-app"
TOKEN = Token(TokenKind.USER, "EAAG-acceso")
NUMBER = Asset(
    "a1",
    "c1",
    WHATSAPP,
    "dueño",
    WHATSAPP_NUMBER,
    "106540352242922",
    name="Mi Tienda",
    parent_external_id="102290129340398",
    capabilities=NUMBER_CAPABILITIES,
)
ME = {"id": "122100", "name": "Usuario de sistema"}
INSPECTED = {
    "data": {
        "is_valid": True,
        "granular_scopes": [
            {"scope": "whatsapp_business_management", "target_ids": ["102290129340398"]},
            {"scope": "whatsapp_business_messaging", "target_ids": ["102290129340398"]},
            {"scope": "public_profile"},
        ],
    }
}
NUMBERS = {
    "data": [
        {
            "id": "106540352242922",
            "display_phone_number": "+54 9 11 5555-0100",
            "verified_name": "Mi Tienda",
            "quality_rating": "GREEN",
        },
        {"display_phone_number": "sin id"},
    ]
}
SENT = {
    "messaging_product": "whatsapp",
    "contacts": [{"input": "5491155550199", "wa_id": "5491155550199"}],
    "messages": [{"id": "wamid.HBgL1"}],
}


def config(**overrides: object) -> WhatsAppConfig:
    values: dict[str, object] = {"app_id": "app", "app_secret": SECRET, "webhook_verify_token": "saludo"}
    values.update(overrides)
    return WhatsAppConfig(**values)  # type: ignore[arg-type]


def failure(status: int, code: int, message: str = "no", details: str | None = None) -> HttpResponse:
    error: dict[str, object] = {"message": message, "type": "OAuthException", "code": code}
    if details is not None:
        error["error_data"] = {"messaging_product": "whatsapp", "details": details}
    return HttpResponse(status, {"error": error}, "")


def signed(payload: object, secret: str = SECRET) -> IncomingRequest:
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return IncomingRequest(headers=[("X-Hub-Signature-256", f"sha256={signature}")], query=[], body=body)


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def client(transport: FakeTransport) -> WhatsAppClient:
    return WhatsAppClient(config(), transport)
