"""La descripción de Reddit: su OAuth, sus capacidades y qué quiere decir cada error."""

from __future__ import annotations

from omnisocial.adapters.providers.reddit.config import (
    AUTHORIZE_URL,
    REDDIT,
    REDDIT_ACCOUNT,
    REVOKE_URL,
    TOKEN_URL,
    RedditOptions,
)
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.lookup import LookupSpec
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits
from omnisocial.domain.spec import ErrorTable, NetworkSpec, OAuthSpec, Pace

ACCOUNT_CAPABILITIES = frozenset({Capability.CONTENT, Capability.COMMENTS, Capability.PUBLISHING})

ERRORS = ErrorTable(
    codes={
        # Vienen en la cabecera `WWW-Authenticate`.
        "invalid_token": ErrorKind.TOKEN_DEAD,
        "insufficient_scope": ErrorKind.MISSING_PERMISSION,
        # Los que siguen vienen en el cuerpo, con un 200. Reddit pide esperar antes de publicar de nuevo:
        # pasa con cuentas nuevas o con poco karma en esa comunidad.
        "RATELIMIT": ErrorKind.RATE_LIMITED,
        "SUBREDDIT_RATELIMIT": ErrorKind.RATE_LIMITED,
        # La sesión no vale.
        "USER_REQUIRED": ErrorKind.TOKEN_DEAD,
    },
    statuses={
        401: ErrorKind.TOKEN_DEAD,
        400: ErrorKind.INVALID_REQUEST,
    },
)
"""Un 403 sin `insufficient_scope` no es un permiso faltante: es una comunidad privada o una cuenta
vetada en ella, y reconectar no lo arregla."""

# Reddit no documenta cómo subir imágenes ni videos por la API: se publica texto o un link.
ACCOUNT_LIMITS = PublishLimits(
    max_text=40000,
    link=True,
    delete=True,
    options=RedditOptions,
    options_required=True,
)

COMMUNITIES = LookupSpec(
    "communities",
    "Las comunidades a las que la cuenta está suscripta o, con un texto, las que coinciden.",
    searchable=True,
)
FLAIRS = LookupSpec("flairs", "Las etiquetas que acepta una comunidad.", parent="communities")

PACE = Pace(max_concurrent=2, min_interval=0.6)
"""100 pedidos por minuto por app."""


def oauth_spec(
    *, authorize_url: str = AUTHORIZE_URL, token_url: str = TOKEN_URL, revoke_url: str = REVOKE_URL
) -> OAuthSpec:
    """La app se identifica por cabecera. `duration=permanent` es lo que hace que venga un token de
    renovación: el de acceso dura una hora. Sin PKCE documentado."""
    return OAuthSpec(
        authorize_url=authorize_url,
        token_url=token_url,
        revoke_url=revoke_url,
        pkce=False,
        client_auth_basic=True,
        authorize_params={"duration": "permanent"},
    )


SPEC = NetworkSpec(
    id=REDDIT,
    name="Reddit",
    capabilities=frozenset(
        {
            Capability.LOGIN,
            Capability.ASSETS,
            Capability.CONTENT,
            Capability.COMMENTS,
            Capability.PUBLISHING,
        }
    ),
    assets={REDDIT_ACCOUNT: ACCOUNT_CAPABILITIES},
    errors=ERRORS,
    oauth=oauth_spec(),
    docs="docs/reddit.md",
    publishing={REDDIT_ACCOUNT: ACCOUNT_LIMITS},
    lookups={REDDIT_ACCOUNT: (COMMUNITIES, FLAIRS)},
    pace=PACE,
)
