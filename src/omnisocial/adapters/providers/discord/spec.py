"""La descripción de Discord, por bot y por webhook, y qué quiere decir cada error."""

from __future__ import annotations

from datetime import date

from omnisocial.adapters.providers.discord.config import (
    AUTHORIZE_URL,
    DISCORD,
    DISCORD_GUILD,
    DISCORD_WEBHOOK,
    DISCORD_WEBHOOK_CHANNEL,
    DiscordOptions,
    DiscordWebhookOptions,
)
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.lookup import LookupSpec
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits
from omnisocial.domain.spec import ApiPin, ErrorTable, NetworkSpec, OAuthSpec, Pace

GUILD_CAPABILITIES = frozenset({Capability.PUBLISHING})
WEBHOOK_CAPABILITIES = frozenset({Capability.PUBLISHING})

_COMMON = {
    # Al bot le falta acceso al canal o un permiso en él: se arregla en el servidor, o sumándolo de
    # nuevo con los permisos que hacen falta.
    "50001": ErrorKind.MISSING_PERMISSION,
    "50013": ErrorKind.MISSING_PERMISSION,
    # El canal, el servidor o el mensaje no existen (o el bot no los ve).
    "10003": ErrorKind.INVALID_REQUEST,
    "10004": ErrorKind.INVALID_REQUEST,
    "10008": ErrorKind.INVALID_REQUEST,
    # El mensaje está vacío, tiene un campo mal o es demasiado grande.
    "50006": ErrorKind.INVALID_REQUEST,
    "50035": ErrorKind.INVALID_REQUEST,
    "40005": ErrorKind.INVALID_REQUEST,
    # Un foro que exige una etiqueta, o un link que el filtro del servidor no deja pasar.
    "40067": ErrorKind.INVALID_REQUEST,
    "240000": ErrorKind.INVALID_REQUEST,
    # El canal está en modo lento, o el canal o el servidor llegaron a su tope de escrituras.
    "20016": ErrorKind.RATE_LIMITED,
    "20028": ErrorKind.RATE_LIMITED,
    "20029": ErrorKind.RATE_LIMITED,
}

ERRORS = ErrorTable(codes=_COMMON, statuses={401: ErrorKind.TOKEN_DEAD, 400: ErrorKind.INVALID_REQUEST})
WEBHOOK_ERRORS = ErrorTable(
    codes={
        **_COMMON,
        # Borraron el webhook: no hay con qué publicar.
        "10015": ErrorKind.TOKEN_DEAD,
        "50027": ErrorKind.TOKEN_DEAD,
    },
    statuses={401: ErrorKind.TOKEN_DEAD, 400: ErrorKind.INVALID_REQUEST},
)

_MAX_FILE = 20 * 1024**2
_LIMITS = {
    "max_text": 2000,
    "max_images": 10,
    "max_videos": 10,
    "max_media": 10,
    "mix_media": True,
    "media_by_url": True,
    "media_by_file": True,
    # Una imagen por URL se muestra incrustada; un video no: va como archivo.
    "video_by_url": False,
    "max_image_bytes": _MAX_FILE,
    "max_video_bytes": _MAX_FILE,
    "delete": True,
}
GUILD_LIMITS = PublishLimits(**_LIMITS, options=DiscordOptions, options_required=True)  # type: ignore[arg-type]
WEBHOOK_LIMITS = PublishLimits(**_LIMITS, options=DiscordWebhookOptions)  # type: ignore[arg-type]

CHANNELS = LookupSpec("channels", "Los canales del servidor donde el bot puede publicar.")

PACE = Pace(max_concurrent=5)
"""50 pedidos por segundo por bot, y además un tope por canal que Discord informa en cada respuesta."""


def oauth_spec(*, authorize_url: str = AUTHORIZE_URL, api_base: str, permissions: int) -> OAuthSpec:
    """La app se identifica por cabecera, hay PKCE y cada renovación trae un token de renovación nuevo.
    `permissions` es lo que se le pide al servidor para el bot."""
    return OAuthSpec(
        authorize_url=authorize_url,
        token_url=f"{api_base}/oauth2/token",
        revoke_url=f"{api_base}/oauth2/token/revoke",
        client_auth_basic=True,
        refresh_rotates=True,
        authorize_params={"permissions": str(permissions)},
    )


SPEC = NetworkSpec(
    id=DISCORD,
    name="Discord",
    capabilities=frozenset({Capability.LOGIN, Capability.ASSETS, Capability.PUBLISHING}),
    assets={DISCORD_GUILD: GUILD_CAPABILITIES},
    errors=ERRORS,
    oauth=oauth_spec(api_base="https://discord.com/api/v10", permissions=0),
    docs="docs/discord.md",
    api=ApiPin(
        "v10", reviewed=date(2026, 11, 24), changelog="https://discord.com/developers/docs/change-log"
    ),
    publishing={DISCORD_GUILD: GUILD_LIMITS},
    lookups={DISCORD_GUILD: (CHANNELS,)},
    pace=PACE,
)

WEBHOOK_SPEC = NetworkSpec(
    id=DISCORD_WEBHOOK,
    name="Discord (webhook)",
    capabilities=frozenset({Capability.CREDENTIALS, Capability.ASSETS, Capability.PUBLISHING}),
    assets={DISCORD_WEBHOOK_CHANNEL: WEBHOOK_CAPABILITIES},
    errors=WEBHOOK_ERRORS,
    docs="docs/discord.md",
    api=ApiPin(
        "v10", reviewed=date(2026, 11, 24), changelog="https://discord.com/developers/docs/change-log"
    ),
    publishing={DISCORD_WEBHOOK_CHANNEL: WEBHOOK_LIMITS},
    pace=PACE,
)

EXTRA_SPECS = (WEBHOOK_SPEC,)
