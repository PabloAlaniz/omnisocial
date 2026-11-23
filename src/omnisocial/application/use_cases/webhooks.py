"""Recibir avisos de una red y saber a qué activos (y dueños) corresponden."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from omnisocial.application.ports import AssetRepository
from omnisocial.application.registry import ProviderRegistry
from omnisocial.application.results import Done, Refusal, Refused
from omnisocial.domain.asset import Asset
from omnisocial.domain.webhooks import SocialEvent


@dataclass(frozen=True, slots=True)
class RoutedEvent:
    event: SocialEvent
    assets: Sequence[Asset]
    """Los activos guardados con ese id. Puede haber varios si más de un dueño conectó la misma página."""


class HandleWebhook:
    """Verifica la firma, traduce el aviso y lo enruta. Nada se traduce sin verificar."""

    def __init__(self, *, registry: ProviderRegistry, assets: AssetRepository) -> None:
        self._registry = registry
        self._assets = assets

    async def execute(
        self, provider_id: str, *, body: bytes, headers: Mapping[str, str]
    ) -> Done[Sequence[RoutedEvent]] | Refused:
        provider = self._registry.get(provider_id)
        parser = provider.require_webhooks()
        lowered = {k.lower(): v for k, v in headers.items()}
        if not parser.verify_signature(body, lowered):
            return Refused(Refusal.INVALID_SIGNATURE)
        routed = [
            RoutedEvent(event, await self._assets.find_by_external_id(provider.id, event.asset_external_id))
            for event in parser.parse(body)
        ]
        return Done(routed)
