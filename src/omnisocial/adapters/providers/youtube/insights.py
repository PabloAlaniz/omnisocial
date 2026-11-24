"""Contadores del canal (`statistics`).

Son una foto del momento: para tener la evolución de suscriptores, la app guarda una lectura por día. Las
series históricas están en otra API (YouTube Analytics), que todavía no se usa.
"""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.youtube.client import YouTubeClient, as_dict, as_int
from omnisocial.adapters.providers.youtube.config import YOUTUBE_CHANNEL
from omnisocial.adapters.providers.youtube.oauth import own_channel
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

API_VERSION = "v3"

STATS = ("subscriberCount", "viewCount", "videoCount")
"""`subscriberCount` viene redondeado a tres cifras, y no viene si el canal lo oculta."""

DEFAULT_CATALOG = MetricCatalog(
    (
        CatalogEntry(YOUTUBE_CHANNEL, CanonicalMetric.FOLLOWERS, "subscriberCount"),
        CatalogEntry(YOUTUBE_CHANNEL, CanonicalMetric.VIEWS, "viewCount"),
    )
)


class YouTubeInsightsReader(InsightsReader):
    def __init__(self, client: YouTubeClient, clock: Clock, catalog: MetricCatalog = DEFAULT_CATALOG) -> None:
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
        channel = await own_channel(self._client, token, "statistics")
        statistics = as_dict(channel.get("statistics"))
        now = self._clock.now()
        return [
            MetricSeries(name, Period.LIFETIME, (MetricPoint(now, float(value)),))
            for name in wanted
            if (value := as_int(statistics.get(name))) is not None
        ]
