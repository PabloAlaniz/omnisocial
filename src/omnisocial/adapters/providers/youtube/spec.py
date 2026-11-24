"""La descripción de YouTube: su OAuth (el de Google), sus capacidades y qué quiere decir cada error."""

from __future__ import annotations

from omnisocial.adapters.providers.youtube.config import (
    AUTHORIZE_URL,
    REVOKE_URL,
    TOKEN_URL,
    YOUTUBE,
    YOUTUBE_CHANNEL,
    YouTubeOptions,
)
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits, TextCount
from omnisocial.domain.spec import ErrorTable, NetworkSpec, OAuthSpec

CHANNEL_CAPABILITIES = frozenset(
    {Capability.CONTENT, Capability.COMMENTS, Capability.INSIGHTS, Capability.PUBLISHING}
)

# YouTube dice qué pasó en `error.errors[0].reason`; el estado HTTP solo no alcanza: un 403 puede ser la
# cuota, un permiso o un video con los comentarios desactivados.
ERRORS = ErrorTable(
    codes={
        # El token no sirve: lo revocaron o venció y no se pudo renovar.
        "authError": ErrorKind.TOKEN_DEAD,
        "insufficientPermissions": ErrorKind.MISSING_PERMISSION,
        # La cuota diaria del proyecto. Vuelve a medianoche, hora del Pacífico.
        "quotaExceeded": ErrorKind.QUOTA_EXHAUSTED,
        "dailyLimitExceeded": ErrorKind.QUOTA_EXHAUSTED,
        # Demasiados pedidos seguidos, o el canal subió demasiados videos hoy: se resuelve esperando.
        "rateLimitExceeded": ErrorKind.RATE_LIMITED,
        "userRateLimitExceeded": ErrorKind.RATE_LIMITED,
        "uploadRateLimitExceeded": ErrorKind.RATE_LIMITED,
        "uploadLimitExceeded": ErrorKind.RATE_LIMITED,
        # Lo que se pidió no se puede aceptar así.
        "invalidTitle": ErrorKind.INVALID_REQUEST,
        "invalidDescription": ErrorKind.INVALID_REQUEST,
        "invalidVideoMetadata": ErrorKind.INVALID_REQUEST,
        "invalidCategoryId": ErrorKind.INVALID_REQUEST,
        "forbiddenPrivacySetting": ErrorKind.INVALID_REQUEST,
        "commentTextTooLong": ErrorKind.INVALID_REQUEST,
        "commentTextRequired": ErrorKind.INVALID_REQUEST,
        "backendError": ErrorKind.TRANSIENT,
    }
)

COMMENTS_DISABLED = "commentsDisabled"
"""Un 403 que no es un error: el video tiene los comentarios desactivados."""

# Un video por publicación, siempre como archivo: YouTube no va a buscar una URL.
CHANNEL_LIMITS = PublishLimits(
    max_text=5000,
    text_count=TextCount.UTF8,
    max_videos=1,
    media_required=True,
    media_by_url=False,
    media_by_file=True,
    max_video_bytes=256 * 1024**3,
    max_video_seconds=12 * 60 * 60,
    delete=True,
    options=YouTubeOptions,
)


def oauth_spec(
    *, authorize_url: str = AUTHORIZE_URL, token_url: str = TOKEN_URL, revoke_url: str = REVOKE_URL
) -> OAuthSpec:
    return OAuthSpec(
        authorize_url=authorize_url,
        token_url=token_url,
        revoke_url=revoke_url,
        revoke_with_credentials=False,
        # `offline` para recibir un token de renovación, y `consent` para que Google lo vuelva a mandar si
        # la persona ya había autorizado: sin eso solo llega la primera vez.
        authorize_params={"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
    )


SPEC = NetworkSpec(
    id=YOUTUBE,
    name="YouTube",
    capabilities=frozenset(
        {
            Capability.LOGIN,
            Capability.ASSETS,
            Capability.CONTENT,
            Capability.COMMENTS,
            Capability.INSIGHTS,
            Capability.PUBLISHING,
            Capability.PUBLIC_PROFILES,
        }
    ),
    assets={YOUTUBE_CHANNEL: CHANNEL_CAPABILITIES},
    errors=ERRORS,
    oauth=oauth_spec(),
    docs="docs/youtube.md",
    publishing={YOUTUBE_CHANNEL: CHANNEL_LIMITS},
)
