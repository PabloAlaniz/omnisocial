"""Conversaciones privadas y la regla de cuándo se puede responder."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class Message:
    external_id: str
    conversation_external_id: str
    created_at: datetime | None
    sender_id: str | None
    text: str | None
    from_asset: bool
    """Lo mandó el activo (la página) y no la otra persona."""
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
