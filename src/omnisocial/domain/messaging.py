"""Conversaciones privadas y la regla de cuándo se puede responder."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from omnisocial.domain.publishing import Media


class AttachmentKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    STICKER = "sticker"
    LOCATION = "location"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Attachment:
    """Algo que vino adjunto a un mensaje."""

    kind: AttachmentKind
    url: str | None = None
    media_id: str | None = None
    """El id con que se le pide el archivo a la red, cuando no manda una URL."""
    mime_type: str | None = None
    name: str | None = None


class DeliveryStatus(StrEnum):
    """Qué pasó con un mensaje enviado, cuando la red lo informa."""

    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Message:
    external_id: str
    conversation_external_id: str
    created_at: datetime | None
    sender_id: str | None
    text: str | None
    from_asset: bool
    """Lo mandó el activo (la página) y no la otra persona."""
    attachments: tuple[Attachment, ...] = ()
    status: DeliveryStatus | None = None
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)


@dataclass(frozen=True, slots=True)
class Conversation:
    external_id: str
    asset_external_id: str
    updated_at: datetime | None
    participant_ids: tuple[str, ...] = ()
    channel: str | None = None
    """Por dónde llegó, cuando la red mezcla canales (Messenger o Instagram, por ejemplo)."""
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)


def last_inbound_at(messages: Iterable[Message]) -> datetime | None:
    """El último mensaje que mandó la otra persona."""
    moments = [m.created_at for m in messages if not m.from_asset and m.created_at is not None]
    return max(moments) if moments else None


@dataclass(frozen=True, slots=True)
class ReplyWindow:
    """Cuánto tiempo después del último mensaje de la persona se le puede escribir.

    Las redes limitan los mensajes que inicia la marca. Si `duration` es `None`, la red no pone límite.
    """

    duration: timedelta | None

    def allows(self, last_inbound: datetime | None, now: datetime) -> bool:
        if self.duration is None:
            return True
        if last_inbound is None:
            return False
        return now - last_inbound <= self.duration


@dataclass(frozen=True, slots=True)
class TemplateRef:
    """Un mensaje armado de antemano y aprobado por la red (una plantilla de WhatsApp). Es la forma de
    escribirle a alguien fuera de la ventana de respuesta."""

    name: str
    language: str
    """El código de idioma con que se aprobó: `es_AR`, `en_US`."""
    components: tuple[Mapping[str, object], ...] = ()
    """Los valores de sus variables, en la forma que pide la red."""


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """Lo que se le manda a una persona: un texto, adjuntos, o una plantilla."""

    text: str = ""
    attachments: tuple[Media, ...] = ()
    template: TemplateRef | None = None
    reply_to: str | None = None
    """El id del mensaje que se cita, donde la red lo permite."""


@dataclass(frozen=True, slots=True)
class Recipient:
    """A quién se le escribe, cuando la red no deja leer la conversación para averiguarlo."""

    id: str
    last_inbound_at: datetime | None = None
    """Cuándo escribió por última vez, que es lo que abre la ventana de respuesta. Lo sabe la app, por los
    avisos que recibió. Sin este dato, una red con ventana solo acepta una plantilla."""


@dataclass(frozen=True, slots=True)
class MessagingLimits:
    """Lo que un tipo de activo acepta al mandar un mensaje."""

    max_text: int
    max_attachments: int = 0
    attachments_by_url: bool = True
    attachments_by_file: bool = False
    templates: bool = False
    history: bool = True
    """Si la red deja leer las conversaciones y sus mensajes. Si no, lo que llega se recibe por avisos, y
    para responder hay que decir a quién (`Recipient`)."""


def _template_problem(message: OutboundMessage, limits: MessagingLimits) -> str | None:
    if not limits.templates:
        return "Esta red no tiene plantillas."
    if message.text or message.attachments:
        return "Una plantilla va sola: su texto y sus adjuntos son los que se aprobaron."
    return None


def _attachment_problem(message: OutboundMessage, limits: MessagingLimits) -> str | None:
    if len(message.attachments) > limits.max_attachments:
        return f"Lleva {len(message.attachments)} adjuntos y el máximo es {limits.max_attachments}."
    for media in message.attachments:
        if not (limits.attachments_by_url if media.url is not None else limits.attachments_by_file):
            wanted = "un archivo para subir" if media.url is not None else "una URL pública"
            return f"Un adjunto tiene que ser {wanted}."
    return None


def check_message(message: OutboundMessage, limits: MessagingLimits) -> str | None:
    """Por qué ese mensaje no entra, o `None` si entra. No llama a la red."""
    if message.template is not None:
        return _template_problem(message, limits)
    if not message.text and not message.attachments:
        return "El mensaje está vacío."
    if len(message.text) > limits.max_text:
        return f"El texto tiene más de {limits.max_text} caracteres."
    return _attachment_problem(message, limits)
