"""Login Kit de TikTok: el OAuth es el estándar; lo propio es cómo se lee la identidad."""

from __future__ import annotations

from dataclasses import replace

from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.providers.tiktok.client import TikTokClient, as_dict, as_str
from omnisocial.adapters.providers.tiktok.config import TIKTOK
from omnisocial.adapters.providers.tiktok.spec import SPEC, oauth_spec
from omnisocial.application.ports import Clock, IdentityReader
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token

IDENTITY_FIELDS = ("open_id", "union_id", "display_name", "avatar_url")


class TikTokIdentity(IdentityReader):
    def __init__(self, client: TikTokClient) -> None:
        self._client = client

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


def tiktok_oauth(client: TikTokClient, clock: Clock) -> StandardOAuth:
    config = client.config
    network = replace(SPEC, oauth=oauth_spec(authorize_url=config.authorize_url, api_base=config.api_base))
    app = OAuthApp(
        config.client_key,
        config.client_secret,
        scopes={Purpose.LOGIN: config.login_scopes, Purpose.CONNECT: config.connect_scopes},
    )
    return StandardOAuth(
        network, app, transport=client.transport, clock=clock, identity=TikTokIdentity(client)
    )
