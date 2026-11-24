"""Arma el proveedor de Google Business Profile."""

from __future__ import annotations

from omnisocial.adapters.http.pacing import paced
from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.google_business.client import GoogleBusinessClient
from omnisocial.adapters.providers.google_business.config import GOOGLE_BUSINESS, GoogleBusinessConfig
from omnisocial.adapters.providers.google_business.oauth import (
    GoogleBusinessIdentity,
    google_business_oauth,
)
from omnisocial.adapters.providers.google_business.publishing import GoogleBusinessPublisher
from omnisocial.adapters.providers.google_business.reading import (
    DEFAULT_CATALOG,
    GoogleBusinessAssetDirectory,
    GoogleBusinessContentReader,
    GoogleBusinessInsightsReader,
    GoogleBusinessReviews,
)
from omnisocial.adapters.providers.google_business.spec import SPEC
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import Clock, RateLimitStore
from omnisocial.application.registry import Provider
from omnisocial.domain.metrics import MetricCatalog
from omnisocial.domain.spec import Pace


def google_business_provider(
    config: GoogleBusinessConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    catalog: MetricCatalog = DEFAULT_CATALOG,
    pace: Pace | None = SPEC.pace,
    rate_limits: RateLimitStore | None = None,
) -> Provider:
    """Google aprueba cada proyecto antes de darle acceso a estas APIs: hasta entonces su cupo es cero y
    todo responde con un límite de uso. `pace` es el ritmo de los pedidos dentro de este proceso."""
    clock = clock or SystemClock()
    client = GoogleBusinessClient(config, paced(transport, pace, store=rate_limits, key=GOOGLE_BUSINESS))
    return Provider(
        id=GOOGLE_BUSINESS,
        oauth=google_business_oauth(client, clock),
        identity=GoogleBusinessIdentity(client),
        assets=GoogleBusinessAssetDirectory(client),
        content=GoogleBusinessContentReader(client),
        comments=GoogleBusinessReviews(client),
        insights=GoogleBusinessInsightsReader(client, clock, catalog),
        publisher=GoogleBusinessPublisher(client),
        spec=SPEC,
    )
