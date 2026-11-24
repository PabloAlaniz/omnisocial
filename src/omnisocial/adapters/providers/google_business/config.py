"""Configuración del proyecto de Google para Business Profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

GOOGLE_BUSINESS = ProviderId("google_business")

GOOGLE_BUSINESS_LOCATION = "google_business_location"
"""Una sede (un local, una sucursal) que la cuenta administra."""

LOGIN_SCOPES: tuple[str, ...] = ("openid", "email", "profile")
BUSINESS_SCOPE = "https://www.googleapis.com/auth/business.manage"
CONNECT_SCOPES: tuple[str, ...] = (*LOGIN_SCOPES, BUSINESS_SCOPE)
"""Un solo permiso cubre todo: ver las sedes, publicar novedades y responder reseñas."""

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105  # es una URL
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
ACCOUNTS_BASE = "https://mybusinessaccountmanagement.googleapis.com/v1"
INFORMATION_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"
POSTS_BASE = "https://mybusiness.googleapis.com/v4"
"""Las novedades y las reseñas siguen en la versión 4."""
PERFORMANCE_BASE = "https://businessprofileperformance.googleapis.com/v1"

ACTIONS = frozenset({"BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "CALL"})
TOPICS = frozenset({"STANDARD", "EVENT", "OFFER"})


@dataclass(frozen=True, slots=True, kw_only=True)
class GoogleBusinessConfig:
    client_id: str
    client_secret: str = field(repr=False)
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    language_code: str = "es"
    """El idioma de las novedades, si el borrador no dice otro."""
    authorize_url: str = AUTHORIZE_URL
    token_url: str = TOKEN_URL
    revoke_url: str = REVOKE_URL
    userinfo_url: str = USERINFO_URL
    accounts_base: str = ACCOUNTS_BASE
    information_base: str = INFORMATION_BASE
    posts_base: str = POSTS_BASE
    performance_base: str = PERFORMANCE_BASE
    max_pages: int = 20
    """Cuántas páginas se recorren como mucho al leer cuentas, sedes, novedades o reseñas."""


@dataclass(frozen=True, slots=True)
class GoogleBusinessOptions(PublishOptions):
    """Una novedad puede llevar un botón, y puede ser un evento o una oferta con sus fechas."""

    topic: str = "STANDARD"
    """`STANDARD`, `EVENT` u `OFFER`."""
    action: str | None = None
    """El botón: `BOOK`, `ORDER`, `SHOP`, `LEARN_MORE`, `SIGN_UP` o `CALL`. Una oferta no lleva botón."""
    action_url: str | None = None
    """A dónde lleva el botón. `CALL` no lleva URL: llama al teléfono de la sede."""
    event_title: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    """El título y las fechas de un evento o de una oferta, en la hora de la sede."""
    coupon_code: str | None = None
    redeem_url: str | None = None
    terms: str | None = None
    language_code: str | None = None

    def __post_init__(self) -> None:
        if self.topic not in TOPICS:
            raise ValueError(f"El tipo de novedad es uno de: {', '.join(sorted(TOPICS))}.")
        if self.action is not None and self.action not in ACTIONS:
            raise ValueError(f"El botón es uno de: {', '.join(sorted(ACTIONS))}.")
        if self.action is not None and (self.action == "CALL") == (self.action_url is not None):
            raise ValueError("El botón lleva una URL, salvo `CALL`, que no lleva.")
        if self.topic != "STANDARD" and not (self.event_title and self.starts_at and self.ends_at):
            raise ValueError("Un evento o una oferta llevan título, comienzo y fin.")
