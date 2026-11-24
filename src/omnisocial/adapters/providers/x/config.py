"""Configuración de la app de X."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

X = ProviderId("x")

X_ACCOUNT = "x_account"

LOGIN_SCOPES: tuple[str, ...] = ("tweet.read", "users.read")
"""Lo mínimo para saber quién es la persona. X pide `tweet.read` hasta para eso."""

CONNECT_SCOPES: tuple[str, ...] = ("tweet.read", "users.read", "offline.access")
"""Leer la cuenta y sus posts. Sin `offline.access` no hay token de renovación y la conexión dura dos
horas."""

PUBLISH_SCOPES: tuple[str, ...] = ("tweet.write", "media.write")
"""Publicar, responder, borrar y subir medios."""

MODERATE_SCOPES: tuple[str, ...] = ("tweet.moderate.write", "like.write")
"""Ocultar respuestas y dar like."""

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
API_BASE = "https://api.x.com/2"

MEDIA_SEGMENT_BYTES = 3 * 1024 * 1024
"""Cada parte de un medio va en JSON, en Base64: 3 MB de archivo son 4 MB de pedido, el tope."""


@dataclass(frozen=True, slots=True)
class XConfig:
    client_id: str | None = None
    client_secret: str | None = field(default=None, repr=False)
    bearer_token: str | None = field(default=None, repr=False)
    """El token de la app. Alcanza para leer perfiles públicos, sin que nadie autorice. Sin `client_id` y
    `client_secret` el proveedor solo ofrece eso."""
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    authorize_url: str = AUTHORIZE_URL
    api_base: str = API_BASE
    page_size: int = 100
    """Posts por página. La API acepta entre 5 y 100."""
    post_fields_param: str = "tweet.fields"
    """El nombre del parámetro con los campos de un post. La documentación de X usa `tweet.fields` en las
    guías y `post.fields` en la especificación: si la API deja de aceptar uno, se cambia acá."""
    max_post_length: int = 280
    """Con X Premium la cuenta puede publicar textos más largos."""
    media_segment_bytes: int = MEDIA_SEGMENT_BYTES

    def __post_init__(self) -> None:
        if bool(self.client_id) != bool(self.client_secret):
            raise ValueError("client_id y client_secret de X van juntos: los dos o ninguno.")
        if not self.has_app and not self.bearer_token:
            raise ValueError("X necesita la app (client_id y client_secret) o el token de la app.")
        if not 0 < self.media_segment_bytes <= MEDIA_SEGMENT_BYTES:
            raise ValueError("Las partes de un medio no pueden pasar de 3 MB.")

    @property
    def has_app(self) -> bool:
        return bool(self.client_id and self.client_secret)


@dataclass(frozen=True, slots=True)
class XOptions(PublishOptions):
    reply_to: str | None = None
    """El id del post al que responde. En el plan de pago por uso, X solo deja responder por API a quien
    mencionó o citó a la cuenta."""
