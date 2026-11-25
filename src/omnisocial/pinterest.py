"""Pinterest. `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.pinterest.config import (
    CONNECT_SCOPES,
    LOGIN_SCOPES,
    PINTEREST,
    PINTEREST_ACCOUNT,
    PUBLISH_SCOPES,
    SANDBOX_BASE,
    PinterestConfig,
    PinterestOptions,
)
from omnisocial.adapters.providers.pinterest.provider import pinterest_provider
from omnisocial.adapters.providers.pinterest.reading import ACCOUNT_METRICS, DEFAULT_CATALOG, FOLLOWERS
from omnisocial.adapters.providers.pinterest.spec import BOARD_SECTIONS, BOARDS, ERRORS, SPEC

__all__ = [
    "ACCOUNT_METRICS",
    "BOARDS",
    "BOARD_SECTIONS",
    "CONNECT_SCOPES",
    "DEFAULT_CATALOG",
    "ERRORS",
    "FOLLOWERS",
    "LOGIN_SCOPES",
    "PINTEREST",
    "PINTEREST_ACCOUNT",
    "PUBLISH_SCOPES",
    "SANDBOX_BASE",
    "SPEC",
    "PinterestConfig",
    "PinterestOptions",
    "pinterest_provider",
]
