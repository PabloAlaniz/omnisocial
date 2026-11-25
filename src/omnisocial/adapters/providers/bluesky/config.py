"""Configuración de Bluesky. No hay app que registrar: la persona conecta con una contraseña de aplicación."""

from __future__ import annotations

from dataclasses import dataclass

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

BLUESKY = ProviderId("bluesky")

BLUESKY_ACCOUNT = "bluesky_account"

DEFAULT_SERVER = "bsky.social"
"""Donde están casi todas las cuentas. Quien tiene su propio servidor de datos lo indica al conectar."""

POST = "app.bsky.feed.post"
LIKE = "app.bsky.feed.like"


@dataclass(frozen=True, slots=True)
class BlueskyConfig:
    default_server: str = DEFAULT_SERVER
    public_api: str = "https://public.api.bsky.app"
    """Para leer perfiles públicos sin que nadie conecte."""
    page_size: int = 50
    """Posts por página. La API acepta hasta 100."""


@dataclass(frozen=True, slots=True)
class BlueskyOptions(PublishOptions):
    reply_to: str | None = None
    """El post al que responde, como `at://did:plc:…/app.bsky.feed.post/…`."""
    langs: tuple[str, ...] = ()
    """Los idiomas del post (`es`, `en`): hasta tres."""
    link_title: str | None = None
    """El título de la tarjeta del link. Bluesky no lee la página: si falta, se muestra la URL."""
    link_description: str | None = None


def rkey(uri: str) -> str:
    """El último tramo de `at://did/colección/rkey`."""
    return uri.rsplit("/", 1)[-1]


def post_url(did: str, uri: str) -> str:
    return f"https://bsky.app/profile/{did}/post/{rkey(uri)}"
