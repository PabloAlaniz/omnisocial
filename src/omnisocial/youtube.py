"""YouTube (Data API v3). `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.youtube.config import (
    CONNECT_SCOPES,
    LOGIN_SCOPES,
    MODERATE_SCOPES,
    PUBLISH_SCOPES,
    YOUTUBE,
    YOUTUBE_CHANNEL,
    YouTubeConfig,
    YouTubeOptions,
)
from omnisocial.adapters.providers.youtube.insights import DEFAULT_CATALOG, STATS
from omnisocial.adapters.providers.youtube.provider import youtube_provider
from omnisocial.adapters.providers.youtube.spec import ERRORS, SPEC

__all__ = [
    "CONNECT_SCOPES",
    "DEFAULT_CATALOG",
    "ERRORS",
    "LOGIN_SCOPES",
    "MODERATE_SCOPES",
    "PUBLISH_SCOPES",
    "SPEC",
    "STATS",
    "YOUTUBE",
    "YOUTUBE_CHANNEL",
    "YouTubeConfig",
    "YouTubeOptions",
    "youtube_provider",
]
