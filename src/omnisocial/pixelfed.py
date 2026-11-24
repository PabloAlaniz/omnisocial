"""Pixelfed. Habla el protocolo de Mastodon: comparte su adaptador. `pip install omnisocial[httpx]`."""

from omnisocial.adapters.providers.mastodon.config import (
    PIXELFED,
    PIXELFED_ACCOUNT,
    MastodonOptions,
    PixelfedConfig,
)
from omnisocial.adapters.providers.mastodon.config import PIXELFED_CONNECT_SCOPES as CONNECT_SCOPES
from omnisocial.adapters.providers.mastodon.config import PIXELFED_LOGIN_SCOPES as LOGIN_SCOPES
from omnisocial.adapters.providers.mastodon.config import PIXELFED_PUBLISH_SCOPES as PUBLISH_SCOPES
from omnisocial.adapters.providers.mastodon.provider import pixelfed_provider
from omnisocial.adapters.providers.mastodon.reading import STATS
from omnisocial.adapters.providers.mastodon.spec import ERRORS
from omnisocial.adapters.providers.mastodon.spec import PIXELFED_SPEC as SPEC

__all__ = [
    "CONNECT_SCOPES",
    "ERRORS",
    "LOGIN_SCOPES",
    "PIXELFED",
    "PIXELFED_ACCOUNT",
    "PUBLISH_SCOPES",
    "SPEC",
    "STATS",
    "MastodonOptions",
    "PixelfedConfig",
    "pixelfed_provider",
]
