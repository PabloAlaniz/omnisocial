"""Arma el proveedor de LinkedIn."""

from __future__ import annotations

from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.linkedin.assets import LinkedInAssetDirectory
from omnisocial.adapters.providers.linkedin.client import LinkedInClient
from omnisocial.adapters.providers.linkedin.comments import LinkedInCommentGateway
from omnisocial.adapters.providers.linkedin.config import LINKEDIN, LinkedInConfig
from omnisocial.adapters.providers.linkedin.content import LinkedInContentReader
from omnisocial.adapters.providers.linkedin.insights import DEFAULT_CATALOG, LinkedInInsightsReader
from omnisocial.adapters.providers.linkedin.oauth import LinkedInIdentity, linkedin_oauth
from omnisocial.adapters.providers.linkedin.publishing import LinkedInPublisher
from omnisocial.adapters.providers.linkedin.spec import SPEC
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import Clock
from omnisocial.application.registry import Provider
from omnisocial.domain.metrics import MetricCatalog


def linkedin_provider(
    config: LinkedInConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    catalog: MetricCatalog = DEFAULT_CATALOG,
) -> Provider:
    """Login y publicar como persona funcionan con una app recién creada. Las páginas de empresa (leer,
    comentarios, métricas, publicar como la página) necesitan la Community Management API aprobada."""
    clock = clock or SystemClock()
    client = LinkedInClient(config, transport)
    return Provider(
        id=LINKEDIN,
        oauth=linkedin_oauth(client, clock),
        identity=LinkedInIdentity(client),
        assets=LinkedInAssetDirectory(client),
        content=LinkedInContentReader(client),
        comments=LinkedInCommentGateway(client),
        insights=LinkedInInsightsReader(client, clock, catalog),
        publisher=LinkedInPublisher(client),
        spec=SPEC,
    )
