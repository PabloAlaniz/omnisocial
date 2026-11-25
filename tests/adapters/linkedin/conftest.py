from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.linkedin.client import LinkedInClient
from omnisocial.adapters.providers.linkedin.config import (
    LINKEDIN,
    LINKEDIN_MEMBER,
    LINKEDIN_ORGANIZATION,
    LinkedInConfig,
)
from omnisocial.adapters.providers.linkedin.spec import MEMBER_CAPABILITIES, ORGANIZATION_CAPABILITIES
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport

BASE = "https://api.linkedin.com/rest/"
USERINFO = "https://api.linkedin.com/v2/userinfo"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

TOKEN = Token(TokenKind.USER, "AQV-acceso")
MEMBER = Asset("a1", "c1", LINKEDIN, "dueño", LINKEDIN_MEMBER, "abc123", capabilities=MEMBER_CAPABILITIES)
ORGANIZATION = Asset(
    "a2", "c1", LINKEDIN, "dueño", LINKEDIN_ORGANIZATION, "5515715", capabilities=ORGANIZATION_CAPABILITIES
)
PERSON = {"sub": "abc123", "name": "Ana Pérez", "email": "ana@ejemplo.com", "picture": "https://media/ana"}
ACLS = {
    "elements": [
        {"role": "ADMINISTRATOR", "organization": "urn:li:organization:5515715", "state": "APPROVED"}
    ],
    "paging": {"count": 50, "start": 0, "links": []},
}
ORGANIZATIONS = {"results": {"5515715": {"localizedName": "Mi Empresa", "vanityName": "mi-empresa"}}}


def config(**overrides: object) -> LinkedInConfig:
    values: dict[str, object] = {"client_id": "app", "client_secret": "secreto", "api_version": "202611"}
    values.update(overrides)
    return LinkedInConfig(**values)  # type: ignore[arg-type]


def failure(status: int, code: str | None = None, message: str = "no") -> HttpResponse:
    body: dict[str, object] = {"status": status, "message": message}
    if code is not None:
        body["code"] = code
    return HttpResponse(status, body, "")


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def client(transport: FakeTransport) -> LinkedInClient:
    return LinkedInClient(config(), transport)
