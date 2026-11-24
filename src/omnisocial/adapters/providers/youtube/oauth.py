"""El login con Google para YouTube: el OAuth es el estándar; la identidad es el canal que autorizó."""

from __future__ import annotations

from dataclasses import replace

from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.providers.youtube.client import YouTubeClient, as_dict, as_list, as_str
from omnisocial.adapters.providers.youtube.config import YOUTUBE
from omnisocial.adapters.providers.youtube.spec import SPEC, oauth_spec
from omnisocial.application.ports import Clock, IdentityReader
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token


async def own_channel(client: YouTubeClient, token: Token, part: str) -> dict[str, object]:
    """El canal de quien autorizó. Google hace elegir uno al autorizar: un token es de un solo canal."""
    data = await client.get("channels", token.access_token, {"part": part, "mine": "true"})
    channels = as_list(data.get("items"))
    if not channels or not as_str(channels[0].get("id")):
        raise ProviderError(YOUTUBE, "La cuenta de Google que autorizó no tiene un canal de YouTube.")
    return channels[0]


def thumbnail(snippet: dict[str, object]) -> str | None:
    return as_str(as_dict(as_dict(snippet.get("thumbnails")).get("default")).get("url"))


class YouTubeIdentity(IdentityReader):
    def __init__(self, client: YouTubeClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        channel = await own_channel(self._client, token, "snippet")
        snippet = as_dict(channel.get("snippet"))
        return Identity(
            provider=YOUTUBE,
            external_id=str(channel["id"]),
            name=as_str(snippet.get("title")),
            avatar_url=thumbnail(snippet),
        )


def youtube_oauth(client: YouTubeClient, clock: Clock) -> StandardOAuth:
    config = client.config
    network = replace(
        SPEC,
        oauth=oauth_spec(
            authorize_url=config.authorize_url, token_url=config.token_url, revoke_url=config.revoke_url
        ),
    )
    app = OAuthApp(
        config.client_id or "",
        config.client_secret or "",
        scopes={Purpose.LOGIN: config.login_scopes, Purpose.CONNECT: config.connect_scopes},
    )
    return StandardOAuth(
        network, app, transport=client.transport, clock=clock, identity=YouTubeIdentity(client)
    )
