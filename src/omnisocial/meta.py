"""Meta (Facebook e Instagram). `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.meta.catalog import DEFAULT_CATALOG, INSTAGRAM_TOTAL_VALUE_METRICS
from omnisocial.adapters.providers.meta.config import (
    CONNECT_SCOPES,
    FACEBOOK_PAGE,
    INSTAGRAM_ACCOUNT,
    LOGIN_SCOPES,
    META,
    PUBLISH_SCOPES,
    MetaConfig,
)
from omnisocial.adapters.providers.meta.deletion import (
    DeletionReceipt,
    DeletionRequest,
    InvalidSignedRequest,
    MetaDeletionRequests,
    parse_signed_request,
)
from omnisocial.adapters.providers.meta.graph import GraphClient
from omnisocial.adapters.providers.meta.oauth import MetaIdentity, MetaOAuth, TokenInfo
from omnisocial.adapters.providers.meta.provider import meta_provider
from omnisocial.adapters.providers.meta.spec import ERRORS, SPEC
from omnisocial.adapters.providers.meta.webhooks import verify_subscription

__all__ = [
    "CONNECT_SCOPES",
    "DEFAULT_CATALOG",
    "ERRORS",
    "FACEBOOK_PAGE",
    "INSTAGRAM_ACCOUNT",
    "INSTAGRAM_TOTAL_VALUE_METRICS",
    "LOGIN_SCOPES",
    "META",
    "PUBLISH_SCOPES",
    "SPEC",
    "DeletionReceipt",
    "DeletionRequest",
    "GraphClient",
    "InvalidSignedRequest",
    "MetaConfig",
    "MetaDeletionRequests",
    "MetaIdentity",
    "MetaOAuth",
    "TokenInfo",
    "meta_provider",
    "parse_signed_request",
    "verify_subscription",
]
