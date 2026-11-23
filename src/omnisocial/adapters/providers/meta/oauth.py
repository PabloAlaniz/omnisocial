"""Facebook Login: autorizar, canjear el código, identidad y revocación."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

from typing_extensions import override

from omnisocial.adapters.providers.meta.config import META
from omnisocial.adapters.providers.meta.graph import (
    GraphClient,
    as_dict,
    as_int,
    as_list,
    as_str,
    parse_time,
)
from omnisocial.application.ports import Clock, OAuthClient
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token, TokenKind


@dataclass(frozen=True, slots=True)
class TokenInfo:
    """Lo que Meta dice de un token (`/debug_token`)."""

    is_valid: bool
    type: str | None
    app_id: str | None
    user_id: str | None
    expires_at: datetime | None
    data_access_expires_at: datetime | None
    scopes: frozenset[str]


def _expiry(value: object) -> datetime | None:
    # `0` quiere decir que no vence.
    return parse_time(value) if as_int(value) else None


class MetaOAuth(OAuthClient):
    supports_pkce = False
    """El canje del código va del servidor con el secreto de la app."""

    def __init__(self, graph: GraphClient, clock: Clock) -> None:
        self._graph = graph
        self._clock = clock

    @override
    def default_scopes(self, purpose: Purpose) -> tuple[str, ...]:
        config = self._graph.config
        return config.login_scopes if purpose is Purpose.LOGIN else config.connect_scopes

    @override
    def authorization_url(
        self, *, state: str, redirect_uri: str, scopes: Sequence[str], code_challenge: str | None
    ) -> str:
        config = self._graph.config
        query = urlencode(
            {
                "client_id": config.app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": ",".join(scopes),
                "response_type": "code",
            }
        )
        return f"{config.dialog_url.rstrip('/')}/{config.api_version}/dialog/oauth?{query}"

    @override
    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str | None) -> Token:
        """Canjea el código y estira el token de usuario al de larga duración (unos 60 días).

        Los tokens de página que se obtienen con un token de larga duración no vencen.
        """
        config = self._graph.config
        short = await self._graph.get_app(
            "oauth/access_token",
            {
                "client_id": config.app_id,
                "client_secret": config.app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        short_token = as_str(short.get("access_token"))
        if not short_token:
            raise ProviderError(META, "Meta no devolvió un token al canjear el código.")
        long = await self._graph.get_app(
            "oauth/access_token",
            {
                "grant_type": "fb_exchange_token",
                "client_id": config.app_id,
                "client_secret": config.app_secret,
                "fb_exchange_token": short_token,
            },
        )
        access = as_str(long.get("access_token")) or short_token
        expires_in = (
            as_int(long.get("expires_in")) if "access_token" in long else as_int(short.get("expires_in"))
        )
        expires_at = self._clock.now() + timedelta(seconds=expires_in) if expires_in else None
        token = Token(TokenKind.USER, access, expires_at=expires_at)
        return token.with_scopes(await self.granted_scopes(token))

    async def granted_scopes(self, token: Token) -> frozenset[str]:
        body = await self._graph.get("me/permissions", token.access_token)
        return frozenset(
            name
            for item in as_list(body.get("data"))
            if (name := as_str(item.get("permission"))) and item.get("status") == "granted"
        )

    @override
    async def identity(self, token: Token) -> Identity:
        body = await self._graph.get(
            "me", token.access_token, {"fields": "id,name,email,picture.type(large)"}
        )
        external_id = as_str(body.get("id"))
        if not external_id:
            raise ProviderError(META, "Meta no devolvió el id de la persona.")
        return Identity(
            provider=META,
            external_id=external_id,
            name=as_str(body.get("name")),
            email=as_str(body.get("email")),
            avatar_url=as_str(as_dict(as_dict(body.get("picture")).get("data")).get("url")),
        )

    @override
    def can_refresh(self, token: Token) -> bool:
        # Meta no renueva tokens de usuario sin la persona: al vencer, hay que volver a conectar.
        return False

    @override
    async def refresh(self, token: Token) -> Token:
        raise ProviderError(META, "Meta no permite renovar tokens sin que la persona vuelva a autorizar.")

    @override
    async def revoke(self, token: Token) -> None:
        await self._graph.delete("me/permissions", token.access_token)

    async def debug_token(self, token: Token) -> TokenInfo:
        """Valida un token contra la app: tipo, vencimiento y permisos concedidos."""
        body = await self._graph.get_app(
            "debug_token",
            {"input_token": token.access_token, "access_token": self._graph.config.app_access_token},
        )
        data = as_dict(body.get("data"))
        scopes = data.get("scopes")
        return TokenInfo(
            is_valid=data.get("is_valid") is True,
            type=as_str(data.get("type")),
            app_id=as_str(data.get("app_id")),
            user_id=as_str(data.get("user_id")),
            expires_at=_expiry(data.get("expires_at")),
            data_access_expires_at=_expiry(data.get("data_access_expires_at")),
            scopes=frozenset(s for s in scopes if isinstance(s, str))
            if isinstance(scopes, list)
            else frozenset(),
        )
