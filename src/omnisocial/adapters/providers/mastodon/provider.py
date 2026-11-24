"""Arma los proveedores de Mastodon y de Pixelfed."""

from __future__ import annotations

from dataclasses import dataclass

from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.mastodon.client import MastodonClient
from omnisocial.adapters.providers.mastodon.config import (
    MASTODON_FLAVOR,
    PIXELFED_FLAVOR,
    Flavor,
    MastodonConfig,
    PixelfedConfig,
)
from omnisocial.adapters.providers.mastodon.oauth import MastodonIdentity, MastodonOAuth
from omnisocial.adapters.providers.mastodon.publishing import MastodonPublisher
from omnisocial.adapters.providers.mastodon.reading import (
    MastodonAssetDirectory,
    MastodonCommentGateway,
    MastodonContentReader,
    MastodonInsightsReader,
    MastodonProfileLookup,
    catalog_for,
)
from omnisocial.adapters.providers.mastodon.spec import PIXELFED_SPEC, SPEC
from omnisocial.adapters.system import SystemClock, UuidGenerator
from omnisocial.application.ports import Clock, IdGenerator, ServerAppStore
from omnisocial.application.registry import Provider
from omnisocial.domain.spec import NetworkSpec


@dataclass(frozen=True, slots=True)
class _Network:
    flavor: Flavor
    spec: NetworkSpec
    profiles: bool


_MASTODON = _Network(MASTODON_FLAVOR, SPEC, profiles=True)
# No se pudo confirmar que Pixelfed deje buscar cuentas sin autorizar: no se ofrece.
_PIXELFED = _Network(PIXELFED_FLAVOR, PIXELFED_SPEC, profiles=False)


def _build(
    network: _Network,
    config: MastodonConfig,
    transport: HttpTransport,
    apps: ServerAppStore,
    *,
    clock: Clock | None,
    ids: IdGenerator | None,
) -> Provider:
    clock = clock or SystemClock()
    flavor = network.flavor
    client = MastodonClient(flavor, transport, clock)
    return Provider(
        id=flavor.provider,
        server_oauth=MastodonOAuth(client, config, apps, clock),
        identity=MastodonIdentity(client),
        assets=MastodonAssetDirectory(client),
        content=MastodonContentReader(client, config.page_size),
        comments=MastodonCommentGateway(client),
        insights=MastodonInsightsReader(client, clock, catalog_for(flavor.account_kind)),
        profiles=MastodonProfileLookup(client) if network.profiles else None,
        publisher=MastodonPublisher(client, ids or UuidGenerator()),
        spec=network.spec,
    )


def mastodon_provider(
    config: MastodonConfig,
    transport: HttpTransport,
    *,
    apps: ServerAppStore,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
) -> Provider:
    """`apps` guarda la app registrada en cada servidor. Para autorizar hay que decir en cuál está la
    cuenta: `social.start_authorization.execute("mastodon", ..., server="mastodon.social")`."""
    return _build(_MASTODON, config, transport, apps, clock=clock, ids=ids)


def pixelfed_provider(
    config: PixelfedConfig,
    transport: HttpTransport,
    *,
    apps: ServerAppStore,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
) -> Provider:
    """Pixelfed habla el protocolo de Mastodon: es el mismo adaptador, con otros límites y otros permisos."""
    return _build(_PIXELFED, config, transport, apps, clock=clock, ids=ids)
