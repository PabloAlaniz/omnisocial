"""La descripción de Bluesky: sus capacidades, sus límites y qué quiere decir cada error."""

from __future__ import annotations

from datetime import date

from omnisocial.adapters.providers.bluesky.config import BLUESKY, BLUESKY_ACCOUNT, BlueskyOptions
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits
from omnisocial.domain.spec import ApiPin, ErrorTable, NetworkSpec

ACCOUNT_CAPABILITIES = frozenset(
    {Capability.CONTENT, Capability.COMMENTS, Capability.INSIGHTS, Capability.PUBLISHING}
)

# Bluesky nombra el error en `error`. Un token de acceso vencido (`ExpiredToken`) no está en la tabla a
# propósito: se renueva, y no es motivo para invalidar la conexión.
ERRORS = ErrorTable(
    codes={
        # El token no es de una sesión válida, o la cuenta fue dada de baja o suspendida.
        "InvalidToken": ErrorKind.TOKEN_DEAD,
        "AccountTakedown": ErrorKind.TOKEN_DEAD,
        "AccountDeactivated": ErrorKind.TOKEN_DEAD,
        "RateLimitExceeded": ErrorKind.RATE_LIMITED,
        "InvalidRequest": ErrorKind.INVALID_REQUEST,
        "BlobTooLarge": ErrorKind.INVALID_REQUEST,
        "InvalidMimeType": ErrorKind.INVALID_REQUEST,
        "UpstreamFailure": ErrorKind.TRANSIENT,
    }
)

# Hasta 4 imágenes o un video, subidos como archivo. El límite es de 300 grafemas: acá se cuentan
# caracteres, que nunca son menos. Un video se sube entero en un pedido, así que el tope es el del
# servidor (50 MB).
ACCOUNT_LIMITS = PublishLimits(
    max_text=300,
    max_images=4,
    max_videos=1,
    media_by_url=False,
    media_by_file=True,
    max_image_bytes=2_000_000,
    max_video_bytes=50 * 1024**2,
    link=True,
    delete=True,
    options=BlueskyOptions,
    max_thread=24,
)

SPEC = NetworkSpec(
    id=BLUESKY,
    name="Bluesky",
    capabilities=frozenset(
        {
            Capability.CREDENTIALS,
            Capability.ASSETS,
            Capability.CONTENT,
            Capability.COMMENTS,
            Capability.INSIGHTS,
            Capability.PUBLISHING,
            Capability.PUBLIC_PROFILES,
        }
    ),
    assets={BLUESKY_ACCOUNT: ACCOUNT_CAPABILITIES},
    errors=ERRORS,
    docs="docs/bluesky.md",
    api=ApiPin(
        "lexicons de app.bsky y com.atproto",
        reviewed=date(2026, 11, 24),
        changelog="https://docs.bsky.app/blog",
    ),
    publishing={BLUESKY_ACCOUNT: ACCOUNT_LIMITS},
)
