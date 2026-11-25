"""X (API v2). `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.x.config import (
    CONNECT_SCOPES,
    LOGIN_SCOPES,
    MODERATE_SCOPES,
    PUBLISH_SCOPES,
    X_ACCOUNT,
    X,
    XConfig,
    XOptions,
)
from omnisocial.adapters.providers.x.insights import DEFAULT_CATALOG, STATS
from omnisocial.adapters.providers.x.provider import x_provider
from omnisocial.adapters.providers.x.spec import ERRORS, SPEC

__all__ = [
    "CONNECT_SCOPES",
    "DEFAULT_CATALOG",
    "ERRORS",
    "LOGIN_SCOPES",
    "MODERATE_SCOPES",
    "PUBLISH_SCOPES",
    "SPEC",
    "STATS",
    "X_ACCOUNT",
    "X",
    "XConfig",
    "XOptions",
    "x_provider",
]
