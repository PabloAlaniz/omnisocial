"""Bluesky. `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.bluesky.config import (
    BLUESKY,
    BLUESKY_ACCOUNT,
    DEFAULT_SERVER,
    BlueskyConfig,
    BlueskyOptions,
)
from omnisocial.adapters.providers.bluesky.insights import DEFAULT_CATALOG, STATS
from omnisocial.adapters.providers.bluesky.provider import bluesky_provider
from omnisocial.adapters.providers.bluesky.session import FIELDS
from omnisocial.adapters.providers.bluesky.spec import ERRORS, SPEC

__all__ = [
    "BLUESKY",
    "BLUESKY_ACCOUNT",
    "DEFAULT_CATALOG",
    "DEFAULT_SERVER",
    "ERRORS",
    "FIELDS",
    "SPEC",
    "STATS",
    "BlueskyConfig",
    "BlueskyOptions",
    "bluesky_provider",
]
