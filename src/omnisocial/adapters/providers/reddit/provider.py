"""Arma el proveedor de Reddit."""

from __future__ import annotations

from omnisocial.adapters.http.pacing import paced
from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.reddit.client import RedditClient
from omnisocial.adapters.providers.reddit.config import REDDIT, RedditConfig
from omnisocial.adapters.providers.reddit.oauth import RedditIdentity, reddit_oauth
from omnisocial.adapters.providers.reddit.publishing import RedditPublisher
from omnisocial.adapters.providers.reddit.reading import (
    RedditAssetDirectory,
    RedditCommentGateway,
    RedditContentReader,
    RedditLookups,
)
from omnisocial.adapters.providers.reddit.spec import SPEC
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import Clock, RateLimitStore
from omnisocial.application.registry import Provider
from omnisocial.domain.spec import Pace


def reddit_provider(
    config: RedditConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    pace: Pace | None = SPEC.pace,
    rate_limits: RateLimitStore | None = None,
) -> Provider:
    """`pace` es el ritmo de los pedidos dentro de este proceso. Con varios procesos conviene bajarlo;
    `None` lo saca.

    Reddit aprueba cada app antes de darle acceso a la API, y el uso comercial va por un acuerdo
    aparte: conviene leer sus condiciones antes de integrar."""
    client = RedditClient(config, paced(transport, pace, store=rate_limits, key=REDDIT))
    return Provider(
        id=REDDIT,
        oauth=reddit_oauth(client, clock or SystemClock()),
        identity=RedditIdentity(client),
        assets=RedditAssetDirectory(client),
        content=RedditContentReader(client),
        comments=RedditCommentGateway(client),
        publisher=RedditPublisher(client),
        lookups=RedditLookups(client),
        spec=SPEC,
    )
