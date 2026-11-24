"""El login de Pinterest: el OAuth es el estándar; la identidad sale de la cuenta."""

from __future__ import annotations

from dataclasses import replace

from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.providers.pinterest.client import PinterestClient, as_str
from omnisocial.adapters.providers.pinterest.config import PINTEREST
from omnisocial.adapters.providers.pinterest.spec import SPEC, oauth_spec
from omnisocial.application.ports import Clock, IdentityReader
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token


class PinterestIdentity(IdentityReader):
    def __init__(self, client: PinterestClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        account = await self._client.get("user_account", token.access_token)
        external_id = as_str(account.get("id"))
        if external_id is None:
            raise ProviderError(PINTEREST, "Pinterest no devolvió el id de la cuenta.")
        return Identity(
            provider=PINTEREST,
            external_id=external_id,
            name=as_str(account.get("business_name")) or as_str(account.get("username")),
            avatar_url=as_str(account.get("profile_image")),
        )


def pinterest_oauth(client: PinterestClient, clock: Clock) -> StandardOAuth:
    config = client.config
    network = replace(SPEC, oauth=oauth_spec(authorize_url=config.authorize_url, api_base=config.api_base))
    app = OAuthApp(
        config.client_id,
        config.client_secret,
        scopes={Purpose.LOGIN: config.login_scopes, Purpose.CONNECT: config.connect_scopes},
    )
    return StandardOAuth(
        network, app, transport=client.transport, clock=clock, identity=PinterestIdentity(client)
    )
