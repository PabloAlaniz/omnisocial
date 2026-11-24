"""Avisos que manda una red, ya traducidos."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from omnisocial.domain.messaging import Attachment, DeliveryStatus
from omnisocial.domain.provider import ProviderId


class EventKind(StrEnum):
    COMMENT = "comment"
    POST = "post"
    MESSAGE = "message"
    MENTION = "mention"
    AUTHORIZATION = "authorization"
    """La persona quitó el acceso de la app desde la red. `DELETED` deja la conexión revocada."""
    OTHER = "other"


class EventAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SocialEvent:
    provider: ProviderId
    kind: EventKind
    action: EventAction
    asset_external_id: str
    object_external_id: str | None
    occurred_at: datetime | None
    actor_id: str | None = None
    text: str | None = None
    actor_name: str | None = None
    conversation_external_id: str | None = None
    """En un mensaje, la conversación. Es lo que hay que guardar para responder."""
    attachments: tuple[Attachment, ...] = ()
    status: DeliveryStatus | None = None
    """En un aviso sobre un mensaje enviado, hasta dónde llegó."""
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)
