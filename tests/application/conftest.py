from __future__ import annotations

from dataclasses import dataclass

import pytest

from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
)
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.entrypoints.hub import Omnisocial
from tests.fakes import FakeNetwork, FakeSecrets, SequentialIds


@dataclass
class World:
    network: FakeNetwork
    connections: InMemoryConnectionRepository
    assets: InMemoryAssetRepository
    social: Omnisocial


def build_world(network: FakeNetwork | None = None, **provider_kwargs: object) -> World:
    network = network or FakeNetwork()
    connections = InMemoryConnectionRepository()
    assets = InMemoryAssetRepository()
    social = Omnisocial.build(
        providers=[network.provider(**provider_kwargs)],  # type: ignore[arg-type]
        connections=connections,
        assets=assets,
        states=InMemoryAuthorizationStateStore(network.clock),
        redirect_uri_for=lambda provider: f"https://api.ejemplo.com/oauth/{provider}/callback",
        return_urls=ReturnUrlPolicy.of("https://app.ejemplo.com"),
        clock=network.clock,
        ids=SequentialIds(),
        secrets=FakeSecrets(),
    )
    return World(network, connections, assets, social)


@pytest.fixture
def world() -> World:
    return build_world()
