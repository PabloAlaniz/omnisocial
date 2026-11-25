"""El login de Threads.

El código se canjea por un token corto (una hora) y ese por uno largo (60 días). No hay token de
renovación: se renueva el mismo token largo, y solo mientras esté vigente y tenga más de un día. Un token
que venció no se recupera: la persona tiene que volver a autorizar. Por eso conviene correr la renovación
anticipada (`social.refresh_expiring`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from urllib.parse import urlencode

from typing_extensions import override

from omnisocial.adapters.providers.threads.client import ThreadsClient, as_dict, as_int, as_str, unwrap
from omnisocial.adapters.providers.threads.config import THREADS
from omnisocial.application.ports import Clock, OAuthClient
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token, TokenKind

PROFILE_FIELDS = "id,username,name,threads_profile_picture_url,threads_biography"
LIFETIME = timedelta(days=60)
MIN_AGE = timedelta(hours=24)
"""Un token largo no se puede renovar hasta que pasó un día desde que se emitió."""


async def own_profile(client: ThreadsClient, token: Token) -> dict[str, object]:
    profile = await client.get("me", token.access_token, {"fields": PROFILE_FIELDS})
    if not as_str(profile.get("id")):
        raise ProviderError(THREADS, "Threads no devolvió el id de la cuenta.")
    return profile


class ThreadsOAuth(OAuthClient):
    supports_pkce = False

    def __init__(self, client: ThreadsClient, clock: Clock) -> None:
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
                "client_id": self._client.config.client_id,
                "redirect_uri": redirect_uri,
                "scope": ",".join(scopes),
                "response_type": "code",
                "state": state,
            }
        )
        return f"{self._client.config.authorize_url}?{query}"

    async def _token_call(self, method: str, path: str, **fields: str) -> dict[str, object]:
        """Los endpoints de tokens no llevan la versión de la API."""
        url = f"{self._client.config.graph_url.rstrip('/')}/{path}"
        if method == "POST":
            response = await self._client.transport.request(
                "POST", url, form=fields, retry_safe="no publica nada en la cuenta"
            )
        else:
            response = await self._client.transport.request("GET", url, params=fields)
        return unwrap(response)

    def _long_lived(self, body: dict[str, object]) -> Token:
        access = as_str(body.get("access_token"))
        if not access:
            raise ProviderError(THREADS, "Threads no devolvió un token.")
        expires_in = as_int(body.get("expires_in")) or int(LIFETIME.total_seconds())
        return Token(TokenKind.USER, access, expires_at=self._clock.now() + timedelta(seconds=expires_in))

    @override
    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str | None) -> Token:
        config = self._client.config
        short = await self._token_call(
            "POST",
            "oauth/access_token",
            client_id=config.client_id,
            client_secret=config.client_secret,
            grant_type="authorization_code",
            redirect_uri=redirect_uri,
            code=code,
        )
        short_token = as_str(short.get("access_token"))
        if not short_token:
            raise ProviderError(THREADS, "Threads no devolvió un token.")
        long = await self._token_call(
            "GET",
            "access_token",
            grant_type="th_exchange_token",
            client_secret=config.client_secret,
            access_token=short_token,
        )
        return self._long_lived(long)

    @override
    async def identity(self, token: Token) -> Identity:
        profile = await own_profile(self._client, token)
        return Identity(
            provider=THREADS,
            external_id=str(profile["id"]),
            name=as_str(profile.get("name")) or as_str(profile.get("username")),
            avatar_url=as_str(profile.get("threads_profile_picture_url")),
        )

    @override
    def can_refresh(self, token: Token) -> bool:
        """Mientras esté vigente y tenga más de un día. La edad sale del vencimiento: dura 60 días."""
        if token.expires_at is None:
            return False
        now = self._clock.now()
        issued = token.expires_at - LIFETIME
        return now < token.expires_at and now - issued >= MIN_AGE

    @override
    async def refresh(self, token: Token) -> Token:
        body = await self._token_call(
            "GET", "refresh_access_token", grant_type="th_refresh_token", access_token=token.access_token
        )
        return self._long_lived(as_dict(body))

    @override
    async def revoke(self, token: Token) -> None:
        """Threads no documenta cómo revocar un token por API: la persona quita el acceso desde su cuenta."""
