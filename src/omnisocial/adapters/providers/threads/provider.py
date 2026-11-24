"""Arma el proveedor de Threads."""

from __future__ import annotations

from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.threads.assets import ThreadsAssetDirectory
from omnisocial.adapters.providers.threads.client import ThreadsClient
from omnisocial.adapters.providers.threads.comments import ThreadsCommentGateway
from omnisocial.adapters.providers.threads.config import THREADS, ThreadsConfig
from omnisocial.adapters.providers.threads.content import ThreadsContentReader
from omnisocial.adapters.providers.threads.insights import DEFAULT_CATALOG, ThreadsInsightsReader
from omnisocial.adapters.providers.threads.oauth import ThreadsOAuth
from omnisocial.adapters.providers.threads.publishing import ThreadsPublisher
from omnisocial.adapters.providers.threads.spec import SPEC
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import Clock
from omnisocial.application.registry import Provider
from omnisocial.domain.metrics import MetricCatalog


def threads_provider(
    config: ThreadsConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    catalog: MetricCatalog = DEFAULT_CATALOG,
) -> Provider:
    """Login, la cuenta como activo, posts, respuestas, métricas y publicar (con hilos)."""
    clock = clock or SystemClock()
    client = ThreadsClient(config, transport)
    return Provider(
        id=THREADS,
        oauth=ThreadsOAuth(client, clock),
        assets=ThreadsAssetDirectory(client),
        content=ThreadsContentReader(client),
        comments=ThreadsCommentGateway(client),
        insights=ThreadsInsightsReader(client, clock, catalog),
        publisher=ThreadsPublisher(client),
        spec=SPEC,
    )
