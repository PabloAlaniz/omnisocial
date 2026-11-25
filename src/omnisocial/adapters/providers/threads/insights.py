"""Métricas de la cuenta.

- `views` es una serie: un punto por día, dentro de la ventana pedida.
- `likes`, `replies`, `reposts` y `quotes` son el total de la ventana.
- `followers_count` es la cantidad de hoy: una foto, sin historia y sin ventana.
"""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.threads.client import ThreadsClient, as_dict, as_list, as_str, parse_time
from omnisocial.adapters.providers.threads.config import THREADS_ACCOUNT
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

API_VERSION = "v1.0"

FOLLOWERS = "followers_count"
WINDOWED = ("views", "likes", "replies", "reposts", "quotes")

DEFAULT_CATALOG = MetricCatalog(
    (
        CatalogEntry(THREADS_ACCOUNT, CanonicalMetric.FOLLOWERS, FOLLOWERS),
        CatalogEntry(THREADS_ACCOUNT, CanonicalMetric.VIEWS, "views"),
    )
)


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class ThreadsInsightsReader(InsightsReader):
    def __init__(self, client: ThreadsClient, clock: Clock, catalog: MetricCatalog = DEFAULT_CATALOG) -> None:
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
        """Lee las métricas pedidas que existen y saltea las demás."""
        path = f"{asset.external_id}/threads_insights"
        series: list[MetricSeries] = []
        if FOLLOWERS in metrics:
            # No acepta ventana: se pide aparte.
            data = await self._client.get(path, token.access_token, {"metric": FOLLOWERS})
            series.extend(self._series(data))
        wanted = [name for name in WINDOWED if name in metrics]
        if wanted:
            query: dict[str, str | int] = {"metric": ",".join(wanted)}
            if window.since is not None:
                query["since"] = int(window.since.timestamp())
            if window.until is not None:
                query["until"] = int(window.until.timestamp())
            series.extend(self._series(await self._client.get(path, token.access_token, query)))
        return series

    def _series(self, data: dict[str, object]) -> list[MetricSeries]:
        found: list[MetricSeries] = []
        for item in as_list(data.get("data")):
            name = as_str(item.get("name"))
            if name is None:
                continue
            total = _number(as_dict(item.get("total_value")).get("value"))
            if total is not None:
                found.append(MetricSeries(name, Period.LIFETIME, (MetricPoint(self._clock.now(), total),)))
                continue
            points = tuple(
                MetricPoint(parse_time(value.get("end_time")), number)
                for value in as_list(item.get("values"))
                if (number := _number(value.get("value"))) is not None
            )
            if points:
                found.append(MetricSeries(name, Period.DAY, points))
        return found
