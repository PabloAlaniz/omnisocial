"""Arma el proveedor de Pinterest."""

from __future__ import annotations

from omnisocial.adapters.http.pacing import paced
from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.pinterest.client import PinterestClient
from omnisocial.adapters.providers.pinterest.config import PINTEREST, PinterestConfig
from omnisocial.adapters.providers.pinterest.oauth import PinterestIdentity, pinterest_oauth
from omnisocial.adapters.providers.pinterest.publishing import PinterestPublisher
from omnisocial.adapters.providers.pinterest.reading import (
    DEFAULT_CATALOG,
    PinterestAssetDirectory,
    PinterestContentReader,
    PinterestInsightsReader,
    PinterestLookups,
)
from omnisocial.adapters.providers.pinterest.spec import SPEC
from omnisocial.adapters.system import SystemClock, UuidGenerator
from omnisocial.application.ports import Clock, IdGenerator
from omnisocial.application.registry import Provider
from omnisocial.domain.metrics import MetricCatalog


def pinterest_provider(
    config: PinterestConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    catalog: MetricCatalog = DEFAULT_CATALOG,
) -> Provider:
    """Con acceso de prueba, lo que se crea solo lo ve quien lo creó: para publicar de verdad hace falta
    el acceso estándar."""
    clock = clock or SystemClock()
    client = PinterestClient(config, paced(transport, SPEC.pace))
    return Provider(
        id=PINTEREST,
        oauth=pinterest_oauth(client, clock),
        identity=PinterestIdentity(client),
        assets=PinterestAssetDirectory(client),
        content=PinterestContentReader(client),
        insights=PinterestInsightsReader(client, clock, catalog),
        publisher=PinterestPublisher(client, ids or UuidGenerator()),
        lookups=PinterestLookups(client),
        spec=SPEC,
    )
