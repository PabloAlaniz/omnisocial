"""La descripción de Telegram: sus capacidades y qué quiere decir cada error."""

from __future__ import annotations

from omnisocial.adapters.providers.telegram.config import TELEGRAM, TELEGRAM_BOT, TelegramOptions
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.messaging import MessagingLimits, ReplyWindow
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits
from omnisocial.domain.spec import ErrorTable, NetworkSpec, Pace

BOT_CAPABILITIES = frozenset({Capability.PUBLISHING, Capability.MESSAGING, Capability.WEBHOOKS})

# Telegram no tiene códigos propios: usa el número del estado HTTP y explica en el texto.
ERRORS = ErrorTable(
    statuses={
        # El token del bot no vale: lo revocaron en @BotFather o está mal.
        401: ErrorKind.TOKEN_DEAD,
        400: ErrorKind.INVALID_REQUEST,
        # El bot no puede escribir ahí: la persona lo bloqueó, no es miembro del chat o no es
        # administrador del canal. No se arregla reconectando.
        403: ErrorKind.INVALID_REQUEST,
    },
)

MAX_CAPTION = 1024
"""Lo que entra junto a una foto o un video. Un texto más largo sale como un mensaje aparte."""

BOT_LIMITS = PublishLimits(
    max_text=4096,
    max_images=10,
    max_videos=10,
    max_media=10,
    mix_media=True,
    media_by_url=True,
    media_by_file=True,
    max_image_bytes=10 * 1024**2,
    max_video_bytes=50 * 1024**2,
    delete=True,
    options=TelegramOptions,
    options_required=True,
)

REPLY_WINDOW = ReplyWindow(None)
"""No hay ventana, pero un bot no empieza conversaciones: solo le escribe a quien ya le escribió."""

MESSAGE_LIMITS = MessagingLimits(
    max_text=4096,
    max_attachments=1,
    attachments_by_url=True,
    # No hay forma de leer los mensajes pasados: llegan por avisos.
    history=False,
)

PACE = Pace(max_concurrent=8)
"""Unos 30 mensajes por segundo en total, uno por segundo en un mismo chat y 20 por minuto en un grupo."""

SPEC = NetworkSpec(
    id=TELEGRAM,
    name="Telegram",
    capabilities=frozenset(
        {
            Capability.CREDENTIALS,
            Capability.ASSETS,
            Capability.PUBLISHING,
            Capability.MESSAGING,
            Capability.WEBHOOKS,
        }
    ),
    assets={TELEGRAM_BOT: BOT_CAPABILITIES},
    errors=ERRORS,
    docs="docs/telegram.md",
    publishing={TELEGRAM_BOT: BOT_LIMITS},
    pace=PACE,
)
