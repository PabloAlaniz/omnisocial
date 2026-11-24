"""Renovar antes de que venza: para correr desde un planificador, una vez por día o por hora.

Un token se renueva solo cuando alguien usa la conexión. Una conexión que nadie usa durante semanas vence
sin aviso, y en las redes que renuevan el mismo token (sin uno de renovación aparte) ya no hay cómo
recuperarla: la persona tiene que volver a autorizar. Esto las mantiene vivas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from omnisocial.application.ports import Clock, ConnectionRepository
from omnisocial.application.registry import ProviderRegistry
from omnisocial.application.results import Refused
from omnisocial.application.use_cases.access import GetValidToken
from omnisocial.domain.connection import Connection
from omnisocial.domain.errors import OmnisocialError

DEFAULT_WITHIN = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """Qué pasó con cada conexión que estaba por vencer. Son ids de conexión."""

    refreshed: tuple[str, ...] = ()
    lost: tuple[str, ...] = ()
    """La red rechazó la renovación: quedaron inválidas. La app ya fue avisada por el observador."""
    not_refreshable: tuple[str, ...] = ()
    """La red no permite renovarlas (o todavía no): van a vencer, y conviene avisarle a la persona."""
    errored: tuple[str, ...] = ()
    """La red no respondió o falló. Siguen como estaban: se reintentan en la próxima corrida."""


class RefreshExpiring:
    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        connections: ConnectionRepository,
        tokens: GetValidToken,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._connections = connections
        self._tokens = tokens
        self._clock = clock

    async def execute(self, *, within: timedelta = DEFAULT_WITHIN, limit: int = 100) -> RefreshReport:
        """Renueva las conexiones que vencen dentro de `within`, de la más urgente a la menos."""
        due = await self._connections.list_expiring(self._clock.now() + within, limit=limit)
        outcome: dict[str, list[str]] = {"refreshed": [], "lost": [], "not_refreshable": [], "errored": []}
        for connection in due:
            outcome[await self._refresh(connection, within)].append(connection.id)
        return RefreshReport(**{name: tuple(ids) for name, ids in outcome.items()})

    async def _refresh(self, connection: Connection, within: timedelta) -> str:
        if not self._can_refresh(connection):
            return "not_refreshable"
        try:
            result = await self._tokens.execute(connection.id, margin=within)
        except OmnisocialError:
            # Una conexión que falla no frena a las demás.
            return "errored"
        if isinstance(result, Refused):
            return "lost"
        return "refreshed" if result.connection.version != connection.version else "not_refreshable"

    def _can_refresh(self, connection: Connection) -> bool:
        if connection.provider not in self._registry:
            return False
        refresher = self._registry.get(connection.provider).refresher
        return refresher is not None and refresher.can_refresh(connection.token)
