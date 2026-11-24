"""Configuración de la app de LinkedIn."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

LINKEDIN = ProviderId("linkedin")

LINKEDIN_MEMBER = "linkedin_member"
"""El perfil de la persona que autorizó."""
LINKEDIN_ORGANIZATION = "linkedin_organization"
"""Una página de empresa que la persona administra."""

LOGIN_SCOPES: tuple[str, ...] = ("openid", "profile", "email")
"""Sign In with LinkedIn (OpenID Connect). Se activa sin revisión."""

CONNECT_SCOPES: tuple[str, ...] = LOGIN_SCOPES

PUBLISH_SCOPES: tuple[str, ...] = ("w_member_social",)
"""Publicar en el perfil de la persona. Es el producto "Share on LinkedIn", que se activa sin revisión."""

ORGANIZATION_SCOPES: tuple[str, ...] = (
    "rw_organization_admin",
    "r_organization_social",
    "w_organization_social",
    "r_organization_social_feed",
    "w_organization_social_feed",
)
"""Páginas de empresa: descubrirlas, leer y publicar, comentarios y reacciones. Son de la Community
Management API, que LinkedIn aprueba aparte. Los terminados en `_feed` son los de comentarios y reacciones."""

AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"  # noqa: S105  # es una URL
API_BASE = "https://api.linkedin.com"

_VERSION = re.compile(r"\d{6}")


@dataclass(frozen=True, slots=True, kw_only=True)
class LinkedInConfig:
    client_id: str
    client_secret: str = field(repr=False)
    api_version: str
    """`AAAAMM`, por ejemplo `202611`. Se fija a propósito: LinkedIn saca una versión por mes y retira cada
    una al año. Con una versión retirada, todas las llamadas fallan."""
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    authorize_url: str = AUTHORIZE_URL
    token_url: str = TOKEN_URL
    api_base: str = API_BASE
    page_size: int = 50
    """Publicaciones o comentarios por página. La API acepta hasta 100."""

    def __post_init__(self) -> None:
        if not _VERSION.fullmatch(self.api_version):
            raise ValueError("La versión de la API de LinkedIn va con la forma 'AAAAMM' (202611).")


@dataclass(frozen=True, slots=True)
class LinkedInOptions(PublishOptions):
    visibility: str = "PUBLIC"
    """`PUBLIC` o `CONNECTIONS` (solo para un perfil)."""
    link_title: str | None = None
    """El título de la tarjeta del link. LinkedIn no lee la página: si falta, se muestra la URL."""
    link_description: str | None = None
    reshare_disabled: bool = False
    little_text: bool = False
    """El texto ya viene en el formato de LinkedIn (con menciones `@[Nombre](urn:li:organization:1)`, por
    ejemplo): se manda tal cual, sin escapar los caracteres reservados."""


def urn(kind: str, external_id: str) -> str:
    """El URN del autor: una persona o una organización."""
    entity = "organization" if kind == LINKEDIN_ORGANIZATION else "person"
    return f"urn:li:{entity}:{external_id}"
