"""Configuración de la app de TikTok."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

TIKTOK = ProviderId("tiktok")

TIKTOK_ACCOUNT = "tiktok_account"

LOGIN_SCOPES: tuple[str, ...] = ("user.info.basic",)
"""Lo mínimo para saber quién es la persona."""

CONNECT_SCOPES: tuple[str, ...] = ("user.info.basic", "user.info.profile", "user.info.stats", "video.list")
"""Perfil, contadores de la cuenta y videos públicos. Fuera del sandbox, cada uno necesita la revisión de la
app. Ver `docs/tiktok.md`."""


PUBLISH_SCOPES: tuple[str, ...] = ("video.publish",)
"""Para publicar. No va en `CONNECT_SCOPES`: necesita su propia revisión de la app. Se suma con
`connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES`."""

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
API_BASE = "https://open.tiktokapis.com/v2"


@dataclass(frozen=True, slots=True)
class TikTokConfig:
    client_key: str
    client_secret: str = field(repr=False)
    previous_client_secrets: tuple[str, ...] = field(default=(), repr=False)
    """Secretos anteriores, para no perder avisos firmados con ellos mientras se rota."""
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    authorize_url: str = AUTHORIZE_URL
    api_base: str = API_BASE
    page_size: int = 20
    """Videos por página. TikTok acepta hasta 20."""
    webhook_tolerance_seconds: int = 300
    """Cuánto puede tener de antigüedad un aviso firmado."""

    @property
    def webhook_secrets(self) -> tuple[str, ...]:
        return tuple(s for s in (self.client_secret, *self.previous_client_secrets) if s)


@dataclass(frozen=True, slots=True)
class TikTokOptions(PublishOptions):
    privacy_level: str = "SELF_ONLY"
    """Quién la ve. Una app sin auditar solo puede publicar en privado (`SELF_ONLY`); las opciones de cada
    cuenta las informa TikTok (`PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`, `FOLLOWER_OF_CREATOR`)."""
    disable_comment: bool = False
    disable_duet: bool = False
    disable_stitch: bool = False
    brand_content: bool = False
    """Contenido pago para un tercero."""
    brand_organic: bool = False
    """Promociona la marca propia."""
    photo_title: str | None = None
    """El título de una publicación de fotos (hasta 90). Si falta, se usa el comienzo del texto."""
