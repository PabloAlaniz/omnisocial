"""Mastodon. `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.mastodon.config import (
    CONNECT_SCOPES,
    LOGIN_SCOPES,
    MASTODON,
    MASTODON_ACCOUNT,
    MODERATE_SCOPES,
    PUBLISH_SCOPES,
    MastodonConfig,
    MastodonOptions,
)
from omnisocial.adapters.providers.mastodon.provider import mastodon_provider
from omnisocial.adapters.providers.mastodon.reading import STATS
from omnisocial.adapters.providers.mastodon.spec import ERRORS, SPEC

__all__ = [
    "CONNECT_SCOPES",
    "ERRORS",
    "LOGIN_SCOPES",
    "MASTODON",
    "MASTODON_ACCOUNT",
    "MODERATE_SCOPES",
    "PUBLISH_SCOPES",
    "SPEC",
    "STATS",
    "MastodonConfig",
    "MastodonOptions",
    "mastodon_provider",
]
