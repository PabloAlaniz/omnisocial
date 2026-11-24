"""Almacenes en memoria. Para tests y para probar sin base; no sobreviven a un reinicio."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime

from typing_extensions import override

from omnisocial.application.ports import (
    AssetRepository,
    AuthorizationStateStore,
    Clock,
    ConnectionRepository,
    PublicationRepository,
    QuotaLedger,
    RateLimitStore,
    ServerAppStore,
)
from omnisocial.domain.asset import Asset
from omnisocial.domain.authorization import AuthorizationRequest, ServerApp
from omnisocial.domain.connection import Connection
from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import Publication


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
    async def list_expiring(self, before: datetime, *, limit: int) -> Sequence[Connection]:
        due = [
            c
            for c in self._items.values()
            if c.is_usable and c.token.expires_at is not None and c.token.expires_at <= before
        ]
        return sorted(due, key=lambda c: (c.token.expires_at, c.id))[:limit]

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


class InMemoryPublicationRepository(PublicationRepository):
    def __init__(self) -> None:
        self._items: dict[str, Publication] = {}

    @override
    async def get(self, publication_id: str) -> Publication | None:
        return self._items.get(publication_id)

    @override
    async def find_by_key(self, asset_id: str, idempotency_key: str) -> Publication | None:
        return next(
            (
                p
                for p in self._items.values()
                if p.asset_id == asset_id and p.idempotency_key == idempotency_key
            ),
            None,
        )

    @override
    async def add(self, publication: Publication) -> bool:
        key = publication.idempotency_key
        if key is not None and await self.find_by_key(publication.asset_id, key) is not None:
            return False
        self._items[publication.id] = publication
        return True

    @override
    async def save(self, publication: Publication, *, expected_version: int) -> bool:
        current = self._items.get(publication.id)
        if current is None or current.version != expected_version:
            return False
        self._items[publication.id] = publication
        return True

    @override
    async def remove(self, publication_id: str) -> None:
        self._items.pop(publication_id, None)


class InMemoryQuotaLedger(QuotaLedger):
    def __init__(self) -> None:
        self._used: dict[tuple[str, str], int] = {}

    @override
    async def spend(self, key: str, period: str, units: int, *, limit: int) -> bool:
        total = self._used.get((key, period), 0) + units
        if total > limit:
            return False
        self._used[key, period] = total
        return True

    @override
    async def spent(self, key: str, period: str) -> int:
        return self._used.get((key, period), 0)


class InMemoryRateLimitStore(RateLimitStore):
    """Los turnos, dentro de un proceso. Entre procesos hace falta un almacén compartido."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._next: dict[str, float] = {}

    @override
    async def reserve(self, key: str, interval: float) -> float:
        now = self._now()
        turn = max(self._next.get(key, now), now)
        self._next[key] = turn + interval
        return turn - now

    @override
    async def pause(self, key: str, seconds: float) -> None:
        self._next[key] = max(self._next.get(key, 0.0), self._now() + seconds)


class InMemoryServerAppStore(ServerAppStore):
    def __init__(self) -> None:
        self._apps: dict[tuple[ProviderId, str], ServerApp] = {}

    @override
    async def get(self, provider: ProviderId, server: str) -> ServerApp | None:
        return self._apps.get((provider, server))

    @override
    async def add(self, app: ServerApp) -> ServerApp:
        return self._apps.setdefault((app.provider, app.server), app)

    @override
    async def replace(self, app: ServerApp) -> None:
        self._apps[app.provider, app.server] = app
