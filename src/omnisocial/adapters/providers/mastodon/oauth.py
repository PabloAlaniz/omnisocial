"""OAuth en Mastodon y en Pixelfed: una app por servidor.

La primera vez que alguien de un servidor quiere conectar, la librería registra ahí una app y guarda su
clave y su secreto. Las personas siguientes de ese servidor usan la misma.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from urllib.parse import urlencode

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.mastodon.client import MastodonClient, as_dict, as_int, as_str
from omnisocial.adapters.providers.mastodon.config import MastodonConfig
from omnisocial.application.ports import Clock, IdentityReader, ServerAppStore, ServerOAuth
from omnisocial.domain.authorization import Purpose, ServerApp
from omnisocial.domain.errors import ProviderError, TokenRejected
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token, TokenKind

_GRANT_DEAD = "invalid_grant"
_CLIENT_ERROR = 400


class MastodonOAuth(ServerOAuth):
    def __init__(
        self, client: MastodonClient, config: MastodonConfig, apps: ServerAppStore, clock: Clock
    ) -> None:
        self._client = client
        self._config = config
        self._apps = apps
        self._clock = clock

    @property
    @override
    def supports_pkce(self) -> bool:
        return self._client.flavor.pkce

    @override
    def default_scopes(self, purpose: Purpose) -> tuple[str, ...]:
        return self._config.login_scopes if purpose is Purpose.LOGIN else self._config.connect_scopes

    # ── La app de cada servidor ─────────────────────────────────────────────────────────────────

    async def _post(self, server: str, path: str, form: Mapping[str, str]) -> HttpResponse:
        return await self._client.transport.request(
            "POST", self._client.url(server, path), form=form, retry_safe="no publica nada en la cuenta"
        )

    async def _register(self, server: str, redirect_uri: str) -> ServerApp:
        form = {
            "client_name": self._config.client_name,
            "redirect_uris": redirect_uri,
            "scopes": " ".join(self._config.app_scopes),
        }
        if self._config.website:
            form["website"] = self._config.website
        body = self._client.unwrap(await self._post(server, "api/v1/apps", form))
        client_id, client_secret = as_str(body.get("client_id")), as_str(body.get("client_secret"))
        if not client_id or not client_secret:
            name = self._client.flavor.name
            raise ProviderError(self._client.flavor.provider, f"{server} no registró la app de {name}.")
        return ServerApp(self._client.flavor.provider, server, redirect_uri, client_id, client_secret)

    async def _app(self, server: str, redirect_uri: str) -> ServerApp:
        """La app de ese servidor: la guardada, o una recién registrada."""
        stored = await self._apps.get(self._client.flavor.provider, server)
        if stored is None:
            return await self._apps.add(await self._register(server, redirect_uri))
        if stored.redirect_uri != redirect_uri:
            # La app quedó atada a la URL de retorno anterior: hace falta otra.
            fresh = await self._register(server, redirect_uri)
            await self._apps.replace(fresh)
            return fresh
        return stored

    async def _stored(self, server: str) -> ServerApp:
        stored = await self._apps.get(self._client.flavor.provider, server)
        if stored is None:
            raise ProviderError(self._client.flavor.provider, f"No hay una app registrada en {server}.")
        return stored

    # ── El flujo ────────────────────────────────────────────────────────────────────────────────

    @override
    async def authorization_url(
        self, server: str, *, state: str, redirect_uri: str, scopes: Sequence[str], code_challenge: str | None
    ) -> str:
        app = await self._app(server, redirect_uri)
        query = {
            "response_type": "code",
            "client_id": app.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
        }
        if self.supports_pkce and code_challenge is not None:
            query |= {"code_challenge": code_challenge, "code_challenge_method": "S256"}
        return f"{self._client.url(server, 'oauth/authorize')}?{urlencode(query)}"

    def _token(self, response: HttpResponse, server: str, previous: Token | None = None) -> Token:
        body = as_dict(response.data)
        if as_str(body.get("error")) == _GRANT_DEAD:
            message = as_str(body.get("error_description")) or _GRANT_DEAD
            raise TokenRejected(self._client.flavor.provider, f"{server} rechazó la credencial: {message}")
        granted = self._client.unwrap(response)
        access = as_str(granted.get("access_token"))
        if access is None:
            raise ProviderError(self._client.flavor.provider, f"{server} no devolvió un token.")
        expires_in = as_int(granted.get("expires_in"))
        scopes = frozenset((as_str(granted.get("scope")) or "").split())
        return Token(
            TokenKind.USER,
            access,
            # Un token de Mastodon no vence ni se renueva; uno de Pixelfed, sí.
            refresh_token=as_str(granted.get("refresh_token"))
            or (previous.refresh_token if previous else None),
            expires_at=self._clock.now() + timedelta(seconds=expires_in) if expires_in else None,
            scopes=scopes or (previous.scopes if previous else frozenset()),
            server=server,
        )

    @override
    async def exchange_code(
        self, server: str, *, code: str, redirect_uri: str, code_verifier: str | None
    ) -> Token:
        app = await self._stored(server)
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": app.client_id,
            "client_secret": app.client_secret,
            "redirect_uri": redirect_uri,
        }
        if code_verifier is not None and self.supports_pkce:
            form["code_verifier"] = code_verifier
        return self._token(await self._post(server, "oauth/token", form), server)

    @override
    def can_refresh(self, token: Token) -> bool:
        return token.refresh_token is not None and token.server is not None

    @override
    async def refresh(self, token: Token) -> Token:
        if token.refresh_token is None or token.server is None:
            raise ProviderError(self._client.flavor.provider, "El token no tiene cómo renovarse.")
        app = await self._stored(token.server)
        form = {
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
            "client_id": app.client_id,
            "client_secret": app.client_secret,
        }
        return self._token(await self._post(token.server, "oauth/token", form), token.server, token)

    @override
    async def revoke(self, token: Token) -> None:
        if token.server is None:
            return
        app = await self._stored(token.server)
        form = {"client_id": app.client_id, "client_secret": app.client_secret, "token": token.access_token}
        response = await self._post(token.server, "oauth/revoke", form)
        if response.status >= _CLIENT_ERROR:
            raise self._client.error(response)


async def own_account(client: MastodonClient, token: Token) -> dict[str, object]:
    account = await client.get("api/v1/accounts/verify_credentials", token)
    if not as_str(account.get("id")):
        raise ProviderError(client.flavor.provider, "El servidor no devolvió el id de la cuenta.")
    return account


class MastodonIdentity(IdentityReader):
    def __init__(self, client: MastodonClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        """El id de una cuenta vale solo en su servidor: la identidad lleva los dos."""
        account = await own_account(self._client, token)
        return Identity(
            provider=self._client.flavor.provider,
            external_id=f"{account['id']}@{self._client.server_of(token)}",
            name=as_str(account.get("display_name")) or as_str(account.get("username")),
            avatar_url=as_str(account.get("avatar")),
        )
