"""El login de Reddit: el OAuth es el estándar; la identidad sale de `/api/v1/me`."""

from __future__ import annotations

from dataclasses import replace

from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.providers.reddit.client import RedditClient, as_dict, as_str
from omnisocial.adapters.providers.reddit.config import REDDIT
from omnisocial.adapters.providers.reddit.spec import SPEC, oauth_spec
from omnisocial.application.ports import Clock, IdentityReader
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token


async def me(client: RedditClient, token: Token) -> tuple[str, str, dict[str, object]]:
    """El id, el nombre de usuario y el resto de la cuenta."""
    account = as_dict(await client.get("api/v1/me", token.access_token))
    external_id, name = as_str(account.get("id")), as_str(account.get("name"))
    if external_id is None or name is None:
        raise ProviderError(REDDIT, "Reddit no devolvió el id o el nombre de la cuenta.")
    return external_id, name, account


class RedditIdentity(IdentityReader):
    def __init__(self, client: RedditClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        external_id, name, account = await me(self._client, token)
        return Identity(
            provider=REDDIT, external_id=external_id, name=name, avatar_url=as_str(account.get("icon_img"))
        )


def reddit_oauth(client: RedditClient, clock: Clock) -> StandardOAuth:
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
        network, app, transport=client.transport, clock=clock, identity=RedditIdentity(client)
    )
