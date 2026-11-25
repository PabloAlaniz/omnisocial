"""Configuración de la app de YouTube (un proyecto de Google Cloud con la YouTube Data API v3)."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

YOUTUBE = ProviderId("youtube")

YOUTUBE_CHANNEL = "youtube_channel"

_SCOPE = "https://www.googleapis.com/auth"

LOGIN_SCOPES: tuple[str, ...] = (f"{_SCOPE}/youtube.readonly",)
"""Lo mínimo para saber qué canal autorizó."""

CONNECT_SCOPES: tuple[str, ...] = (f"{_SCOPE}/youtube.readonly",)
"""Leer el canal, sus videos, sus contadores y los comentarios."""

MODERATE_SCOPES: tuple[str, ...] = (f"{_SCOPE}/youtube.force-ssl",)
"""Responder y moderar comentarios, y borrar videos. Es el único permiso que lo habilita."""

PUBLISH_SCOPES: tuple[str, ...] = (f"{_SCOPE}/youtube.upload",)
"""Subir videos. Como los de moderar, se suman a mano:
`connect_scopes=CONNECT_SCOPES + MODERATE_SCOPES + PUBLISH_SCOPES`."""

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105  # es una URL
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3"

CHUNK_UNIT = 256 * 1024
"""Las partes de una subida tienen que ser múltiplos de 256 KB, salvo la última."""


@dataclass(frozen=True, slots=True)
class YouTubeConfig:
    client_id: str | None = None
    client_secret: str | None = field(default=None, repr=False)
    api_key: str | None = field(default=None, repr=False)
    """Una clave de API alcanza para leer perfiles públicos, sin que nadie autorice. Sin `client_id` y
    `client_secret` el proveedor solo ofrece eso."""
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    authorize_url: str = AUTHORIZE_URL
    token_url: str = TOKEN_URL
    revoke_url: str = REVOKE_URL
    api_base: str = API_BASE
    upload_base: str = UPLOAD_BASE
    page_size: int = 50
    """Videos por página. La API acepta hasta 50."""
    comments_page_size: int = 100
    upload_chunk_bytes: int = 32 * CHUNK_UNIT
    """8 MB por parte. Más grande sube más rápido; más chico pierde menos cuando se corta."""
    upload_attempts: int = 3
    """Cuántas veces seguidas puede fallar una parte antes de abandonar la subida."""
    quota_units: int = 10_000
    """Unidades por día del proyecto para todo menos subir y buscar. Se usa si se arma con un libro de
    cuota (`youtube_provider(..., quota=...)`)."""
    quota_uploads: int = 100
    """Subidas por día del proyecto: tienen su propio cupo."""

    def __post_init__(self) -> None:
        if bool(self.client_id) != bool(self.client_secret):
            raise ValueError("client_id y client_secret de YouTube van juntos: los dos o ninguno.")
        if not self.has_app and not self.api_key:
            raise ValueError("YouTube necesita la app (client_id y client_secret) o una clave de API.")
        if self.upload_chunk_bytes <= 0 or self.upload_chunk_bytes % CHUNK_UNIT:
            raise ValueError("Las partes de una subida tienen que ser múltiplos de 256 KB.")

    @property
    def has_app(self) -> bool:
        return bool(self.client_id and self.client_secret)


@dataclass(frozen=True, slots=True)
class YouTubeOptions(PublishOptions):
    title: str | None = None
    """Hasta 100 caracteres. Si falta, se usa la primera línea del texto."""
    privacy_status: str = "public"
    """`public`, `unlisted` o `private`."""
    made_for_kids: bool = False
    """YouTube exige declararlo. Un video para niños no tiene comentarios ni notificaciones."""
    category_id: str | None = None
    tags: tuple[str, ...] = ()
