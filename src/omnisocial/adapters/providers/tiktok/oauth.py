"""Login Kit de TikTok: autorizar, canjear el código, renovar e identidad."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from urllib.parse import urlencode

from typing_extensions import override

from omnisocial.adapters.providers.tiktok.client import TikTokClient, as_dict, as_int, as_str
from omnisocial.adapters.providers.tiktok.config import TIKTOK
from omnisocial.application.ports import Clock, OAuthClient
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token, TokenKind

IDENTITY_FIELDS = ("open_id", "union_id", "display_name", "avatar_url")


class TikTokOAuth(OAuthClient):
    supports_pkce = False
    """En web el canje va del servidor con el secreto de la app; PKCE es para apps móviles y de escritorio."""

    def __init__(self, client: TikTokClient, clock: Clock) -> None:
        self._client = client
        self._clock = clock

    @override
    def default_scopes(self, purpose: Purpose) -> tuple[str, ...]:
        config = self._client.config
        return config.login_scopes if purpose is Purpose.LOGIN else config.connect_scopes

    @override
    def authorization_url(
        self, *, state: str, redirect_uri: str, scopes: Sequence[str], code_challenge: str | None
    ) -> str:
        query = urlencode(
            {
                "client_key": self._client.config.client_key,
                "scope": ",".join(scopes),
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"{self._client.config.authorize_url}?{query}"

    def _token(self, body: dict[str, object]) -> Token:
        access = as_str(body.get("access_token"))
        if not access:
            raise ProviderError(TIKTOK, "TikTok no devolvió un token.")
        expires_in = as_int(body.get("expires_in"))
        scopes = as_str(body.get("scope")) or ""
        return Token(
            TokenKind.USER,
            access,
            refresh_token=as_str(body.get("refresh_token")),
            expires_at=self._clock.now() + timedelta(seconds=expires_in) if expires_in else None,
            scopes=frozenset(s for s in scopes.split(",") if s),
        )

    @override
    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str | None) -> Token:
        body = await self._client.oauth(
            "oauth/token",
            {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri},
        )
        return self._token(body)

    @override
    async def identity(self, token: Token) -> Identity:
        data = await self._client.get("user/info", token.access_token, fields=IDENTITY_FIELDS)
        user = as_dict(data.get("user"))
        external_id = as_str(user.get("open_id"))
        if not external_id:
            raise ProviderError(TIKTOK, "TikTok no devolvió el open_id de la persona.")
        return Identity(
            provider=TIKTOK,
            external_id=external_id,
            name=as_str(user.get("display_name")),
            avatar_url=as_str(user.get("avatar_url")),
        )

    @override
    def can_refresh(self, token: Token) -> bool:
        return token.refresh_token is not None

    @override
    async def refresh(self, token: Token) -> Token:
        """El refresh token rota: la respuesta trae uno nuevo y el anterior deja de servir.

        Quien llama tiene que guardar el token devuelto entero (lo hace `GetValidToken`, con compare-and-swap,
        así dos procesos no renuevan con el mismo refresh token).
        """
        if token.refresh_token is None:
            raise ProviderError(TIKTOK, "El token no tiene refresh token.")
        body = await self._client.oauth(
            "oauth/token", {"grant_type": "refresh_token", "refresh_token": token.refresh_token}
        )
        return self._token(body)

    @override
    async def revoke(self, token: Token) -> None:
        await self._client.oauth("oauth/revoke", {"token": token.access_token})
