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
class ConnectionChange:
    """Una conexión cambió de estado: dejó de servir, o volvió a servir."""

    connection: Connection
    """Como quedó."""
    previous: ConnectionStatus

    @property
    def lost(self) -> bool:
        """Servía y ya no: venció, la red rechazó el token o se desconectó."""
        return self.previous is ConnectionStatus.ACTIVE and not self.connection.is_usable

    @property
    def recovered(self) -> bool:
        """No servía y alguien volvió a conectar."""
        return self.previous is not ConnectionStatus.ACTIVE and self.connection.is_usable


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
        """Hay redes que solo mandan el token de renovación la primera vez que la persona autoriza: si el
        token nuevo no trae uno, se conserva el que había."""
        if token.refresh_token is None and self.token.refresh_token is not None:
            token = replace(token, refresh_token=self.token.refresh_token)
        return replace(self.with_token(token, now), subject=subject)

    def mark(self, status: ConnectionStatus, reason: str, now: datetime) -> Connection:
        return replace(self, status=status, status_reason=reason, version=self.version + 1, updated_at=now)
