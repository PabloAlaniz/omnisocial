"""La descripción de TikTok: su OAuth, sus capacidades y qué quiere decir cada código de error."""

from __future__ import annotations

from omnisocial.adapters.providers.tiktok.config import API_BASE, AUTHORIZE_URL, TIKTOK, TIKTOK_ACCOUNT
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.spec import ErrorTable, NetworkSpec, OAuthSpec

ACCOUNT_CAPABILITIES = frozenset({Capability.CONTENT, Capability.INSIGHTS})

ERRORS = ErrorTable(
    codes={
        # El token venció, lo revocaron o no existe.
        "access_token_invalid": ErrorKind.TOKEN_DEAD,
        # El token no tiene el permiso para ese endpoint o esos campos.
        "scope_not_authorized": ErrorKind.MISSING_PERMISSION,
        "scope_permission_missed": ErrorKind.MISSING_PERMISSION,
        "rate_limit_exceeded": ErrorKind.RATE_LIMITED,
        "invalid_params": ErrorKind.INVALID_REQUEST,
        "internal_error": ErrorKind.TRANSIENT,
    }
)


def oauth_spec(*, authorize_url: str = AUTHORIZE_URL, api_base: str = API_BASE) -> OAuthSpec:
    """El Login Kit. En web el canje va del servidor con el secreto de la app; PKCE es para apps móviles
    y de escritorio."""
    return OAuthSpec(
        authorize_url=authorize_url,
        token_url=f"{api_base}/oauth/token/",
        revoke_url=f"{api_base}/oauth/revoke/",
        scope_separator=",",
        pkce=False,
        client_id_param="client_key",
        refresh_rotates=True,
    )


SPEC = NetworkSpec(
    id=TIKTOK,
    name="TikTok",
    capabilities=frozenset(
        {
            Capability.LOGIN,
            Capability.ASSETS,
            Capability.CONTENT,
            Capability.INSIGHTS,
            Capability.WEBHOOKS,
        }
    ),
    assets={TIKTOK_ACCOUNT: ACCOUNT_CAPABILITIES},
    errors=ERRORS,
    oauth=oauth_spec(),
    docs="docs/tiktok.md",
)
