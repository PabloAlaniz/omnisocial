"""Contadores de la cuenta (`public_metrics`). Son una foto del momento, sin historia."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.x.client import XClient, as_dict, as_int
from omnisocial.adapters.providers.x.config import X_ACCOUNT
from omnisocial.adapters.providers.x.oauth import own_account
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

STATS = ("followers_count", "following_count", "tweet_count", "listed_count")

DEFAULT_CATALOG = MetricCatalog((CatalogEntry(X_ACCOUNT, CanonicalMetric.FOLLOWERS, "followers_count"),))


def post_count(metrics: dict[str, object]) -> int | None:
    """Según la versión de la respuesta, la cantidad de posts viene como `tweet_count` o `post_count`."""
    count = as_int(metrics.get("tweet_count"))
    return count if count is not None else as_int(metrics.get("post_count"))


class XInsightsReader(InsightsReader):
    def __init__(self, client: XClient, clock: Clock, catalog: MetricCatalog = DEFAULT_CATALOG) -> None:
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
        account = await own_account(self._client, token)
        public = as_dict(account.get("public_metrics"))
        values = {**{name: as_int(public.get(name)) for name in STATS}, "tweet_count": post_count(public)}
        now = self._clock.now()
        return [
            MetricSeries(name, Period.LIFETIME, (MetricPoint(now, float(value)),))
            for name in wanted
            if (value := values[name]) is not None
        ]
