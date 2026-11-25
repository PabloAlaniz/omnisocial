"""Discord por webhook de canal: sin app y sin bot.

Quien administra un canal crea un webhook (Editar canal → Integraciones → Webhooks) y pega su URL. Con
eso alcanza para publicar en ese canal. La URL es el secreto: quien la tiene, publica.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from typing_extensions import override

from omnisocial.adapters.providers.discord.bot import message_url
from omnisocial.adapters.providers.discord.client import DiscordClient, Look, as_dict, as_str, message
from omnisocial.adapters.providers.discord.config import (
    DISCORD_WEBHOOK,
    DISCORD_WEBHOOK_CHANNEL,
    DiscordWebhookOptions,
)
from omnisocial.adapters.providers.discord.spec import WEBHOOK_CAPABILITIES
from omnisocial.application.ports import (
    AssetDirectory,
    CredentialLogin,
    IdentityReader,
    Publisher,
)
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.authorization import CredentialField
from omnisocial.domain.errors import ErrorKind, NotPublished, OmnisocialError, ProviderError, TokenRejected
from omnisocial.domain.identity import Identity
from omnisocial.domain.publishing import Draft, Outcome, PublicationStatus
from omnisocial.domain.token import Token, TokenKind

FIELDS = (CredentialField("webhook_url", secret=True),)
_URL = re.compile(
    r"https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/(?:v\d+/)?webhooks/(\d+)/([A-Za-z0-9_-]+)/?"
)
_KEY = re.compile(r"\d+/[A-Za-z0-9_-]+")
_CLIENT_ERROR = 400
_SERVER_ERROR = 500
_SAYS_WHY = frozenset({ErrorKind.MISSING_PERMISSION, ErrorKind.RATE_LIMITED, ErrorKind.INVALID_REQUEST})


def _path(token: Token) -> str:
    """La ruta del webhook. Lo guardado es `id/clave`: la URL se arma siempre contra la API de Discord."""
    if not _KEY.fullmatch(token.access_token):
        raise TokenRejected(DISCORD_WEBHOOK, "Eso no es un webhook de Discord.")
    return f"webhooks/{token.access_token}"


async def _webhook(client: DiscordClient, token: Token) -> dict[str, object]:
    response = await client.request("GET", _path(token))
    webhook = as_dict(client.unwrap(response))
    if as_str(webhook.get("id")) is None:
        raise ProviderError(DISCORD_WEBHOOK, "Discord no devolvió el webhook.")
    return webhook


class DiscordWebhookSession(CredentialLogin):
    def __init__(self, client: DiscordClient) -> None:
        self._client = client

    @property
    @override
    def fields(self) -> Sequence[CredentialField]:
        return FIELDS

    @override
    async def login(self, credentials: Mapping[str, str]) -> Token:
        """Solo se acepta una URL de webhook de Discord: de ella se toman el id y la clave, y a dónde se
        hacen los pedidos lo decide la configuración, no lo que pegó la persona."""
        found = _URL.fullmatch(credentials["webhook_url"].strip())
        if found is None:
            raise TokenRejected(DISCORD_WEBHOOK, "Eso no es la URL de un webhook de Discord.")
        token = Token(TokenKind.USER, f"{found.group(1)}/{found.group(2)}")
        # Si lo borraron o la clave no vale, Discord lo dice acá y no se guarda nada.
        await _webhook(self._client, token)
        return token

    @override
    def can_refresh(self, token: Token) -> bool:
        return False

    @override
    async def refresh(self, token: Token) -> Token:
        raise ProviderError(DISCORD_WEBHOOK, "Un webhook no se renueva.")

    @override
    async def revoke(self, token: Token) -> None:
        """Desconectar no borra el webhook del canal: eso lo decide quien lo creó."""


class DiscordWebhookIdentity(IdentityReader):
    def __init__(self, client: DiscordClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        webhook = await _webhook(self._client, token)
        return Identity(
            provider=DISCORD_WEBHOOK, external_id=str(webhook["id"]), name=as_str(webhook.get("name"))
        )


class DiscordWebhookAssets(AssetDirectory):
    def __init__(self, client: DiscordClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        webhook = await _webhook(self._client, token)
        fields = {
            "channel_id": as_str(webhook.get("channel_id")),
            "guild_id": as_str(webhook.get("guild_id")),
        }
        return [
            DiscoveredAsset(
                DISCORD_WEBHOOK_CHANNEL,
                str(webhook["id"]),
                name=as_str(webhook.get("name")),
                parent_external_id=fields["guild_id"],
                capabilities=WEBHOOK_CAPABILITIES,
                metadata={key: value for key, value in fields.items() if value},
            )
        ]


class DiscordWebhookPublisher(Publisher):
    def __init__(self, client: DiscordClient) -> None:
        self._client = client

    @staticmethod
    def _not_published(error: OmnisocialError, status: int | None = None) -> OmnisocialError:
        if isinstance(error, TokenRejected) or (isinstance(error, ProviderError) and error.kind in _SAYS_WHY):
            return error
        return NotPublished(DISCORD_WEBHOOK, str(error), status=status)

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = (
            draft.options if isinstance(draft.options, DiscordWebhookOptions) else DiscordWebhookOptions()
        )
        body, files = await message(
            draft.text, draft.media, Look(options.mentions, options.silent, options.suppress_embeds)
        )
        extras = {
            "username": options.username,
            "avatar_url": options.avatar_url,
            "thread_name": options.thread_name,
        }
        body.update({name: value for name, value in extras.items() if value})
        # Sin `wait`, Discord no devuelve el mensaje y no habría id con que borrarlo.
        params: dict[str, str | int] = {"wait": "true"}
        if options.thread_id:
            params["thread_id"] = options.thread_id
        response = await self._client.send(_path(token), body, files, params=params)
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            # Un 4xx es un rechazo: Discord no creó nada.
            raise self._not_published(self._client.error(response), response.status)
        created = as_dict(self._client.unwrap(response))
        message_id = as_str(created.get("id"))
        if message_id is None:
            raise ProviderError(DISCORD_WEBHOOK, "Discord creó el mensaje pero no devolvió su id.")
        channel_id = as_str(created.get("channel_id")) or asset.metadata.get("channel_id") or ""
        return Outcome(
            PublicationStatus.PUBLISHED,
            post_id=message_id,
            url=message_url(asset.parent_external_id, channel_id, message_id) if channel_id else None,
        )

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        raise ProviderError(DISCORD_WEBHOOK, "Discord publica en una sola etapa: no hay nada para retomar.")

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        """Un webhook solo puede borrar lo que publicó él."""
        response = await self._client.request("DELETE", f"{_path(token)}/messages/{post_id}")
        self._client.unwrap(response)
