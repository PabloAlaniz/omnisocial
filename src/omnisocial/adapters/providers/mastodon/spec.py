"""La descripción de Mastodon y de Pixelfed: sus capacidades, sus límites y qué quiere decir cada error."""

from __future__ import annotations

from datetime import date

from omnisocial.adapters.providers.mastodon.config import (
    MASTODON,
    MASTODON_ACCOUNT,
    PIXELFED,
    PIXELFED_ACCOUNT,
    MastodonOptions,
)
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits
from omnisocial.domain.spec import ApiPin, ErrorTable, NetworkSpec

ACCOUNT_CAPABILITIES = frozenset(
    {Capability.CONTENT, Capability.COMMENTS, Capability.INSIGHTS, Capability.PUBLISHING}
)

OUT_OF_SCOPE = "scope"
"""El código de la tabla para "esta acción está fuera de los permisos autorizados". El protocolo no tiene
códigos: se reconoce por el mensaje."""

ERRORS = ErrorTable(
    codes={OUT_OF_SCOPE: ErrorKind.MISSING_PERMISSION},
    statuses={
        # Un token de Mastodon no vence: un 401 quiere decir que la persona quitó el acceso.
        401: ErrorKind.TOKEN_DEAD,
        422: ErrorKind.INVALID_REQUEST,
    },
)

# Los límites por defecto de un servidor de Mastodon. Cada servidor puede cambiarlos; si uno acepta menos,
# rechaza la publicación y vuelve `Refused(CONTENT_REJECTED)`.
MASTODON_LIMITS = PublishLimits(
    max_text=500,
    max_images=4,
    max_videos=1,
    media_by_url=False,
    media_by_file=True,
    max_image_bytes=16 * 1024**2,
    max_video_bytes=99 * 1024**2,
    delete=True,
    options=MastodonOptions,
    max_thread=24,
)

# Pixelfed es para fotos: no acepta publicaciones sin medios, y por defecto tampoco videos.
PIXELFED_LIMITS = PublishLimits(
    max_text=500,
    max_images=4,
    media_required=True,
    media_by_url=False,
    media_by_file=True,
    max_image_bytes=15_000_000,
    delete=True,
    options=MastodonOptions,
)

_COMMON = frozenset(
    {
        Capability.LOGIN,
        Capability.ASSETS,
        Capability.CONTENT,
        Capability.COMMENTS,
        Capability.INSIGHTS,
        Capability.PUBLISHING,
    }
)

SPEC = NetworkSpec(
    id=MASTODON,
    name="Mastodon",
    capabilities=_COMMON | {Capability.PUBLIC_PROFILES},
    assets={MASTODON_ACCOUNT: ACCOUNT_CAPABILITIES},
    errors=ERRORS,
    docs="docs/mastodon.md",
    api=ApiPin("v1 y v2", reviewed=date(2026, 11, 24), changelog="https://docs.joinmastodon.org/"),
    publishing={MASTODON_ACCOUNT: MASTODON_LIMITS},
)

PIXELFED_SPEC = NetworkSpec(
    id=PIXELFED,
    name="Pixelfed",
    capabilities=_COMMON,
    assets={PIXELFED_ACCOUNT: ACCOUNT_CAPABILITIES},
    errors=ERRORS,
    docs="docs/mastodon.md",
    api=ApiPin("v1 y v2", reviewed=date(2026, 11, 24), changelog="https://docs.joinmastodon.org/"),
    publishing={PIXELFED_ACCOUNT: PIXELFED_LIMITS},
)

EXTRA_SPECS = (PIXELFED_SPEC,)
"""Otras redes que viven en este paquete porque hablan el mismo protocolo."""
