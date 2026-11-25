"""El login con Google: el OAuth es el estándar; la identidad sale de OpenID Connect."""

from __future__ import annotations

from dataclasses import replace

from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.providers.google_business.client import GoogleBusinessClient, as_str
from omnisocial.adapters.providers.google_business.config import GOOGLE_BUSINESS
from omnisocial.adapters.providers.google_business.spec import SPEC, oauth_spec
from omnisocial.application.ports import Clock, IdentityReader
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token


class GoogleBusinessIdentity(IdentityReader):
    def __init__(self, client: GoogleBusinessClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        info = await self._client.get(self._client.config.userinfo_url, token.access_token)
        external_id = as_str(info.get("sub"))
        if external_id is None:
            raise ProviderError(GOOGLE_BUSINESS, "Google no devolvió el id de la persona.")
        return Identity(
            provider=GOOGLE_BUSINESS,
            external_id=external_id,
            name=as_str(info.get("name")),
            email=as_str(info.get("email")),
            avatar_url=as_str(info.get("picture")),
        )


def google_business_oauth(client: GoogleBusinessClient, clock: Clock) -> StandardOAuth:
    config = client.config
    network = replace(
        SPEC,
        oauth=oauth_spec(
            authorize_url=config.authorize_url, token_url=config.token_url, revoke_url=config.revoke_url
        ),
    )
    app = OAuthApp(
        config.client_id,
        config.client_secret,
        scopes={Purpose.LOGIN: config.login_scopes, Purpose.CONNECT: config.connect_scopes},
    )
    return StandardOAuth(
        network, app, transport=client.transport, clock=clock, identity=GoogleBusinessIdentity(client)
    )
