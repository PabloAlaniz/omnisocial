"""LinkedIn. `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.linkedin.config import (
    CONNECT_SCOPES,
    LINKEDIN,
    LINKEDIN_MEMBER,
    LINKEDIN_ORGANIZATION,
    LOGIN_SCOPES,
    ORGANIZATION_SCOPES,
    PUBLISH_SCOPES,
    LinkedInConfig,
    LinkedInOptions,
)
from omnisocial.adapters.providers.linkedin.insights import DEFAULT_CATALOG, FOLLOWERS, SHARE_STATS
from omnisocial.adapters.providers.linkedin.provider import linkedin_provider
from omnisocial.adapters.providers.linkedin.spec import ERRORS, SPEC

__all__ = [
    "CONNECT_SCOPES",
    "DEFAULT_CATALOG",
    "ERRORS",
    "FOLLOWERS",
    "LINKEDIN",
    "LINKEDIN_MEMBER",
    "LINKEDIN_ORGANIZATION",
    "LOGIN_SCOPES",
    "ORGANIZATION_SCOPES",
    "PUBLISH_SCOPES",
    "SHARE_STATS",
    "SPEC",
    "LinkedInConfig",
    "LinkedInOptions",
    "linkedin_provider",
]
