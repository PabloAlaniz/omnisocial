"""Avisos que manda una red, ya traducidos."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from omnisocial.domain.provider import ProviderId


class EventKind(StrEnum):
    COMMENT = "comment"
    POST = "post"
    MESSAGE = "message"
    MENTION = "mention"
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
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)
