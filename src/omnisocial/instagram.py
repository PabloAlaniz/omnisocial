"""Instagram con login propio, sin página de Facebook. `pip install omnisocial[httpx]` para el transporte.

Para Instagram a través de una página de Facebook, con mensajes y webhooks, ver `omnisocial.meta`.
"""

from omnisocial.adapters.providers.meta.catalog import DEFAULT_CATALOG
from omnisocial.adapters.providers.meta.config import INSTAGRAM, INSTAGRAM_ACCOUNT
from omnisocial.adapters.providers.meta.instagram_login import (
    CONNECT_SCOPES,
    LOGIN_SCOPES,
    PUBLISH_SCOPES,
    InstagramConfig,
    instagram_provider,
)
from omnisocial.adapters.providers.meta.spec import ERRORS
from omnisocial.adapters.providers.meta.spec import INSTAGRAM_SPEC as SPEC

__all__ = [
    "CONNECT_SCOPES",
    "DEFAULT_CATALOG",
    "ERRORS",
    "INSTAGRAM",
    "INSTAGRAM_ACCOUNT",
    "LOGIN_SCOPES",
    "PUBLISH_SCOPES",
    "SPEC",
    "InstagramConfig",
    "instagram_provider",
]
