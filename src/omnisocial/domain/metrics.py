"""Métricas: el nombre propio de cada red y un catálogo chico de nombres comunes."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Period(StrEnum):
    DAY = "day"
    WEEK = "week"
    DAYS_28 = "days_28"
    LIFETIME = "lifetime"


class CanonicalMetric(StrEnum):
    """Nombres comunes a todas las redes. Cada red los traduce a los suyos en su catálogo."""

    FOLLOWERS = "followers"
    REACH = "reach"
    IMPRESSIONS = "impressions"
    VIEWS = "views"
    ENGAGEMENTS = "engagements"


@dataclass(frozen=True, slots=True)
class MetricPoint:
    end_time: datetime | None
    value: float


@dataclass(frozen=True, slots=True)
class MetricSeries:
    name: str
    """El nombre propio de la red."""
    period: Period
    points: tuple[MetricPoint, ...]
    canonical: CanonicalMetric | None = None


_VERSION = re.compile(r"^v?(\d+)(?:\.(\d+))?$")


def parse_version(version: str) -> tuple[int, int]:
    match = _VERSION.match(version.strip())
    if match is None:
        raise ValueError(f"Versión de API inválida: {version!r}")
    return int(match.group(1)), int(match.group(2) or 0)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """`canonical` se llama `native` en `asset_kind` desde la versión `since` y hasta antes de `until`."""

    asset_kind: str
    canonical: CanonicalMetric
    native: str
    since: str | None = None
    until: str | None = None

    def applies(self, asset_kind: str, version: str) -> bool:
        if asset_kind != self.asset_kind:
            return False
        current = parse_version(version)
        if self.since is not None and current < parse_version(self.since):
            return False
        return not (self.until is not None and current >= parse_version(self.until))


@dataclass(frozen=True, slots=True)
class MetricCatalog:
    entries: tuple[CatalogEntry, ...] = ()

    def native_for(self, asset_kind: str, canonical: CanonicalMetric, version: str) -> str | None:
        for entry in self.entries:
            if entry.canonical is canonical and entry.applies(asset_kind, version):
                return entry.native
        return None

    def canonical_for(self, asset_kind: str, native: str, version: str) -> CanonicalMetric | None:
        for entry in self.entries:
            if entry.native == native and entry.applies(asset_kind, version):
                return entry.canonical
        return None


@dataclass(frozen=True, slots=True)
class MetricSelection:
    """Qué métricas pidió alguien, ya traducidas al nombre de la red."""

    native: tuple[str, ...]
    unresolved: tuple[CanonicalMetric, ...]


def select_metrics(
    requested: Iterable[str | CanonicalMetric],
    *,
    catalog: MetricCatalog,
    asset_kind: str,
    version: str,
) -> MetricSelection:
    """Traduce los nombres comunes y deja pasar los propios de la red sin tocarlos.

    Un `CanonicalMetric` sin traducción para ese activo y esa versión queda en `unresolved` en vez de
    pedirse con un nombre que la red va a rechazar.
    """
    native: list[str] = []
    unresolved: list[CanonicalMetric] = []
    for item in requested:
        if isinstance(item, CanonicalMetric):
            name = catalog.native_for(asset_kind, item, version)
            if name is None:
                unresolved.append(item)
                continue
        else:
            name = item
        if name not in native:
            native.append(name)
    return MetricSelection(tuple(native), tuple(unresolved))
