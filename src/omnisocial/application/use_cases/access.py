"""Conseguir un token que sirva, renovándolo si hace falta."""

from __future__ import annotations

from omnisocial.application.ports import AssetRepository, Clock, ConnectionRepository
from omnisocial.application.registry import ProviderRegistry
from omnisocial.application.results import AssetAccess, Refusal, Refused, ValidToken
from omnisocial.domain.connection import Connection, ConnectionStatus
from omnisocial.domain.errors import TokenRejected

_REFUSAL_BY_STATUS = {
    ConnectionStatus.EXPIRED: Refusal.CONNECTION_EXPIRED,
    ConnectionStatus.INVALID: Refusal.CONNECTION_INVALID,
    ConnectionStatus.REVOKED: Refusal.CONNECTION_REVOKED,
}

_MAX_ATTEMPTS = 3


def _refused(connection: Connection) -> Refused:
    return Refused(_REFUSAL_BY_STATUS[connection.status], detail=connection.status_reason)


class GetValidToken:
    """Devuelve el token de una conexión listo para usar.

    Si está por vencer y la red permite renovarlo, lo renueva y lo guarda con compare-and-swap: cuando dos
    procesos renuevan a la vez, el que pierde relee y usa el token que guardó el otro. Si la red rechaza
    el token, la conexión queda marcada como inválida y no se vuelve a intentar.
    """

    def __init__(
        self, *, registry: ProviderRegistry, connections: ConnectionRepository, clock: Clock
    ) -> None:
        self._registry = registry
        self._connections = connections
        self._clock = clock

    async def execute(self, connection_id: str) -> ValidToken | Refused:
        for _ in range(_MAX_ATTEMPTS):
            connection = await self._connections.get(connection_id)
            if connection is None:
                return Refused(Refusal.NOT_FOUND)
            if not connection.is_usable:
                return _refused(connection)
            updated = await self._renewed(connection)
            if updated is None:
                return ValidToken(connection, connection.token)
            if await self._connections.save(updated, expected_version=connection.version):
                return ValidToken(updated, updated.token) if updated.is_usable else _refused(updated)
            # Otro proceso la cambió primero: se relee y se decide de nuevo.
        return Refused(Refusal.NOT_FOUND, detail="la conexión cambia demasiado rápido")  # pragma: no cover

    async def _renewed(self, connection: Connection) -> Connection | None:
        """La conexión con el token renovado, o marcada si ya no sirve. `None` si el token actual sirve."""
        now = self._clock.now()
        token = connection.token
        if not token.needs_refresh(now):
            return None
        oauth = self._registry.get(connection.provider).oauth
        if oauth is None or not oauth.can_refresh(token):
            return (
                connection.mark(ConnectionStatus.EXPIRED, "el token venció", now)
                if token.is_expired(now)
                else None
            )
        try:
            fresh = await oauth.refresh(token)
        except TokenRejected as error:
            return connection.mark(ConnectionStatus.INVALID, str(error), now)
        return connection.with_token(fresh, now)


class ResolveAssetAccess:
    """El activo y el token con el que se le habla: el propio del activo o, si no tiene, el de la conexión."""

    def __init__(self, *, assets: AssetRepository, tokens: GetValidToken, clock: Clock) -> None:
        self._assets = assets
        self._tokens = tokens
        self._clock = clock

    async def execute(self, asset_id: str) -> AssetAccess | Refused:
        asset = await self._assets.get(asset_id)
        if asset is None:
            return Refused(Refusal.NOT_FOUND)
        valid = await self._tokens.execute(asset.connection_id)
        if isinstance(valid, Refused):
            return valid
        own = asset.token
        if own is not None and not own.is_expired(self._clock.now()):
            return AssetAccess(asset, own)
        return AssetAccess(asset, valid.token)
