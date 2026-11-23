"""Configuración de la app de TikTok."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId

TIKTOK = ProviderId("tiktok")

TIKTOK_ACCOUNT = "tiktok_account"

LOGIN_SCOPES: tuple[str, ...] = ("user.info.basic",)
"""Lo mínimo para saber quién es la persona."""

CONNECT_SCOPES: tuple[str, ...] = ("user.info.basic", "user.info.profile", "user.info.stats", "video.list")
"""Perfil, contadores de la cuenta y videos públicos. Fuera del sandbox, cada uno necesita la revisión de la
app. Ver `docs/tiktok.md`."""


@dataclass(frozen=True, slots=True)
class TikTokConfig:
    client_key: str
    client_secret: str = field(repr=False)
    previous_client_secrets: tuple[str, ...] = field(default=(), repr=False)
    """Secretos anteriores, para no perder avisos firmados con ellos mientras se rota."""
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    authorize_url: str = "https://www.tiktok.com/v2/auth/authorize/"
    api_base: str = "https://open.tiktokapis.com/v2"
    page_size: int = 20
    """Videos por página. TikTok acepta hasta 20."""
    webhook_tolerance_seconds: int = 300
    """Cuánto puede tener de antigüedad un aviso firmado."""

    @property
    def webhook_secrets(self) -> tuple[str, ...]:
        return tuple(s for s in (self.client_secret, *self.previous_client_secrets) if s)
