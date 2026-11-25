"""Discord con el bot de la app: login, servidores, canales y publicar.

La persona autoriza y, en el mismo paso, suma el bot a un servidor que administra. Después publica el
bot, con su propio token: el de la persona solo dice qué servidores administra.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.discord.client import (
    DiscordClient,
    Look,
    as_dict,
    as_int,
    as_list,
    as_str,
    message,
)
from omnisocial.adapters.providers.discord.config import (
    DISCORD,
    DISCORD_GUILD,
    SITE,
    DiscordConfig,
    DiscordOptions,
)
from omnisocial.adapters.providers.discord.spec import CHANNELS, GUILD_CAPABILITIES, SPEC, oauth_spec
from omnisocial.application.ports import (
    AssetDirectory,
    Clock,
    IdentityReader,
    IdGenerator,
    LookupReader,
    Publisher,
)
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ErrorKind, NotPublished, OmnisocialError, ProviderError, TokenRejected
from omnisocial.domain.identity import Identity
from omnisocial.domain.lookup import Choice
from omnisocial.domain.publishing import Draft, Outcome, PublicationStatus
from omnisocial.domain.token import Token

_CLIENT_ERROR = 400
_SERVER_ERROR = 500
_ADMINISTRATOR = 1 << 3
_MANAGE_GUILD = 1 << 5
_PAGE = 200
_MAX_PAGES = 10
_MAX_NONCE = 25
_CHANNEL_TYPES = {0: "text", 5: "announcement", 15: "forum"}
# Errores que ya dicen por qué no salió: el núcleo los traduce a su propia negativa.
_SAYS_WHY = frozenset({ErrorKind.MISSING_PERMISSION, ErrorKind.RATE_LIMITED, ErrorKind.INVALID_REQUEST})


def message_url(guild_id: str | None, channel_id: str, message_id: str) -> str | None:
    """La dirección de un mensaje, como la arma la app de Discord."""
    return f"{SITE}/channels/{guild_id}/{channel_id}/{message_id}" if guild_id else None


class DiscordBot:
    """Lo que se hace con el token del bot. Si Discord lo rechaza, el problema es de la configuración de
    la app y no de la conexión de nadie: no se informa como un token muerto."""

    def __init__(self, client: DiscordClient, config: DiscordConfig) -> None:
        self.client = client
        self._authorization = f"Bot {config.bot_token}"

    @property
    def authorization(self) -> str:
        return self._authorization

    def failure(self, response: HttpResponse) -> OmnisocialError:
        error = self.client.error(response)
        if isinstance(error, TokenRejected):
            return ProviderError(
                DISCORD, "Discord rechazó el token del bot de la app.", status=response.status
            )
        return error

    async def get(self, path: str, params: Mapping[str, str | int] | None = None) -> object:
        response = await self.client.request("GET", path, authorization=self._authorization, params=params)
        if response.status >= _CLIENT_ERROR:
            raise self.failure(response)
        return response.data

    async def guild_ids(self) -> set[str]:
        """Los servidores donde está el bot."""
        found: set[str] = set()
        after: str | None = None
        for _ in range(_MAX_PAGES):
            params: dict[str, str | int] = {"limit": _PAGE, **({"after": after} if after else {})}
            page = [
                g
                for g in (
                    as_str(item.get("id")) for item in as_list(await self.get("users/@me/guilds", params))
                )
                if g
            ]
            found.update(page)
            if len(page) < _PAGE:
                break
            after = page[-1]
        return found


class DiscordIdentity(IdentityReader):
    def __init__(self, client: DiscordClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        response = await self._client.request(
            "GET", "users/@me", authorization=f"Bearer {token.access_token}"
        )
        user = as_dict(self._client.unwrap(response))
        user_id = as_str(user.get("id"))
        if user_id is None:
            raise ProviderError(DISCORD, "Discord no devolvió el id de la persona.")
        avatar = as_str(user.get("avatar"))
        return Identity(
            provider=DISCORD,
            external_id=user_id,
            name=as_str(user.get("global_name")) or as_str(user.get("username")),
            email=as_str(user.get("email")),
            avatar_url=f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png" if avatar else None,
        )


def discord_oauth(client: DiscordClient, config: DiscordConfig, clock: Clock) -> StandardOAuth:
    network = replace(
        SPEC,
        oauth=oauth_spec(
            authorize_url=config.authorize_url, api_base=config.api_base, permissions=config.permissions
        ),
    )
    app = OAuthApp(
        config.client_id,
        config.client_secret,
        scopes={Purpose.LOGIN: config.login_scopes, Purpose.CONNECT: config.connect_scopes},
    )
    return StandardOAuth(
        network, app, transport=client.transport, clock=clock, identity=DiscordIdentity(client)
    )


def _channel_kind(channel: Mapping[str, object]) -> str | None:
    """`text`, `announcement` o `forum`; `None` si en ese tipo de canal no se publica. El tipo de un
    canal de texto es 0."""
    number = as_int(channel.get("type"))
    return _CHANNEL_TYPES.get(number) if number is not None else None


def _manages(guild: Mapping[str, object]) -> bool:
    try:
        permissions = int(str(guild.get("permissions") or 0))
    except ValueError:
        permissions = 0
    return guild.get("owner") is True or bool(permissions & (_ADMINISTRATOR | _MANAGE_GUILD))


class DiscordAssetDirectory(AssetDirectory):
    def __init__(self, bot: DiscordBot) -> None:
        self._bot = bot

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        """Los servidores que la persona administra y donde además está el bot."""
        client = self._bot.client
        response = await client.request(
            "GET", "users/@me/guilds", authorization=f"Bearer {token.access_token}", params={"limit": _PAGE}
        )
        mine = [guild for guild in as_list(client.unwrap(response)) if _manages(guild)]
        if not mine:
            return []
        with_bot = await self._bot.guild_ids()
        return [
            DiscoveredAsset(
                DISCORD_GUILD, guild_id, name=as_str(guild.get("name")), capabilities=GUILD_CAPABILITIES
            )
            for guild in mine
            if (guild_id := as_str(guild.get("id"))) is not None and guild_id in with_bot
        ]


class DiscordLookups(LookupReader):
    def __init__(self, bot: DiscordBot) -> None:
        self._bot = bot

    @override
    async def choices(
        self, asset: Asset, token: Token, *, lookup: str, query: str | None, parent: str | None
    ) -> Sequence[Choice]:
        """Los canales de texto, de anuncios y de foro que el bot ve, en el orden del servidor."""
        if lookup != CHANNELS.name:
            return []
        channels = as_list(await self._bot.get(f"guilds/{asset.external_id}/channels"))
        channels.sort(key=lambda channel: as_int(channel.get("position")) or 0)
        return [
            Choice(
                channel_id,
                f"#{as_str(channel.get('name')) or channel_id}",
                data={"type": kind, **({"nsfw": "true"} if channel.get("nsfw") is True else {})},
            )
            for channel in channels
            if (kind := _channel_kind(channel)) is not None
            and (channel_id := as_str(channel.get("id"))) is not None
        ]


class DiscordPublisher(Publisher):
    def __init__(self, bot: DiscordBot, ids: IdGenerator) -> None:
        self._bot = bot
        self._ids = ids

    def _not_published(self, error: OmnisocialError, status: int | None = None) -> OmnisocialError:
        if isinstance(error, ProviderError) and error.kind in _SAYS_WHY:
            return error
        return NotPublished(DISCORD, str(error), status=status)

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options
        if not isinstance(options, DiscordOptions):
            raise ProviderError(
                DISCORD, "El bot publica en un canal: faltan las opciones.", kind=ErrorKind.INVALID_REQUEST
            )
        look = Look(options.mentions, options.silent, options.suppress_embeds)
        body, files = await message(draft.text, draft.media, look)
        if options.reply_to:
            body["message_reference"] = {"message_id": options.reply_to}
        channel = options.channel_id.strip()
        payload: dict[str, object]
        if options.thread_name is not None:
            path, payload = f"channels/{channel}/threads", {"name": options.thread_name, "message": body}
        else:
            # Con el nonce, si el pedido se repite Discord devuelve el mensaje que ya creó.
            nonce = self._ids.new_id().replace("-", "")[:_MAX_NONCE]
            path, payload = f"channels/{channel}/messages", {**body, "nonce": nonce, "enforce_nonce": True}
        response = await self._bot.client.send(
            path,
            payload,
            files,
            authorization=self._bot.authorization,
            retry_safe=None if options.thread_name is not None else "lleva un nonce: Discord no lo repite",
        )
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            # Un 4xx es un rechazo: Discord no creó nada.
            raise self._not_published(self._bot.failure(response), response.status)
        if response.status >= _SERVER_ERROR:
            raise self._bot.failure(response)
        created = as_dict(response.data)
        # En un foro la respuesta es el hilo, con su primer mensaje adentro.
        posted = as_dict(created.get("message")) if options.thread_name is not None else created
        message_id = as_str(posted.get("id"))
        channel_id = as_str(posted.get("channel_id")) or as_str(created.get("id")) or channel
        if message_id is None:
            raise ProviderError(DISCORD, "Discord creó el mensaje pero no devolvió su id.")
        outcome = Outcome(
            PublicationStatus.PUBLISHED,
            post_id=f"{channel_id}:{message_id}",
            url=message_url(asset.external_id, channel_id, message_id),
        )
        return await self._crosspost(outcome, channel_id, message_id) if options.crosspost else outcome

    async def _crosspost(self, outcome: Outcome, channel_id: str, message_id: str) -> Outcome:
        """Ya salió en el canal. Si mandarlo a los servidores que lo siguen falla, no es un fracaso."""
        try:
            response = await self._bot.client.request(
                "POST",
                f"channels/{channel_id}/messages/{message_id}/crosspost",
                authorization=self._bot.authorization,
            )
            if response.status >= _CLIENT_ERROR:
                raise self._bot.failure(response)
        except (ProviderError, TransportError) as error:
            return replace(
                outcome,
                status=PublicationStatus.PUBLISHED_WITH_ERROR,
                error=f"No se mandó a los servidores que siguen el canal: {error}",
            )
        return outcome

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        raise ProviderError(DISCORD, "Discord publica en una sola etapa: no hay nada para retomar.")

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        channel_id, _, message_id = post_id.partition(":")
        response = await self._bot.client.request(
            "DELETE", f"channels/{channel_id}/messages/{message_id}", authorization=self._bot.authorization
        )
        if response.status >= _CLIENT_ERROR:
            raise self._bot.failure(response)
