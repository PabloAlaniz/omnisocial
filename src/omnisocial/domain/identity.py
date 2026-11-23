"""La persona que autorizó, tal como la describe la red."""

from __future__ import annotations

from dataclasses import dataclass

from omnisocial.domain.provider import ProviderId


@dataclass(frozen=True, slots=True)
class Identity:
    provider: ProviderId
    external_id: str
    name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
