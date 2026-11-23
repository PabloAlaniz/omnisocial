"""Arma el proveedor de Meta con todas sus capacidades."""

from __future__ import annotations

from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.meta.assets import MetaAssetDirectory
from omnisocial.adapters.providers.meta.catalog import DEFAULT_CATALOG
from omnisocial.adapters.providers.meta.comments import MetaCommentGateway
from omnisocial.adapters.providers.meta.config import META, MetaConfig
from omnisocial.adapters.providers.meta.content import MetaContentReader
from omnisocial.adapters.providers.meta.graph import GraphClient
from omnisocial.adapters.providers.meta.insights import MetaInsightsReader
from omnisocial.adapters.providers.meta.messaging import MetaMessagingGateway
from omnisocial.adapters.providers.meta.oauth import MetaOAuth
from omnisocial.adapters.providers.meta.webhooks import MetaWebhookParser
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import Clock
from omnisocial.application.registry import Provider
from omnisocial.domain.metrics import MetricCatalog


def meta_provider(
    config: MetaConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    catalog: MetricCatalog = DEFAULT_CATALOG,
) -> Provider:
    clock = clock or SystemClock()
    graph = GraphClient(config, transport)
    return Provider(
        id=META,
        oauth=MetaOAuth(graph, clock),
        assets=MetaAssetDirectory(graph),
        content=MetaContentReader(graph),
        comments=MetaCommentGateway(graph),
        messaging=MetaMessagingGateway(graph),
        insights=MetaInsightsReader(graph, clock, catalog),
        webhooks=MetaWebhookParser(config),
    )
