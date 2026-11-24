"""Threads. `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.threads.config import (
    CONNECT_SCOPES,
    LOGIN_SCOPES,
    MODERATE_SCOPES,
    PUBLISH_SCOPES,
    THREADS,
    THREADS_ACCOUNT,
    ThreadsConfig,
    ThreadsOptions,
)
from omnisocial.adapters.providers.threads.insights import DEFAULT_CATALOG, FOLLOWERS, WINDOWED
from omnisocial.adapters.providers.threads.provider import threads_provider
from omnisocial.adapters.providers.threads.spec import ERRORS, SPEC

__all__ = [
    "CONNECT_SCOPES",
    "DEFAULT_CATALOG",
    "ERRORS",
    "FOLLOWERS",
    "LOGIN_SCOPES",
    "MODERATE_SCOPES",
    "PUBLISH_SCOPES",
    "SPEC",
    "THREADS",
    "THREADS_ACCOUNT",
    "WINDOWED",
    "ThreadsConfig",
    "ThreadsOptions",
    "threads_provider",
]
