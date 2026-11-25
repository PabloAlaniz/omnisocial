"""Configuración para los bots de Telegram."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

TELEGRAM = ProviderId("telegram")

TELEGRAM_BOT = "telegram_bot"
"""Un bot. Publica en los canales y grupos donde lo sumaron, y conversa con quien le escribió."""

API_BASE = "https://api.telegram.org"


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramConfig:
    """No hay app que registrar: cada bot se conecta con el token que da @BotFather."""

    webhook_secret: str | None = field(default=None, repr=False)
    """Un secreto propio, largo y al azar. De él sale el que Telegram manda en cada aviso, distinto para
    cada bot. Sin él no se reciben avisos."""
    api_base: str = API_BASE


@dataclass(frozen=True, slots=True)
class TelegramOptions(PublishOptions):
    """Un bot no publica "en su cuenta": publica en un chat. Sin `chat_id` no hay publicación."""

    chat_id: str
    """`@nombredelcanal`, o el id numérico del canal o del grupo (`-1001234567890`)."""
    parse_mode: str | None = None
    """`HTML` o `MarkdownV2`, si el texto trae formato."""
    silent: bool = False
    """Llega sin sonido."""
    protect: bool = False
    """No se puede reenviar ni guardar."""
    disable_preview: bool = False
    thread_id: int | None = None
    """El tema, en un grupo con temas."""

    def __post_init__(self) -> None:
        if not self.chat_id.strip():
            raise ValueError("Falta el chat donde se publica (`chat_id`).")
