"""Arma el proveedor de X."""

from __future__ import annotations

from dataclasses import replace

from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.x.assets import XAssetDirectory
from omnisocial.adapters.providers.x.client import XClient
from omnisocial.adapters.providers.x.comments import XCommentGateway
from omnisocial.adapters.providers.x.config import X_ACCOUNT, X, XConfig
from omnisocial.adapters.providers.x.content import XContentReader
from omnisocial.adapters.providers.x.insights import DEFAULT_CATALOG, XInsightsReader
from omnisocial.adapters.providers.x.oauth import XIdentity, x_oauth
from omnisocial.adapters.providers.x.profiles import XProfileLookup
from omnisocial.adapters.providers.x.publishing import XPublisher
from omnisocial.adapters.providers.x.spec import ACCOUNT_LIMITS, SPEC, account_limits
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import Clock
from omnisocial.application.registry import Provider
from omnisocial.domain.metrics import MetricCatalog
from omnisocial.domain.spec import NetworkSpec


def _spec(config: XConfig) -> NetworkSpec:
    if config.max_post_length == ACCOUNT_LIMITS.max_text:
        return SPEC
    # Una cuenta con X Premium publica textos más largos.
    return replace(SPEC, publishing={X_ACCOUNT: account_limits(config.max_post_length)})


def x_provider(
    config: XConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    catalog: MetricCatalog = DEFAULT_CATALOG,
) -> Provider:
    """Con la app, todo menos mensajes y webhooks. Solo con el token de la app, perfiles públicos."""
    clock = clock or SystemClock()
    client = XClient(config, transport, clock)
    spec = _spec(config)
    profiles = XProfileLookup(client) if config.bearer_token else None
    if not config.has_app:
        return Provider(id=X, profiles=profiles, spec=spec)
    return Provider(
        id=X,
        oauth=x_oauth(client, clock),
        identity=XIdentity(client),
        assets=XAssetDirectory(client),
        content=XContentReader(client),
        comments=XCommentGateway(client),
        insights=XInsightsReader(client, clock, catalog),
        profiles=profiles,
        publisher=XPublisher(client),
        spec=spec,
    )
