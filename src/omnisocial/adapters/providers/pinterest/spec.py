"""La descripción de Pinterest: su OAuth, sus capacidades y qué quiere decir cada error."""

from __future__ import annotations

from datetime import date

from omnisocial.adapters.providers.pinterest.config import (
    API_BASE,
    AUTHORIZE_URL,
    PINTEREST,
    PINTEREST_ACCOUNT,
    PinterestOptions,
)
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.lookup import LookupSpec
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits
from omnisocial.domain.spec import ApiPin, ErrorTable, NetworkSpec, OAuthSpec, Pace

ACCOUNT_CAPABILITIES = frozenset({Capability.CONTENT, Capability.INSIGHTS, Capability.PUBLISHING})

ERRORS = ErrorTable(
    statuses={
        # El token venció, es inválido o lo revocaron (código 2).
        401: ErrorKind.TOKEN_DEAD,
        # Al token le falta un permiso, o la app no tiene el nivel de acceso que hace falta.
        403: ErrorKind.MISSING_PERMISSION,
        400: ErrorKind.INVALID_REQUEST,
    },
)

# La descripción es el texto de la publicación. El título, el link y el tablero van en las opciones.
ACCOUNT_LIMITS = PublishLimits(
    max_text=800,
    max_images=5,
    max_videos=1,
    media_required=True,
    media_by_url=True,
    media_by_file=True,
    # Un video se sube: Pinterest no lo va a buscar a una URL.
    video_by_url=False,
    delete=True,
    options=PinterestOptions,
    options_required=True,
)

BOARDS = LookupSpec("boards", "Los tableros de la cuenta. Un pin siempre va a uno.")
BOARD_SECTIONS = LookupSpec("board_sections", "Las secciones de un tablero.", parent="boards")

PACE = Pace(max_concurrent=4)
"""Con acceso estándar son 100 escrituras por minuto por persona; con acceso de prueba, 300 por día."""


def oauth_spec(*, authorize_url: str = AUTHORIZE_URL, api_base: str = API_BASE) -> OAuthSpec:
    """La app se identifica por cabecera, los permisos van separados por comas y cada renovación trae un
    token de renovación nuevo. Sin PKCE documentado, y sin revocación para tokens de personas."""
    return OAuthSpec(
        authorize_url=authorize_url,
        token_url=f"{api_base}/oauth/token",
        scope_separator=",",
        pkce=False,
        client_auth_basic=True,
        refresh_rotates=True,
    )


SPEC = NetworkSpec(
    id=PINTEREST,
    name="Pinterest",
    capabilities=frozenset(
        {
            Capability.LOGIN,
            Capability.ASSETS,
            Capability.CONTENT,
            Capability.INSIGHTS,
            Capability.PUBLISHING,
        }
    ),
    assets={PINTEREST_ACCOUNT: ACCOUNT_CAPABILITIES},
    errors=ERRORS,
    oauth=oauth_spec(),
    docs="docs/pinterest.md",
    api=ApiPin(
        "v5", reviewed=date(2026, 11, 24), changelog="https://developers.pinterest.com/docs/changelog/"
    ),
    publishing={PINTEREST_ACCOUNT: ACCOUNT_LIMITS},
    lookups={PINTEREST_ACCOUNT: (BOARDS, BOARD_SECTIONS)},
    pace=PACE,
)
