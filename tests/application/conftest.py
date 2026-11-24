from __future__ import annotations

from dataclasses import dataclass

import pytest
from omniwebhook import AsyncMemoryIdempotencyStore

from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
)
from omnisocial.application.observing import Observer
from omnisocial.application.ports import ConnectionObserver, PublicationRepository
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.entrypoints.hub import Omnisocial
from tests.fakes import FakeNetwork, FakeSecrets, SequentialIds


@dataclass
class World:
    network: FakeNetwork
    connections: InMemoryConnectionRepository
    assets: InMemoryAssetRepository
    social: Omnisocial


def build_world(
    network: FakeNetwork | None = None,
    *,
    publications: PublicationRepository | None = None,
    on_connection_change: ConnectionObserver | None = None,
    observer: Observer | None = None,
    **provider_kwargs: object,
) -> World:
    network = network or FakeNetwork()
    connections = InMemoryConnectionRepository()
    assets = InMemoryAssetRepository()
    social = Omnisocial.build(
        providers=[network.provider(**provider_kwargs)],  # type: ignore[arg-type]
        connections=connections,
        assets=assets,
        states=InMemoryAuthorizationStateStore(network.clock),
        webhook_events=AsyncMemoryIdempotencyStore(),
        redirect_uri_for=lambda provider: f"https://api.ejemplo.com/oauth/{provider}/callback",
        return_urls=ReturnUrlPolicy.of("https://app.ejemplo.com"),
        clock=network.clock,
        ids=SequentialIds(),
        secrets=FakeSecrets(),
        publications=publications,
        on_connection_change=on_connection_change,
        observer=observer,
    )
    return World(network, connections, assets, social)


@pytest.fixture
def world() -> World:
    return build_world()
