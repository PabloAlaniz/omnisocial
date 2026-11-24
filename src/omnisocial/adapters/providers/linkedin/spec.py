"""La descripción de LinkedIn: su OAuth, sus capacidades y qué quiere decir cada error."""

from __future__ import annotations

from omnisocial.adapters.providers.linkedin.config import (
    AUTHORIZE_URL,
    LINKEDIN,
    LINKEDIN_MEMBER,
    LINKEDIN_ORGANIZATION,
    TOKEN_URL,
    LinkedInOptions,
)
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits
from omnisocial.domain.spec import ErrorTable, NetworkSpec, OAuthSpec

# Leer las publicaciones de un perfil pide un permiso restringido (`r_member_social`): un perfil solo publica.
MEMBER_CAPABILITIES = frozenset({Capability.PUBLISHING})
ORGANIZATION_CAPABILITIES = frozenset(
    {Capability.CONTENT, Capability.COMMENTS, Capability.INSIGHTS, Capability.PUBLISHING}
)

ERRORS = ErrorTable(
    codes={
        # Al token le falta un permiso, o la app no tiene aprobado el producto que lo da.
        "ACCESS_DENIED": ErrorKind.MISSING_PERMISSION,
        # El mismo caso en las respuestas viejas, que no traen `code`.
        "100": ErrorKind.MISSING_PERMISSION,
        # Se llegó al tope diario del endpoint, de la app o de la persona. Vuelve a medianoche UTC.
        "TOO_MANY_REQUESTS": ErrorKind.RATE_LIMITED,
        "FIELD_LENGTH_TOO_LONG": ErrorKind.INVALID_REQUEST,
        "UNPROCESSABLE_ENTITY": ErrorKind.INVALID_REQUEST,
    },
    statuses={
        # LinkedIn usa el 401 solo para el token: falta, es inválido, venció o lo revocaron.
        401: ErrorKind.TOKEN_DEAD,
        400: ErrorKind.INVALID_REQUEST,
        422: ErrorKind.INVALID_REQUEST,
    },
)

# Los medios se suben como archivo: LinkedIn no va a buscar una URL.
_COMMON = {
    "max_text": 3000,
    "max_images": 20,
    "max_videos": 1,
    "media_by_url": False,
    "media_by_file": True,
    "max_video_bytes": 500 * 1024**2,
    "max_video_seconds": 30 * 60,
    "link": True,
    "delete": True,
    "options": LinkedInOptions,
}
MEMBER_LIMITS = PublishLimits(**_COMMON)  # type: ignore[arg-type]
# El primer comentario se publica como la página; como persona pide un permiso restringido.
ORGANIZATION_LIMITS = PublishLimits(**_COMMON, first_comment=True)  # type: ignore[arg-type]


def oauth_spec(*, authorize_url: str = AUTHORIZE_URL, token_url: str = TOKEN_URL) -> OAuthSpec:
    """Para apps web LinkedIn no usa PKCE, y no documenta un endpoint para revocar."""
    return OAuthSpec(authorize_url=authorize_url, token_url=token_url, pkce=False)


SPEC = NetworkSpec(
    id=LINKEDIN,
    name="LinkedIn",
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
    assets={LINKEDIN_MEMBER: MEMBER_CAPABILITIES, LINKEDIN_ORGANIZATION: ORGANIZATION_CAPABILITIES},
    errors=ERRORS,
    oauth=oauth_spec(),
    docs="docs/linkedin.md",
    publishing={LINKEDIN_MEMBER: MEMBER_LIMITS, LINKEDIN_ORGANIZATION: ORGANIZATION_LIMITS},
)
