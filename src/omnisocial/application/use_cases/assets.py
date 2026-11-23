"""Listar y volver a descubrir los activos de una conexión."""

from __future__ import annotations

from collections.abc import Sequence

from omnisocial.application.ports import AssetRepository, IdGenerator
from omnisocial.application.registry import ProviderRegistry
from omnisocial.application.results import Done, Refused
from omnisocial.application.use_cases.access import GetValidToken
from omnisocial.application.use_cases.authorization import AssetSync
from omnisocial.domain.asset import Asset
from omnisocial.domain.provider import ProviderId


class SyncAssets:
    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        tokens: GetValidToken,
        assets: AssetRepository,
        ids: IdGenerator,
    ) -> None:
        self._registry = registry
        self._tokens = tokens
        self._sync = AssetSync(assets=assets, ids=ids)

    async def execute(self, connection_id: str) -> Done[Sequence[Asset]] | Refused:
        valid = await self._tokens.execute(connection_id)
        if isinstance(valid, Refused):
            return valid
        provider = self._registry.get(valid.connection.provider)
        return Done(await self._sync.sync(provider, valid.connection))


class ListAssets:
    def __init__(self, *, assets: AssetRepository) -> None:
        self._assets = assets

    async def execute(self, owner: str, *, provider: str | None = None) -> Sequence[Asset]:
        return await self._assets.list_by_owner(
            owner, provider=ProviderId(provider) if provider is not None else None
        )
