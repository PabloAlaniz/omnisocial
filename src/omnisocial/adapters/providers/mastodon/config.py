"""Configuración de Mastodon y de Pixelfed.

No hay una app que registrar de antemano: la librería registra una en cada servidor la primera vez que
alguien de ese servidor conecta, y la guarda.
"""

from __future__ import annotations

from dataclasses import dataclass

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

MASTODON = ProviderId("mastodon")
PIXELFED = ProviderId("pixelfed")

MASTODON_ACCOUNT = "mastodon_account"
PIXELFED_ACCOUNT = "pixelfed_account"

LOGIN_SCOPES: tuple[str, ...] = ("read:accounts",)
CONNECT_SCOPES: tuple[str, ...] = ("read:accounts", "read:statuses")
"""Leer la cuenta, sus publicaciones y las respuestas."""
PUBLISH_SCOPES: tuple[str, ...] = ("write:statuses", "write:media")
"""Publicar, responder, borrar y subir medios."""
MODERATE_SCOPES: tuple[str, ...] = ("write:favourites",)
"""Marcar como favorita una respuesta."""

PIXELFED_LOGIN_SCOPES: tuple[str, ...] = ("read",)
PIXELFED_CONNECT_SCOPES: tuple[str, ...] = ("read",)
PIXELFED_PUBLISH_SCOPES: tuple[str, ...] = ("write",)
"""Pixelfed no tiene permisos finos: `write` cubre publicar, responder, borrar y marcar favoritas."""


@dataclass(frozen=True, slots=True)
class MastodonConfig:
    client_name: str = "omnisocial"
    """El nombre con que la app aparece en cada servidor, cuando la persona autoriza."""
    website: str | None = None
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    app_scopes: tuple[str, ...] = CONNECT_SCOPES + PUBLISH_SCOPES + MODERATE_SCOPES
    """Los permisos con que se registra la app en cada servidor: el máximo que después se le puede pedir a
    una persona. Si se agrandan, las apps ya registradas no los tienen: hay que registrarlas de nuevo."""
    page_size: int = 40
    """Publicaciones por página. La API acepta hasta 40."""


@dataclass(frozen=True, slots=True)
class PixelfedConfig(MastodonConfig):
    login_scopes: tuple[str, ...] = PIXELFED_LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = PIXELFED_CONNECT_SCOPES
    app_scopes: tuple[str, ...] = PIXELFED_CONNECT_SCOPES + PIXELFED_PUBLISH_SCOPES


@dataclass(frozen=True, slots=True)
class MastodonOptions(PublishOptions):
    visibility: str = "public"
    """`public`, `unlisted`, `private` (solo seguidores) o `direct` (solo los mencionados)."""
    sensitive: bool = False
    spoiler_text: str | None = None
    """La advertencia de contenido: el texto queda oculto detrás."""
    language: str | None = None
    reply_to: str | None = None
    """El id de la publicación a la que responde, en el servidor de la cuenta."""


@dataclass(frozen=True, slots=True)
class Flavor:
    """En qué se diferencian las redes que comparten el protocolo."""

    provider: ProviderId
    name: str
    account_kind: str
    pkce: bool


MASTODON_FLAVOR = Flavor(MASTODON, "Mastodon", MASTODON_ACCOUNT, pkce=True)
# No se pudo confirmar que Pixelfed acepte PKCE: no se manda.
PIXELFED_FLAVOR = Flavor(PIXELFED, "Pixelfed", PIXELFED_ACCOUNT, pkce=False)
