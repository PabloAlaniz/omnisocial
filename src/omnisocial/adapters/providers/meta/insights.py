"""Métricas de páginas y de cuentas de Instagram."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from omnisocial.adapters.providers.meta.catalog import DEFAULT_CATALOG, INSTAGRAM_TOTAL_VALUE_METRICS
from omnisocial.adapters.providers.meta.config import INSTAGRAM_ACCOUNT
from omnisocial.adapters.providers.meta.graph import (
    GraphClient,
    as_dict,
    as_list,
    as_str,
    parse_time,
    unix,
)
from omnisocial.application.ports import Clock
from omnisocial.domain.asset import Asset
from omnisocial.domain.metrics import MetricCatalog, MetricPoint, MetricSeries, Period
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

DEFAULT_SPAN = timedelta(days=28)


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, dict):
        # Desgloses (por país, por tipo…): se suma el total.
        numbers = [float(v) for v in value.values() if isinstance(v, int | float) and not isinstance(v, bool)]
        return sum(numbers) if numbers else None
    return None


class MetaInsightsReader:
    def __init__(self, graph: GraphClient, clock: Clock, catalog: MetricCatalog = DEFAULT_CATALOG) -> None:
        self._graph = graph
        self._clock = clock
        self.catalog = catalog

    @property
    def api_version(self) -> str:
        return self._graph.config.api_version

    def _resolve(self, window: TimeWindow) -> TimeWindow:
        until = window.until or self._clock.now()
        since = window.since or until - DEFAULT_SPAN
        return TimeWindow(since, until)

    async def read(
        self, asset: Asset, token: Token, *, metrics: Sequence[str], period: Period, window: TimeWindow
    ) -> Sequence[MetricSeries]:
        resolved = self._resolve(window)
        groups: list[tuple[tuple[str, ...], str | None]]
        if asset.kind == INSTAGRAM_ACCOUNT:
            totals = tuple(m for m in metrics if m in INSTAGRAM_TOTAL_VALUE_METRICS)
            series = tuple(m for m in metrics if m not in INSTAGRAM_TOTAL_VALUE_METRICS)
            groups = [(series, None), (totals, "total_value")]
        else:
            groups = [(tuple(metrics), None)]

        points: dict[str, list[MetricPoint]] = {name: [] for name in metrics}
        chunks = resolved.chunks(self._graph.config.insights_max_span)
        for names, metric_type in groups:
            if not names:
                continue
            for chunk in chunks:
                for name, chunk_points in await self._fetch(asset, token, names, period, chunk, metric_type):
                    points.setdefault(name, []).extend(chunk_points)
        return [
            MetricSeries(name=name, period=period, points=tuple(values))
            for name, values in points.items()
            if values
        ]

    async def _fetch(
        self,
        asset: Asset,
        token: Token,
        names: tuple[str, ...],
        period: Period,
        window: TimeWindow,
        metric_type: str | None,
    ) -> list[tuple[str, list[MetricPoint]]]:
        since, until = window.since, window.until
        if since is None or until is None:  # pragma: no cover - _resolve completa los dos extremos
            raise ValueError("La ventana de métricas necesita los dos extremos.")
        params: dict[str, str | int] = {
            "metric": ",".join(names),
            "period": period.value,
            "since": unix(since),
            "until": unix(until),
        }
        if metric_type:
            params["metric_type"] = metric_type
        body = await self._graph.get(f"{asset.external_id}/insights", token.access_token, params)
        out: list[tuple[str, list[MetricPoint]]] = []
        for item in as_list(body.get("data")):
            name = as_str(item.get("name"))
            if not name:
                continue
            if "total_value" in item:
                value = _number(as_dict(item.get("total_value")).get("value"))
                out.append((name, [MetricPoint(until, value)] if value is not None else []))
                continue
            values = []
            for raw in as_list(item.get("values")):
                value = _number(raw.get("value"))
                if value is not None:
                    values.append(MetricPoint(parse_time(raw.get("end_time")), value))
            out.append((name, values))
        return out
