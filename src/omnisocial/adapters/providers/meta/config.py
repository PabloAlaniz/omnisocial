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


PUBLISH_SCOPES: tuple[str, ...] = ("pages_manage_posts", "instagram_content_publish")
"""Para publicar. No van en `CONNECT_SCOPES`: cada uno necesita su revisión de la app, y quien no publica no
tiene por qué pedirlos. Se suman con `connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MetaConfig:
    """La app de Meta y la versión de la Graph API.

    Sin `app_id` y `app_secret` funciona en **modo token**: solo con tokens cargados a mano (de un usuario de
    sistema, por ejemplo), sin OAuth, sin webhooks y sin `appsecret_proof`.
    """

    api_version: str
    """Por ejemplo `v24.0`. Se fija a propósito: Meta cambia métricas y campos entre versiones."""
    app_id: str | None = None
    app_secret: str | None = field(default=None, repr=False)
    graph_url: str = "https://graph.facebook.com"
    video_url: str = "https://graph-video.facebook.com"
    """El servidor donde se crean los videos de una página."""
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
        if bool(self.app_id) != bool(self.app_secret):
            raise ValueError("app_id y app_secret de Meta van juntos: los dos o ninguno.")
        if not self.api_version.startswith("v"):
            raise ValueError("La versión de la Graph API va con la forma 'v24.0'.")

    @property
    def base(self) -> str:
        return f"{self.graph_url.rstrip('/')}/{self.api_version}"

    @property
    def video_base(self) -> str:
        return f"{self.video_url.rstrip('/')}/{self.api_version}"

    @property
    def has_app(self) -> bool:
        """Si hay una app configurada. Sin app no hay OAuth, ni webhooks, ni `appsecret_proof`."""
        return bool(self.app_id and self.app_secret)

    @property
    def require_app(self) -> tuple[str, str]:
        """`(app_id, app_secret)`, o un error claro si se pidió algo que necesita la app en modo token."""
        if not self.app_id or not self.app_secret:
            raise ValueError("Esto necesita la app de Meta (app_id y app_secret); está en modo token.")
        return self.app_id, self.app_secret

    @property
    def app_access_token(self) -> str:
        app_id, app_secret = self.require_app
        return f"{app_id}|{app_secret}"
