"""Arma el proveedor de YouTube."""

from __future__ import annotations

from datetime import timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.youtube.assets import YouTubeAssetDirectory
from omnisocial.adapters.providers.youtube.client import YouTubeClient
from omnisocial.adapters.providers.youtube.comments import YouTubeCommentGateway
from omnisocial.adapters.providers.youtube.config import YOUTUBE, YouTubeConfig
from omnisocial.adapters.providers.youtube.content import YouTubeContentReader
from omnisocial.adapters.providers.youtube.insights import DEFAULT_CATALOG, YouTubeInsightsReader
from omnisocial.adapters.providers.youtube.oauth import YouTubeIdentity, youtube_oauth
from omnisocial.adapters.providers.youtube.profiles import YouTubeProfileLookup
from omnisocial.adapters.providers.youtube.publishing import YouTubePublisher
from omnisocial.adapters.providers.youtube.spec import SPEC
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import Clock, QuotaLedger
from omnisocial.application.quota import QuotaBudget
from omnisocial.application.registry import Provider
from omnisocial.domain.metrics import MetricCatalog


def quota_resets_in() -> tzinfo:
    """YouTube reinicia la cuota a medianoche, hora del Pacífico."""
    try:
        return ZoneInfo("America/Los_Angeles")
    except ZoneInfoNotFoundError:  # pragma: no cover - sistemas sin base de zonas horarias
        return timezone(timedelta(hours=-8))


def _client(
    config: YouTubeConfig, transport: HttpTransport, clock: Clock, quota: QuotaLedger | None
) -> YouTubeClient:
    if quota is None:
        return YouTubeClient(config, transport)
    # La cuota es del proyecto de Google, no de cada canal conectado.
    project = f"youtube:{config.client_id or 'clave-de-api'}"
    zone = quota_resets_in()
    return YouTubeClient(
        config,
        transport,
        units=QuotaBudget(f"{project}:unidades", config.quota_units, quota, clock, zone),
        uploads=QuotaBudget(f"{project}:subidas", config.quota_uploads, quota, clock, zone),
    )


def youtube_provider(
    config: YouTubeConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    catalog: MetricCatalog = DEFAULT_CATALOG,
    quota: QuotaLedger | None = None,
) -> Provider:
    """Con la app, todo menos webhooks. Solo con una clave de API, perfiles públicos y nada más.

    `quota` lleva la cuenta de lo que se gasta por día: cuando el presupuesto se agota, las operaciones
    vuelven `Refused(QUOTA_EXHAUSTED)` sin llamar a YouTube.
    """
    clock = clock or SystemClock()
    client = _client(config, transport, clock, quota)
    profiles = YouTubeProfileLookup(client) if config.api_key else None
    if not config.has_app:
        return Provider(id=YOUTUBE, profiles=profiles, spec=SPEC)
    return Provider(
        id=YOUTUBE,
        oauth=youtube_oauth(client, clock),
        identity=YouTubeIdentity(client),
        assets=YouTubeAssetDirectory(client),
        content=YouTubeContentReader(client),
        comments=YouTubeCommentGateway(client),
        insights=YouTubeInsightsReader(client, clock, catalog),
        profiles=profiles,
        publisher=YouTubePublisher(client),
        spec=SPEC,
    )
