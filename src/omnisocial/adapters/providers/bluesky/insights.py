"""Contadores de la cuenta. Son una foto del momento, sin historia."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.bluesky.client import BlueskyClient, as_int
from omnisocial.adapters.providers.bluesky.config import BLUESKY_ACCOUNT
from omnisocial.application.ports import InsightsReader
from omnisocial.domain.asset import Asset
from omnisocial.domain.metrics import (
    CanonicalMetric,
    CatalogEntry,
    MetricCatalog,
    MetricPoint,
    MetricSeries,
    Period,
)
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

API_VERSION = "v1"

STATS = ("followersCount", "followsCount", "postsCount")

DEFAULT_CATALOG = MetricCatalog((CatalogEntry(BLUESKY_ACCOUNT, CanonicalMetric.FOLLOWERS, "followersCount"),))


class BlueskyInsightsReader(InsightsReader):
    def __init__(self, client: BlueskyClient, catalog: MetricCatalog = DEFAULT_CATALOG) -> None:
        self._client = client
        self._catalog = catalog

    @property
    @override
    def catalog(self) -> MetricCatalog:
        return self._catalog

    @property
    @override
    def api_version(self) -> str:
        return API_VERSION

    @override
    async def read(
        self, asset: Asset, token: Token, *, metrics: Sequence[str], period: Period, window: TimeWindow
    ) -> Sequence[MetricSeries]:
        """Lee los contadores pedidos que existen y saltea los demás. `period` y `window` no aplican."""
        wanted = [name for name in STATS if name in metrics]
        if not wanted:
            return []
        profile = await self._client.get("app.bsky.actor.getProfile", token, {"actor": asset.external_id})
        now = self._client.clock.now()
        return [
            MetricSeries(name, Period.LIFETIME, (MetricPoint(now, float(value)),))
            for name in wanted
            if (value := as_int(profile.get(name))) is not None
        ]
