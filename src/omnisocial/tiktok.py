"""TikTok (Login Kit y Display API). `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.tiktok.config import (
    CONNECT_SCOPES,
    LOGIN_SCOPES,
    TIKTOK,
    TIKTOK_ACCOUNT,
    TikTokConfig,
)
from omnisocial.adapters.providers.tiktok.insights import DEFAULT_CATALOG, STATS
from omnisocial.adapters.providers.tiktok.provider import tiktok_provider

__all__ = [
    "CONNECT_SCOPES",
    "DEFAULT_CATALOG",
    "LOGIN_SCOPES",
    "STATS",
    "TIKTOK",
    "TIKTOK_ACCOUNT",
    "TikTokConfig",
    "tiktok_provider",
]
