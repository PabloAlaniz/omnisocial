"""Arma el proveedor de TikTok."""

from __future__ import annotations

from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.tiktok.assets import TikTokAssetDirectory
from omnisocial.adapters.providers.tiktok.client import TikTokClient
from omnisocial.adapters.providers.tiktok.config import TIKTOK, TikTokConfig
from omnisocial.adapters.providers.tiktok.content import TikTokContentReader
from omnisocial.adapters.providers.tiktok.insights import DEFAULT_CATALOG, TikTokInsightsReader
from omnisocial.adapters.providers.tiktok.oauth import tiktok_oauth
from omnisocial.adapters.providers.tiktok.publishing import TikTokPublisher
from omnisocial.adapters.providers.tiktok.spec import SPEC
from omnisocial.adapters.providers.tiktok.webhooks import TikTokWebhookParser
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import Clock
from omnisocial.application.registry import Provider
from omnisocial.domain.metrics import MetricCatalog


def tiktok_provider(
    config: TikTokConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    catalog: MetricCatalog = DEFAULT_CATALOG,
) -> Provider:
    """Login, la cuenta como activo, videos, contadores y webhooks.

    Sin comentarios ni mensajes: la Display API no los ofrece.
    """
    clock = clock or SystemClock()
    client = TikTokClient(config, transport)
    return Provider(
        id=TIKTOK,
        oauth=tiktok_oauth(client, clock),
        assets=TikTokAssetDirectory(client),
        content=TikTokContentReader(client),
        insights=TikTokInsightsReader(client, clock, catalog),
        webhooks=TikTokWebhookParser(config, clock),
        publisher=TikTokPublisher(client),
        spec=SPEC,
    )
