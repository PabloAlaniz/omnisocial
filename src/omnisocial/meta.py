"""Meta (Facebook e Instagram). `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.meta.catalog import DEFAULT_CATALOG, INSTAGRAM_TOTAL_VALUE_METRICS
from omnisocial.adapters.providers.meta.config import (
    CONNECT_SCOPES,
    FACEBOOK_PAGE,
    INSTAGRAM_ACCOUNT,
    LOGIN_SCOPES,
    META,
    MetaConfig,
)
from omnisocial.adapters.providers.meta.graph import GraphClient
from omnisocial.adapters.providers.meta.oauth import MetaOAuth, TokenInfo
from omnisocial.adapters.providers.meta.provider import meta_provider
from omnisocial.adapters.providers.meta.webhooks import verify_subscription

__all__ = [
    "CONNECT_SCOPES",
    "DEFAULT_CATALOG",
    "FACEBOOK_PAGE",
    "INSTAGRAM_ACCOUNT",
    "INSTAGRAM_TOTAL_VALUE_METRICS",
    "LOGIN_SCOPES",
    "META",
    "GraphClient",
    "MetaConfig",
    "MetaOAuth",
    "TokenInfo",
    "meta_provider",
    "verify_subscription",
]
