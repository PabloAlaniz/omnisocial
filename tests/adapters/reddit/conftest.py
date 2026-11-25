from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.reddit.client import RedditClient
from omnisocial.adapters.providers.reddit.config import REDDIT, REDDIT_ACCOUNT, RedditConfig
from omnisocial.adapters.providers.reddit.spec import ACCOUNT_CAPABILITIES
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport

BASE = "https://oauth.reddit.com/"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REVOKE_URL = "https://www.reddit.com/api/v1/revoke_token"
AGENT = "web:com.ejemplo.app:1.0 (by /u/ejemplo)"

TOKEN = Token(TokenKind.USER, "acceso-1")
ACCOUNT = Asset(
    "a1",
    "c1",
    REDDIT,
    "dueño",
    REDDIT_ACCOUNT,
    "abc12",
    name="u/ana",
    capabilities=ACCOUNT_CAPABILITIES,
    metadata={"username": "ana"},
)
ME = {"id": "abc12", "name": "ana", "icon_img": "https://styles.redditmedia.com/ana.png", "link_karma": 10}
COMMUNITIES = {
    "data": {
        "after": None,
        "children": [
            {
                "kind": "t5",
                "data": {
                    "display_name": "argentina",
                    "display_name_prefixed": "r/argentina",
                    "title": "Argentina",
                    "subscribers": 900000,
                    "submission_type": "any",
                    "over18": False,
                },
            },
            {"kind": "t5", "data": {"display_name": "cocina"}},
            {"kind": "t5", "data": {}},
        ],
    }
}
FLAIRS = [{"id": "f1", "text": "Pregunta", "text_editable": False}, {"id": "f2", "text_editable": True}, {}]


def config(**overrides: object) -> RedditConfig:
    values: dict[str, object] = {"client_id": "app", "client_secret": "secreto", "user_agent": AGENT}
    values.update(overrides)
    return RedditConfig(**values)  # type: ignore[arg-type]


def failure(status: int, auth: str | None = None, **headers: str) -> HttpResponse:
    if auth is not None:
        headers["WWW-Authenticate"] = f'Bearer realm="reddit", error="{auth}"'
    return HttpResponse(status, {"message": "no", "error": status}, "", headers)


def refused(code: str, message: str = "no", field: str = "sr") -> dict[str, object]:
    return {"json": {"errors": [[code, message, field]]}}


def listing(*items: dict[str, object], after: str | None = None, kind: str = "t3") -> dict[str, object]:
    return {
        "kind": "Listing",
        "data": {"after": after, "children": [{"kind": kind, "data": i} for i in items]},
    }


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def client(transport: FakeTransport) -> RedditClient:
    return RedditClient(config(), transport)
