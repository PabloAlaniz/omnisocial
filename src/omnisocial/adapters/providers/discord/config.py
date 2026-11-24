"""Configuración de la app de Discord, y de los webhooks de canal."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

DISCORD = ProviderId("discord")
DISCORD_WEBHOOK = ProviderId("discord_webhook")

DISCORD_GUILD = "discord_guild"
"""Un servidor donde está el bot de la app y que la persona administra."""
DISCORD_WEBHOOK_CHANNEL = "discord_webhook"
"""Un webhook de canal: publica en ese canal, sin bot ni app."""

LOGIN_SCOPES: tuple[str, ...] = ("identify",)
CONNECT_SCOPES: tuple[str, ...] = ("identify", "guilds", "bot")
"""Quién es, qué servidores administra y, con `bot`, sumar el bot de la app al servidor que elija."""

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
EMBED_LINKS = 1 << 14
ATTACH_FILES = 1 << 15
PUBLISH_PERMISSIONS = VIEW_CHANNEL | SEND_MESSAGES | EMBED_LINKS | ATTACH_FILES
"""Lo que el bot necesita para publicar: ver el canal, escribir, mostrar links y adjuntar archivos."""

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
API_BASE = "https://discord.com/api/v10"
SITE = "https://discord.com"

MAX_THREAD_NAME = 100


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscordConfig:
    client_id: str
    client_secret: str = field(repr=False)
    bot_token: str = field(repr=False)
    """El token del bot de la app. Es el que publica: el de cada persona solo dice qué servidores
    administra."""
    app_url: str
    """La dirección del producto. Discord la pide en el `User-Agent` de todos los pedidos."""
    app_version: str = "1.0"
    permissions: int = PUBLISH_PERMISSIONS
    """Los permisos que se le piden al servidor para el bot."""
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    authorize_url: str = AUTHORIZE_URL
    api_base: str = API_BASE

    @property
    def user_agent(self) -> str:
        return f"DiscordBot ({self.app_url}, {self.app_version})"


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscordWebhookConfig:
    """No hay app que registrar: cada webhook se conecta con su URL."""

    app_url: str
    app_version: str = "1.0"
    api_base: str = API_BASE

    @property
    def user_agent(self) -> str:
        return f"DiscordBot ({self.app_url}, {self.app_version})"


@dataclass(frozen=True, slots=True)
class DiscordOptions(PublishOptions):
    """El bot publica en un canal del servidor: sin `channel_id` no hay publicación."""

    channel_id: str
    """Sale de la consulta `channels`."""
    mentions: bool = False
    """Si las menciones del texto (`@everyone`, roles, personas) avisan de verdad. Por defecto no."""
    silent: bool = False
    """Llega sin notificación."""
    suppress_embeds: bool = False
    """No mostrar la vista previa de los links."""
    crosspost: bool = False
    """En un canal de anuncios, mandarlo también a los servidores que lo siguen."""
    thread_name: str | None = None
    """En un canal de foro, el título de la publicación. Un foro no acepta publicaciones sin título."""
    reply_to: str | None = None
    """El id de un mensaje de ese canal al que se responde."""

    def __post_init__(self) -> None:
        if not self.channel_id.strip().isdigit():
            raise ValueError("Falta el canal donde se publica (`channel_id`).")
        if self.thread_name is not None and not 0 < len(self.thread_name) <= MAX_THREAD_NAME:
            raise ValueError(
                f"El título de una publicación de foro tiene hasta {MAX_THREAD_NAME} caracteres."
            )


@dataclass(frozen=True, slots=True)
class DiscordWebhookOptions(PublishOptions):
    username: str | None = None
    """Con qué nombre aparece esta publicación, en lugar del nombre del webhook."""
    avatar_url: str | None = None
    mentions: bool = False
    silent: bool = False
    suppress_embeds: bool = False
    thread_id: str | None = None
    """Un hilo del canal donde publicar."""
    thread_name: str | None = None
    """En un canal de foro, el título de la publicación."""
