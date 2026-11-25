"""Credenciales que entrega una red."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum

DEFAULT_REFRESH_MARGIN = timedelta(minutes=5)


class TokenKind(StrEnum):
    USER = "user"
    """De la persona que autorizó."""
    ASSET = "asset"
    """De un activo (una página, por ejemplo). Puede no vencer nunca."""
    SYSTEM = "system"
    """De un usuario de sistema de la organización. No pasa por el diálogo de autorización."""


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None
    scopes: frozenset[str] = frozenset()
    server: str | None = None
    """En una red federada, el servidor al que pertenece el token (`mastodon.social`). El adaptador le
    habla a ese servidor. `None` en las redes que tienen uno solo."""

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    def needs_refresh(self, now: datetime, margin: timedelta = DEFAULT_REFRESH_MARGIN) -> bool:
        """Vence dentro del margen: conviene renovarlo antes de usarlo."""
        return self.expires_at is not None and now + margin >= self.expires_at

    def with_scopes(self, scopes: frozenset[str]) -> Token:
        return replace(self, scopes=scopes)

    def missing_scopes(self, required: frozenset[str]) -> frozenset[str]:
        return required - self.scopes
