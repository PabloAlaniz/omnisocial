"""El login de LinkedIn: el OAuth es el estándar; la identidad sale de OpenID Connect."""

from __future__ import annotations

from dataclasses import replace

from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.providers.linkedin.client import LinkedInClient, as_str
from omnisocial.adapters.providers.linkedin.config import LINKEDIN
from omnisocial.adapters.providers.linkedin.spec import SPEC, oauth_spec
from omnisocial.application.ports import Clock, IdentityReader
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token


class LinkedInIdentity(IdentityReader):
    def __init__(self, client: LinkedInClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        """`sub` es el id de la persona para esta app: con otra app, la misma persona tiene otro."""
        info = await self._client.userinfo(token.access_token)
        external_id = as_str(info.get("sub"))
        if external_id is None:
            raise ProviderError(LINKEDIN, "LinkedIn no devolvió el id de la persona.")
        return Identity(
            provider=LINKEDIN,
            external_id=external_id,
            name=as_str(info.get("name")),
            email=as_str(info.get("email")),
            avatar_url=as_str(info.get("picture")),
        )


def linkedin_oauth(client: LinkedInClient, clock: Clock) -> StandardOAuth:
    config = client.config
    network = replace(SPEC, oauth=oauth_spec(authorize_url=config.authorize_url, token_url=config.token_url))
    app = OAuthApp(
        config.client_id,
        config.client_secret,
        scopes={Purpose.LOGIN: config.login_scopes, Purpose.CONNECT: config.connect_scopes},
    )
    return StandardOAuth(
        network, app, transport=client.transport, clock=clock, identity=LinkedInIdentity(client)
    )
