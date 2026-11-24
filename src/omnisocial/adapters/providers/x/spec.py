"""La descripción de X: su OAuth, sus capacidades y qué quiere decir cada error."""

from __future__ import annotations

from omnisocial.adapters.providers.x.config import API_BASE, AUTHORIZE_URL, X_ACCOUNT, X, XOptions
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits, TextCount
from omnisocial.domain.spec import ErrorTable, NetworkSpec, OAuthSpec

ACCOUNT_CAPABILITIES = frozenset(
    {Capability.CONTENT, Capability.COMMENTS, Capability.INSIGHTS, Capability.PUBLISHING}
)

# X describe el problema en `type` (una URL): el código de la tabla es su último tramo.
ERRORS = ErrorTable(
    codes={
        "rate-limit-exceeded": ErrorKind.RATE_LIMITED,
        # Se llegó al tope de uso o de gasto de la app.
        "usage-capped": ErrorKind.QUOTA_EXHAUSTED,
        # A la app le falta el acceso a ese endpoint, o no está en un proyecto con pago por uso.
        "client-forbidden": ErrorKind.MISSING_PERMISSION,
        "client-not-enrolled": ErrorKind.MISSING_PERMISSION,
        "invalid-request": ErrorKind.INVALID_REQUEST,
    },
    statuses={
        # El token no sirve: venció sin poder renovarse o la persona quitó el acceso.
        401: ErrorKind.TOKEN_DEAD,
        # La app se quedó sin créditos. No es el token: la conexión sigue sana.
        402: ErrorKind.QUOTA_EXHAUSTED,
        400: ErrorKind.INVALID_REQUEST,
    },
)


def account_limits(max_text: int = 280) -> PublishLimits:
    """Hasta 4 fotos o un video, siempre como archivo: X no va a buscar una URL."""
    return PublishLimits(
        max_text=max_text,
        text_count=TextCount.WEIGHTED,
        max_images=4,
        max_videos=1,
        media_by_url=False,
        media_by_file=True,
        max_image_bytes=5 * 1024**2,
        max_video_bytes=8 * 1024**3,
        max_video_seconds=20 * 60,
        delete=True,
        options=XOptions,
        max_thread=24,
    )


ACCOUNT_LIMITS = account_limits()


def oauth_spec(*, authorize_url: str = AUTHORIZE_URL, api_base: str = API_BASE) -> OAuthSpec:
    return OAuthSpec(
        authorize_url=authorize_url,
        token_url=f"{api_base}/oauth2/token",
        revoke_url=f"{api_base}/oauth2/revoke",
        client_auth_basic=True,
        refresh_rotates=True,
    )


SPEC = NetworkSpec(
    id=X,
    name="X",
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
    assets={X_ACCOUNT: ACCOUNT_CAPABILITIES},
    errors=ERRORS,
    oauth=oauth_spec(),
    docs="docs/x.md",
    publishing={X_ACCOUNT: ACCOUNT_LIMITS},
)
