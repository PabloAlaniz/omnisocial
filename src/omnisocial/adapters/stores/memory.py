"""Almacenes en memoria. Para tests y para probar sin base; no sobreviven a un reinicio."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from typing_extensions import override

from omnisocial.application.ports import AssetRepository, AuthorizationStateStore, Clock, ConnectionRepository
from omnisocial.domain.asset import Asset
from omnisocial.domain.authorization import AuthorizationRequest
from omnisocial.domain.connection import Connection
from omnisocial.domain.provider import ProviderId


class InMemoryConnectionRepository(ConnectionRepository):
    def __init__(self) -> None:
        self._items: dict[str, Connection] = {}

    @override
    async def get(self, connection_id: str) -> Connection | None:
        return self._items.get(connection_id)

    @override
    async def find(self, *, owner: str, provider: ProviderId, subject_id: str) -> Connection | None:
        return next(
            (
                c
                for c in self._items.values()
                if c.owner == owner and c.provider == provider and c.subject.external_id == subject_id
            ),
            None,
        )

    @override
    async def list_by_owner(self, owner: str) -> Sequence[Connection]:
        return [c for c in self._items.values() if c.owner == owner]

    @override
    async def add(self, connection: Connection) -> None:
        if connection.id in self._items:
            raise ValueError(f"La conexión {connection.id} ya existe.")
        self._items[connection.id] = connection

    @override
    async def save(self, connection: Connection, *, expected_version: int) -> bool:
        current = self._items.get(connection.id)
        if current is None or current.version != expected_version:
            return False
        self._items[connection.id] = connection
        return True


class InMemoryAssetRepository(AssetRepository):
    def __init__(self) -> None:
        self._items: dict[str, Asset] = {}

    @override
    async def get(self, asset_id: str) -> Asset | None:
        return self._items.get(asset_id)

    @override
    async def list_by_owner(self, owner: str, *, provider: ProviderId | None = None) -> Sequence[Asset]:
        return [
            a
            for a in self._items.values()
            if a.owner == owner and (provider is None or a.provider == provider)
        ]

    @override
    async def list_by_connection(self, connection_id: str) -> Sequence[Asset]:
        return [a for a in self._items.values() if a.connection_id == connection_id]

    @override
    async def find_by_external_id(self, provider: ProviderId, external_id: str) -> Sequence[Asset]:
        return [a for a in self._items.values() if a.provider == provider and a.external_id == external_id]

    @override
    async def replace_for_connection(self, connection_id: str, assets: Sequence[Asset]) -> None:
        known = {(a.kind, a.external_id): a.id for a in await self.list_by_connection(connection_id)}
        for asset_id in [a.id for a in await self.list_by_connection(connection_id)]:
            del self._items[asset_id]
        for asset in assets:
            kept = known.get((asset.kind, asset.external_id), asset.id)
            self._items[kept] = replace(asset, id=kept, connection_id=connection_id)


class InMemoryAuthorizationStateStore(AuthorizationStateStore):
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._items: dict[str, AuthorizationRequest] = {}

    @override
    async def put(self, request: AuthorizationRequest) -> None:
        now = self._clock.now()
        self._items = {k: v for k, v in self._items.items() if not v.is_expired(now)}
        self._items[request.state] = request

    @override
    async def take(self, state: str) -> AuthorizationRequest | None:
        return self._items.pop(state, None)
