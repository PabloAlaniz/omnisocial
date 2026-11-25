"""TikTok (Login Kit y Display API). `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.tiktok.config import (
    CONNECT_SCOPES,
    LOGIN_SCOPES,
    PUBLISH_SCOPES,
    TIKTOK,
    TIKTOK_ACCOUNT,
    TikTokConfig,
    TikTokOptions,
)
from omnisocial.adapters.providers.tiktok.insights import DEFAULT_CATALOG, STATS
from omnisocial.adapters.providers.tiktok.provider import tiktok_provider
from omnisocial.adapters.providers.tiktok.spec import ERRORS, SPEC

__all__ = [
    "CONNECT_SCOPES",
    "DEFAULT_CATALOG",
    "ERRORS",
    "LOGIN_SCOPES",
    "PUBLISH_SCOPES",
    "SPEC",
    "STATS",
    "TIKTOK",
    "TIKTOK_ACCOUNT",
    "TikTokConfig",
    "TikTokOptions",
    "tiktok_provider",
]
