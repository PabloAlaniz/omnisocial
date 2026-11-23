"""Una cuenta de una red conectada por alguien, con su token."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from omnisocial.domain.identity import Identity
from omnisocial.domain.provider import ProviderId
from omnisocial.domain.token import Token


class ConnectionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    """Venció y la red no permite renovarlo: hay que volver a conectar."""
    INVALID = "invalid"
    """La red rechazó el token: lo revocaron, cambió la contraseña o quitaron permisos."""
    REVOKED = "revoked"
    """Se desconectó a pedido."""


@dataclass(frozen=True, slots=True)
class Connection:
    """Una autorización guardada.

    `owner` es opaco para la librería: quien la usa decide qué significa (un usuario, un proyecto, un
    cliente). Dos dueños pueden conectar la misma cuenta de la red sin pisarse.

    `version` crece con cada cambio de token y permite guardar con compare-and-swap: si dos procesos
    renuevan el mismo token a la vez, solo uno gana.
    """

    id: str
    provider: ProviderId
    owner: str
    subject: Identity
    token: Token
    status: ConnectionStatus
    version: int
    created_at: datetime
    updated_at: datetime
    status_reason: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.status is ConnectionStatus.ACTIVE

    def with_token(self, token: Token, now: datetime) -> Connection:
        return replace(
            self,
            token=token,
            status=ConnectionStatus.ACTIVE,
            status_reason=None,
            version=self.version + 1,
            updated_at=now,
        )

    def reconnect(self, subject: Identity, token: Token, now: datetime) -> Connection:
        return replace(self.with_token(token, now), subject=subject)

    def mark(self, status: ConnectionStatus, reason: str, now: datetime) -> Connection:
        return replace(self, status=status, status_reason=reason, version=self.version + 1, updated_at=now)
