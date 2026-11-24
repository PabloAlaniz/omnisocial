"""Arma el proveedor de Bluesky."""

from __future__ import annotations

from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.bluesky.assets import BlueskyAssetDirectory
from omnisocial.adapters.providers.bluesky.client import BlueskyClient
from omnisocial.adapters.providers.bluesky.comments import BlueskyCommentGateway
from omnisocial.adapters.providers.bluesky.config import BLUESKY, BlueskyConfig
from omnisocial.adapters.providers.bluesky.content import BlueskyContentReader
from omnisocial.adapters.providers.bluesky.insights import DEFAULT_CATALOG, BlueskyInsightsReader
from omnisocial.adapters.providers.bluesky.profiles import BlueskyProfileLookup
from omnisocial.adapters.providers.bluesky.publishing import BlueskyPublisher
from omnisocial.adapters.providers.bluesky.session import BlueskyIdentity, BlueskySession
from omnisocial.adapters.providers.bluesky.spec import SPEC
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import Clock
from omnisocial.application.registry import Provider
from omnisocial.domain.metrics import MetricCatalog


def bluesky_provider(
    config: BlueskyConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    catalog: MetricCatalog = DEFAULT_CATALOG,
) -> Provider:
    """No hace falta registrar una app (`BlueskyConfig()` alcanza): cada persona conecta con una
    contraseña de aplicación (`social.connect_with_credentials`)."""
    client = BlueskyClient(config, transport, clock or SystemClock())
    return Provider(
        id=BLUESKY,
        credentials=BlueskySession(client),
        identity=BlueskyIdentity(client),
        assets=BlueskyAssetDirectory(client),
        content=BlueskyContentReader(client),
        comments=BlueskyCommentGateway(client),
        insights=BlueskyInsightsReader(client, catalog),
        profiles=BlueskyProfileLookup(client),
        publisher=BlueskyPublisher(client),
        spec=SPEC,
    )
