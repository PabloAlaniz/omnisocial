"""Contadores de la cuenta (`user.info.stats`).

La Display API no tiene series históricas: cada lectura es una foto del momento. Para tener la evolución de
seguidores, la app guarda una lectura por día.
"""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.tiktok.client import TikTokClient, as_dict, as_int
from omnisocial.adapters.providers.tiktok.config import TIKTOK_ACCOUNT
from omnisocial.application.ports import Clock, InsightsReader
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

API_VERSION = "v2"

STATS = ("follower_count", "following_count", "likes_count", "video_count")
"""`likes_count` son los likes que recibió la cuenta en total, no los que dio."""

DEFAULT_CATALOG = MetricCatalog((CatalogEntry(TIKTOK_ACCOUNT, CanonicalMetric.FOLLOWERS, "follower_count"),))


class TikTokInsightsReader(InsightsReader):
    def __init__(self, client: TikTokClient, clock: Clock, catalog: MetricCatalog = DEFAULT_CATALOG) -> None:
        self._client = client
        self._clock = clock
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
        data = await self._client.get("user/info", token.access_token, fields=wanted)
        user = as_dict(data.get("user"))
        now = self._clock.now()
        return [
            MetricSeries(name, Period.LIFETIME, (MetricPoint(now, float(value)),))
            for name in wanted
            if (value := as_int(user.get(name))) is not None
        ]
