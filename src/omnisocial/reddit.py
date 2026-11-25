"""Reddit. `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.reddit.config import (
    CONNECT_SCOPES,
    LOGIN_SCOPES,
    MODERATE_SCOPES,
    PUBLISH_SCOPES,
    REDDIT,
    REDDIT_ACCOUNT,
    RedditConfig,
    RedditOptions,
)
from omnisocial.adapters.providers.reddit.provider import reddit_provider
from omnisocial.adapters.providers.reddit.spec import COMMUNITIES, ERRORS, FLAIRS, SPEC

__all__ = [
    "COMMUNITIES",
    "CONNECT_SCOPES",
    "ERRORS",
    "FLAIRS",
    "LOGIN_SCOPES",
    "MODERATE_SCOPES",
    "PUBLISH_SCOPES",
    "REDDIT",
    "REDDIT_ACCOUNT",
    "SPEC",
    "RedditConfig",
    "RedditOptions",
    "reddit_provider",
]
