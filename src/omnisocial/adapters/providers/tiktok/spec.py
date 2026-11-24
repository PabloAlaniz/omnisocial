"""La descripción de TikTok: su OAuth, sus capacidades y qué quiere decir cada código de error."""

from __future__ import annotations

from datetime import date

from omnisocial.adapters.providers.tiktok.config import (
    API_BASE,
    AUTHORIZE_URL,
    TIKTOK,
    TIKTOK_ACCOUNT,
    TikTokOptions,
)
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits, TextCount
from omnisocial.domain.spec import ApiPin, ErrorTable, NetworkSpec, OAuthSpec

ACCOUNT_CAPABILITIES = frozenset({Capability.CONTENT, Capability.INSIGHTS, Capability.PUBLISHING})

ERRORS = ErrorTable(
    codes={
        # El token venció, lo revocaron o no existe.
        "access_token_invalid": ErrorKind.TOKEN_DEAD,
        # El token no tiene el permiso para ese endpoint o esos campos.
        "scope_not_authorized": ErrorKind.MISSING_PERMISSION,
        "scope_permission_missed": ErrorKind.MISSING_PERMISSION,
        "rate_limit_exceeded": ErrorKind.RATE_LIMITED,
        "invalid_param": ErrorKind.INVALID_REQUEST,
        "internal_error": ErrorKind.TRANSIENT,
        # Al publicar. La cuenta publicó demasiado en poco tiempo: se resuelve esperando.
        "spam_risk_too_many_posts": ErrorKind.RATE_LIMITED,
        "spam_risk_too_many_pending_share": ErrorKind.RATE_LIMITED,
        # La app llegó a su tope diario de cuentas que publican.
        "reached_active_user_cap": ErrorKind.QUOTA_EXHAUSTED,
        # Lo que se pidió no se puede publicar así: repetirlo igual da lo mismo.
        "unaudited_client_can_only_post_to_private_accounts": ErrorKind.INVALID_REQUEST,
        "url_ownership_unverified": ErrorKind.INVALID_REQUEST,
        "privacy_level_option_mismatch": ErrorKind.INVALID_REQUEST,
    }
)


# Un video, o hasta 35 fotos. El texto de un video admite 2200 unidades UTF-16.
ACCOUNT_LIMITS = PublishLimits(
    max_text=2200,
    text_count=TextCount.UTF16,
    max_images=35,
    max_videos=1,
    media_required=True,
    options=TikTokOptions,
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
            Capability.PUBLISHING,
        }
    ),
    assets={TIKTOK_ACCOUNT: ACCOUNT_CAPABILITIES},
    errors=ERRORS,
    oauth=oauth_spec(),
    docs="docs/tiktok.md",
    api=ApiPin("v2", reviewed=date(2026, 11, 24), changelog="https://developers.tiktok.com/doc/changelog"),
    publishing={TIKTOK_ACCOUNT: ACCOUNT_LIMITS},
)
