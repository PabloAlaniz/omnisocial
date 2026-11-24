"""Conectar un bot con su token.

El token lo da @BotFather al crear el bot. No vence y no se renueva: deja de valer cuando alguien lo
revoca ahí mismo. A diferencia de otras credenciales, el token es lo que se guarda (cifrado): es lo único
que hay.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from typing_extensions import override

from omnisocial.adapters.providers.telegram.client import TOKEN, TelegramClient, as_int, as_str
from omnisocial.adapters.providers.telegram.config import TELEGRAM, TELEGRAM_BOT
from omnisocial.adapters.providers.telegram.spec import BOT_CAPABILITIES
from omnisocial.application.ports import AssetDirectory, CredentialLogin, IdentityReader
from omnisocial.domain.asset import DiscoveredAsset
from omnisocial.domain.authorization import CredentialField
from omnisocial.domain.errors import ProviderError, TokenRejected
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token, TokenKind

FIELDS = (CredentialField("token", secret=True),)


async def bot(client: TelegramClient, token: Token) -> tuple[str, str | None, str | None]:
    """El id, el nombre de usuario y el nombre visible del bot."""
    me = await client.get(token.access_token, "getMe")
    bot_id = as_int(me.get("id"))
    if bot_id is None:
        raise ProviderError(TELEGRAM, "Telegram no devolvió el id del bot.")
    return str(bot_id), as_str(me.get("username")), as_str(me.get("first_name"))


class TelegramSession(CredentialLogin):
    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    @property
    @override
    def fields(self) -> Sequence[CredentialField]:
        return FIELDS

    @override
    async def login(self, credentials: Mapping[str, str]) -> Token:
        given = credentials["token"].strip()
        if not TOKEN.fullmatch(given):
            raise TokenRejected(TELEGRAM, "Eso no tiene la forma de un token de bot de Telegram.")
        token = Token(TokenKind.USER, given)
        # Si el token no vale, Telegram lo dice acá y no se guarda nada.
        await bot(self._client, token)
        return token

    @override
    def can_refresh(self, token: Token) -> bool:
        return False

    @override
    async def refresh(self, token: Token) -> Token:
        raise ProviderError(TELEGRAM, "El token de un bot no se renueva.")

    @override
    async def revoke(self, token: Token) -> None:
        """No hay cómo revocarlo desde acá: se revoca en @BotFather. Desconectar lo borra de este lado."""


class TelegramIdentity(IdentityReader):
    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        bot_id, username, name = await bot(self._client, token)
        return Identity(provider=TELEGRAM, external_id=bot_id, name=username or name)


class TelegramAssetDirectory(AssetDirectory):
    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        """El bot. Telegram no dice en qué chats está: el chat se indica al publicar."""
        bot_id, username, name = await bot(self._client, token)
        return [
            DiscoveredAsset(
                TELEGRAM_BOT,
                bot_id,
                name=f"@{username}" if username else name,
                capabilities=BOT_CAPABILITIES,
                metadata={"username": username} if username else {},
            )
        ]
