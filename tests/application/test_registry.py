from __future__ import annotations

from importlib.metadata import EntryPoint

import pytest

from omnisocial.application import registry as registry_module
from omnisocial.application.registry import ENTRY_POINT_GROUP, Provider, ProviderRegistry, load_entry_point
from omnisocial.domain.errors import CapabilityNotSupported, UnknownProvider
from omnisocial.domain.provider import Capability, ProviderId
from tests.fakes import FakeNetwork


def test_capacidades_segun_lo_que_trae() -> None:
    full = FakeNetwork().provider()
    assert full.capabilities == frozenset(Capability)
    bare = Provider(ProviderId("vacia"))
    assert bare.capabilities == frozenset()
    for require in (
        bare.require_oauth,
        bare.require_assets,
        bare.require_content,
        bare.require_comments,
        bare.require_messaging,
        bare.require_insights,
        bare.require_webhooks,
        bare.require_publisher,
    ):
        with pytest.raises(CapabilityNotSupported, match="vacia"):
            require()


def test_registro() -> None:
    provider = FakeNetwork().provider()
    registry = ProviderRegistry([provider])
    assert registry.ids == (provider.id,)
    assert "falsa" in registry
    assert registry.get("falsa") is provider
    with pytest.raises(ValueError, match="Ya hay"):
        registry.register(provider)
    with pytest.raises(UnknownProvider, match="otra"):
        registry.get("otra")


def test_redes_externas_por_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = EntryPoint(name="falsa", value="tests.fakes:FakeNetwork", group=ENTRY_POINT_GROUP)
    monkeypatch.setattr(
        registry_module, "entry_points", lambda group: [entry] if group == ENTRY_POINT_GROUP else []
    )
    assert load_entry_point("falsa") is FakeNetwork
    with pytest.raises(UnknownProvider):
        load_entry_point("otra")
