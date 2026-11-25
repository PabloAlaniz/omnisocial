from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.youtube.client import YouTubeClient
from omnisocial.adapters.providers.youtube.config import YOUTUBE, YOUTUBE_CHANNEL, YouTubeConfig
from omnisocial.adapters.providers.youtube.spec import CHANNEL_CAPABILITIES
from omnisocial.domain.asset import Asset
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport

BASE = "https://www.googleapis.com/youtube/v3/"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SESSION = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=sesion-1"

TOKEN = Token(TokenKind.USER, "ya29.acceso")
CHANNEL = Asset(
    "a1",
    "c1",
    YOUTUBE,
    "dueño",
    YOUTUBE_CHANNEL,
    "UC1234567890123456789012",
    capabilities=CHANNEL_CAPABILITIES,
    metadata={"uploads": "UU1234567890123456789012"},
)
OWN_CHANNEL = {
    "items": [
        {
            "id": "UC1234567890123456789012",
            "snippet": {
                "title": "Mi canal",
                "customUrl": "@micanal",
                "description": "Recetas",
                "thumbnails": {"default": {"url": "https://yt3.ggpht.com/a"}},
            },
            "contentDetails": {"relatedPlaylists": {"uploads": "UU1234567890123456789012"}},
            "statistics": {"subscriberCount": "1230", "viewCount": "98765", "videoCount": "42"},
        }
    ]
}


def config(**overrides: object) -> YouTubeConfig:
    values: dict[str, object] = {"client_id": "app", "client_secret": "secreto", "api_key": "clave"}
    values.update(overrides)
    return YouTubeConfig(**values)  # type: ignore[arg-type]


def failure(reason: str, status: int = 403, message: str = "no") -> HttpResponse:
    error = {"code": status, "message": message, "errors": [{"reason": reason, "domain": "youtube"}]}
    return HttpResponse(status, {"error": error}, "")


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def client(transport: FakeTransport) -> YouTubeClient:
    return YouTubeClient(config(), transport)
