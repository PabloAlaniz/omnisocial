"""Configuración de la app de Meta."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from omnisocial.domain.provider import ProviderId

META = ProviderId("meta")

FACEBOOK_PAGE = "facebook_page"
INSTAGRAM_ACCOUNT = "instagram_account"

LOGIN_SCOPES: tuple[str, ...] = ("public_profile", "email")
"""Lo mínimo para saber quién es la persona."""

CONNECT_SCOPES: tuple[str, ...] = (
    "public_profile",
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_engagement",
    "pages_manage_metadata",
    "pages_messaging",
    "read_insights",
    "business_management",
    "instagram_basic",
    "instagram_manage_comments",
    "instagram_manage_messages",
)
"""Para administrar páginas y cuentas de Instagram conectadas a ellas.

Cada permiso que no sea básico necesita acceso avanzado, y el acceso avanzado necesita la revisión de la
app y la verificación del negocio. Ver `docs/meta.md`.
"""


@dataclass(frozen=True, slots=True)
class MetaConfig:
    app_id: str
    app_secret: str = field(repr=False)
    api_version: str
    """Por ejemplo `v24.0`. Se fija a propósito: Meta cambia métricas y campos entre versiones."""
    graph_url: str = "https://graph.facebook.com"
    dialog_url: str = "https://www.facebook.com"
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    previous_app_secrets: tuple[str, ...] = field(default=(), repr=False)
    """Secretos anteriores que todavía se aceptan para firmar webhooks, mientras se rota el secreto."""
    webhook_verify_token: str | None = field(default=None, repr=False)
    """El que se carga al suscribir los webhooks en el panel de la app."""
    use_appsecret_proof: bool = True
    """Firma cada llamada con `appsecret_proof`. Conviene activar "Require App Secret" en la app."""
    insights_max_span: timedelta = timedelta(days=90)
    """La Graph API no devuelve métricas de más de ~93 días por llamada: se parte la ventana."""
    page_size: int = 50

    def __post_init__(self) -> None:
        if not self.app_id or not self.app_secret:
            raise ValueError("Faltan app_id o app_secret de Meta.")
        if not self.api_version.startswith("v"):
            raise ValueError("La versión de la Graph API va con la forma 'v24.0'.")

    @property
    def base(self) -> str:
        return f"{self.graph_url.rstrip('/')}/{self.api_version}"

    @property
    def app_access_token(self) -> str:
        return f"{self.app_id}|{self.app_secret}"
