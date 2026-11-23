"""Las redes disponibles y lo que cada una sabe hacer."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import TypeVar

from omnisocial.application.ports import (
    AssetDirectory,
    CommentGateway,
    ContentReader,
    InsightsReader,
    MessagingGateway,
    OAuthClient,
    WebhookParser,
)
from omnisocial.domain.errors import CapabilityNotSupported, UnknownProvider
from omnisocial.domain.provider import Capability, ProviderId

ENTRY_POINT_GROUP = "omnisocial.providers"

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Provider:
    """Una red con las capacidades que implementa. Lo que no trae, no lo soporta."""

    id: ProviderId
    oauth: OAuthClient | None = None
    assets: AssetDirectory | None = None
    content: ContentReader | None = None
    comments: CommentGateway | None = None
    messaging: MessagingGateway | None = None
    insights: InsightsReader | None = None
    webhooks: WebhookParser | None = None

    @property
    def capabilities(self) -> frozenset[Capability]:
        present = {
            Capability.LOGIN: self.oauth,
            Capability.ASSETS: self.assets,
            Capability.CONTENT: self.content,
            Capability.COMMENTS: self.comments,
            Capability.MESSAGING: self.messaging,
            Capability.INSIGHTS: self.insights,
            Capability.WEBHOOKS: self.webhooks,
        }
        return frozenset(c for c, component in present.items() if component is not None)

    def _require(self, component: T | None, capability: Capability) -> T:
        if component is None:
            raise CapabilityNotSupported(self.id, capability)
        return component

    def require_oauth(self) -> OAuthClient:
        return self._require(self.oauth, Capability.LOGIN)

    def require_assets(self) -> AssetDirectory:
        return self._require(self.assets, Capability.ASSETS)

    def require_content(self) -> ContentReader:
        return self._require(self.content, Capability.CONTENT)

    def require_comments(self) -> CommentGateway:
        return self._require(self.comments, Capability.COMMENTS)

    def require_messaging(self) -> MessagingGateway:
        return self._require(self.messaging, Capability.MESSAGING)

    def require_insights(self) -> InsightsReader:
        return self._require(self.insights, Capability.INSIGHTS)

    def require_webhooks(self) -> WebhookParser:
        return self._require(self.webhooks, Capability.WEBHOOKS)


class ProviderRegistry:
    def __init__(self, providers: Iterable[Provider] = ()) -> None:
        self._providers: dict[ProviderId, Provider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: Provider) -> None:
        if provider.id in self._providers:
            raise ValueError(f"Ya hay una red registrada como '{provider.id}'.")
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> Provider:
        try:
            return self._providers[ProviderId(provider_id)]
        except KeyError:
            raise UnknownProvider(provider_id) from None

    def __contains__(self, provider_id: object) -> bool:
        return provider_id in self._providers

    @property
    def ids(self) -> tuple[ProviderId, ...]:
        return tuple(self._providers)


def load_entry_point(name: str) -> object:
    """La fábrica que un paquete externo publicó en el grupo `omnisocial.providers`.

    Así una red nueva se suma instalando un paquete, sin tocar este. La fábrica recibe la configuración
    que haga falta y devuelve un `Provider`.
    """
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        if entry.name == name:
            return entry.load()
    raise UnknownProvider(name)
