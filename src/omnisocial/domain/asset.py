"""Lo que una conexión permite administrar: una página, una cuenta profesional, un canal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.token import Token


@dataclass(frozen=True, slots=True)
class DiscoveredAsset:
    """Un activo tal como lo devuelve la red, antes de guardarlo."""

    kind: str
    """Abierto a cada red: `facebook_page`, `instagram_account`, `tiktok_account`…"""
    external_id: str
    name: str | None = None
    parent_external_id: str | None = None
    token: Token | None = field(default=None, repr=False)
    """Token propio del activo. Si no tiene, se usa el de la conexión."""
    capabilities: frozenset[Capability] = frozenset()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Asset:
    id: str
    connection_id: str
    provider: ProviderId
    owner: str
    kind: str
    external_id: str
    name: str | None = None
    parent_external_id: str | None = None
    token: Token | None = field(default=None, repr=False)
    capabilities: frozenset[Capability] = frozenset()
    metadata: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_discovered(
        cls, discovered: DiscoveredAsset, *, id: str, connection_id: str, provider: ProviderId, owner: str
    ) -> Asset:
        return cls(
            id=id,
            connection_id=connection_id,
            provider=provider,
            owner=owner,
            kind=discovered.kind,
            external_id=discovered.external_id,
            name=discovered.name,
            parent_external_id=discovered.parent_external_id,
            token=discovered.token,
            capabilities=discovered.capabilities,
            metadata=dict(discovered.metadata),
        )

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities
