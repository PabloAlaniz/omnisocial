"""La descripción de Google Business Profile: su OAuth, sus capacidades y qué quiere decir cada error."""

from __future__ import annotations

from omnisocial.adapters.providers.google_business.config import (
    AUTHORIZE_URL,
    GOOGLE_BUSINESS,
    GOOGLE_BUSINESS_LOCATION,
    REVOKE_URL,
    TOKEN_URL,
    GoogleBusinessOptions,
)
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits
from omnisocial.domain.spec import ErrorTable, NetworkSpec, OAuthSpec, Pace

LOCATION_CAPABILITIES = frozenset(
    {Capability.CONTENT, Capability.COMMENTS, Capability.INSIGHTS, Capability.PUBLISHING}
)

# Google dice qué pasó en `error.status` y, con más detalle, en `error.details[].reason`.
ERRORS = ErrorTable(
    codes={
        "UNAUTHENTICATED": ErrorKind.TOKEN_DEAD,
        "ACCESS_TOKEN_SCOPE_INSUFFICIENT": ErrorKind.MISSING_PERMISSION,
        # Pasa el tope por minuto. También es lo que responde un proyecto al que Google todavía no le
        # aprobó el acceso a la API: su cupo es cero.
        "RESOURCE_EXHAUSTED": ErrorKind.RATE_LIMITED,
        "RATE_LIMIT_EXCEEDED": ErrorKind.RATE_LIMITED,
        "INVALID_ARGUMENT": ErrorKind.INVALID_REQUEST,
        # La sede no está en condiciones (sin verificar, por ejemplo).
        "FAILED_PRECONDITION": ErrorKind.INVALID_REQUEST,
    },
    statuses={401: ErrorKind.TOKEN_DEAD, 400: ErrorKind.INVALID_REQUEST},
)
"""Un `PERMISSION_DENIED` a secas no es un permiso faltante: la cuenta no administra esa sede, y
reconectar no lo arregla."""

# Las fotos van por URL. El botón, con su link, va en las opciones.
LOCATION_LIMITS = PublishLimits(
    max_text=1500,
    max_images=10,
    media_by_url=True,
    delete=True,
    options=GoogleBusinessOptions,
)

PACE = Pace(max_concurrent=4)
"""300 pedidos por minuto por proyecto, y 10 cambios por minuto en una misma sede."""


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
        authorize_params={"access_type": "offline", "prompt": "consent"},
    )


SPEC = NetworkSpec(
    id=GOOGLE_BUSINESS,
    name="Google Business Profile",
    capabilities=frozenset(
        {
            Capability.LOGIN,
            Capability.ASSETS,
            Capability.CONTENT,
            Capability.COMMENTS,
            Capability.INSIGHTS,
            Capability.PUBLISHING,
        }
    ),
    assets={GOOGLE_BUSINESS_LOCATION: LOCATION_CAPABILITIES},
    errors=ERRORS,
    oauth=oauth_spec(),
    docs="docs/google-business.md",
    publishing={GOOGLE_BUSINESS_LOCATION: LOCATION_LIMITS},
    pace=PACE,
)
