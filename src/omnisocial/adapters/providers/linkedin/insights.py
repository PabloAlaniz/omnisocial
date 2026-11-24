"""Métricas de una página de empresa: seguidores y estadísticas de sus publicaciones.

- `firstDegreeSize` es la cantidad de seguidores de hoy: una foto, sin historia.
- Las demás son de las publicaciones de la página. Sin ventana, el total de los últimos 12 meses; con
  ventana y período diario, un punto por día. LinkedIn no guarda más de 12 meses.
"""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.linkedin.client import (
    LinkedInClient,
    as_dict,
    as_list,
    encode,
    from_millis,
)
from omnisocial.adapters.providers.linkedin.config import LINKEDIN_ORGANIZATION, urn
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

FOLLOWERS = "firstDegreeSize"
SHARE_STATS = (
    "impressionCount",
    "uniqueImpressionsCount",
    "clickCount",
    "likeCount",
    "commentCount",
    "shareCount",
    "engagement",
)
"""`engagement` es una tasa (interacciones sobre impresiones), no una cantidad."""

DEFAULT_CATALOG = MetricCatalog(
    (
        CatalogEntry(LINKEDIN_ORGANIZATION, CanonicalMetric.FOLLOWERS, FOLLOWERS),
        CatalogEntry(LINKEDIN_ORGANIZATION, CanonicalMetric.IMPRESSIONS, "impressionCount"),
        CatalogEntry(LINKEDIN_ORGANIZATION, CanonicalMetric.REACH, "uniqueImpressionsCount"),
    )
)


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _millis(window: TimeWindow) -> tuple[int, int] | None:
    if window.since is None or window.until is None:
        return None
    return int(window.since.timestamp() * 1000), int(window.until.timestamp() * 1000)


class LinkedInInsightsReader(InsightsReader):
    def __init__(
        self, client: LinkedInClient, clock: Clock, catalog: MetricCatalog = DEFAULT_CATALOG
    ) -> None:
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
        return self._client.config.api_version

    @override
    async def read(
        self, asset: Asset, token: Token, *, metrics: Sequence[str], period: Period, window: TimeWindow
    ) -> Sequence[MetricSeries]:
        """Lee las métricas pedidas que existen y saltea las demás."""
        organization = encode(urn(asset.kind, asset.external_id))
        series: list[MetricSeries] = []
        if FOLLOWERS in metrics:
            series.extend(await self._followers(organization, token))
        wanted = [name for name in SHARE_STATS if name in metrics]
        if wanted:
            span = _millis(window) if period is Period.DAY else None
            series.extend(await self._share_stats(organization, token, wanted, span))
        return series

    async def _followers(self, organization: str, token: Token) -> list[MetricSeries]:
        data = await self._client.get(
            f"networkSizes/{organization}?edgeType=COMPANY_FOLLOWED_BY_MEMBER", token.access_token
        )
        value = _number(data.get(FOLLOWERS))
        if value is None:
            return []
        return [MetricSeries(FOLLOWERS, Period.LIFETIME, (MetricPoint(self._clock.now(), value),))]

    async def _share_stats(
        self, organization: str, token: Token, wanted: Sequence[str], span: tuple[int, int] | None
    ) -> list[MetricSeries]:
        """Con `span`, un punto por día en ese tramo; sin él, el total de los últimos 12 meses."""
        path = (
            f"organizationalEntityShareStatistics?q=organizationalEntity&organizationalEntity={organization}"
        )
        if span is not None:
            path += f"&timeIntervals=(timeRange:(start:{span[0]},end:{span[1]}),timeGranularityType:DAY)"
        data = await self._client.get(path, token.access_token, finder=True)
        elements = as_list(data.get("elements"))
        result_period = Period.DAY if span is not None else Period.LIFETIME
        return [
            MetricSeries(name, result_period, points)
            for name in wanted
            if (points := self._points(elements, name, daily=span is not None))
        ]

    def _points(
        self, elements: list[dict[str, object]], name: str, *, daily: bool
    ) -> tuple[MetricPoint, ...]:
        points: list[MetricPoint] = []
        for element in elements:
            value = _number(as_dict(element.get("totalShareStatistics")).get(name))
            if value is None:
                continue
            end = from_millis(as_dict(element.get("timeRange")).get("end")) if daily else self._clock.now()
            points.append(MetricPoint(end, value))
        return tuple(points)
