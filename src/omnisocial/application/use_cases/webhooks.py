"""Recibir avisos de una red: verificar, no procesar dos veces, traducir y enrutar a sus dueños.

La verificación y la idempotencia las resuelve omniwebhook. Cada aviso se reserva antes de procesarlo: si el
procesamiento falla, la reserva se libera y el reintento de la red entra; si llega de nuevo después de
procesarse, se responde 200 sin volver a procesarlo.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from omniwebhook import (
    AsyncIdempotencyStore,
    AsyncReceiveWebhook,
    IncomingRequest,
    ReceptionOutcome,
    VerifiedEvent,
    create_async_receiver,
    http_status_for,
)

from omnisocial.application.ports import AssetRepository
from omnisocial.application.registry import Provider, ProviderRegistry
from omnisocial.application.use_cases.access import GetValidToken
from omnisocial.domain.asset import Asset
from omnisocial.domain.connection import ConnectionStatus
from omnisocial.domain.provider import ProviderId
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent


@dataclass(frozen=True, slots=True)
class RoutedEvent:
    event: SocialEvent
    assets: Sequence[Asset]
    """Los activos guardados con ese id. Puede haber varios si más de un dueño conectó la misma página."""


OnEvents = Callable[[Sequence[RoutedEvent]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WebhookReceived:
    outcome: ReceptionOutcome
    """El resultado de omniwebhook: `ok`, `duplicate`, `in_progress`, `failed` o el motivo del rechazo."""
    status: int
    """El estado HTTP para responderle a la red."""
    events: Sequence[RoutedEvent] = field(default_factory=tuple)
    """Lo que se entregó a `on_events`. Vacío si no se procesó (duplicado, rechazo o falla)."""
    error: Exception | None = None


class HandleWebhook:
    """Entrega los avisos, y revoca la conexión cuando la red avisa que la persona quitó el acceso."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        assets: AssetRepository,
        store: AsyncIdempotencyStore,
        tokens: GetValidToken,
    ) -> None:
        self._registry = registry
        self._assets = assets
        self._store = store
        self._tokens = tokens
        self._receivers: dict[ProviderId, AsyncReceiveWebhook] = {}

    def _receiver(self, provider: Provider) -> AsyncReceiveWebhook:
        receiver = self._receivers.get(provider.id)
        if receiver is None:
            verifier = provider.require_webhooks().verifier
            receiver = create_async_receiver(verifier=verifier, store=self._store)
            self._receivers[provider.id] = receiver
        return receiver

    async def execute(
        self, provider_id: str, *, request: IncomingRequest, on_events: OnEvents
    ) -> WebhookReceived:
        provider = self._registry.get(provider_id)
        parser = provider.require_webhooks()
        receiver = self._receiver(provider)
        delivered: list[RoutedEvent] = []

        async def handle(event: VerifiedEvent) -> None:
            routed = [
                RoutedEvent(item, await self._assets.find_by_external_id(provider.id, item.asset_external_id))
                for item in parser.parse(event.request.body, query=_query(event.request))
            ]
            await self._revoke(routed)
            await on_events(routed)
            delivered.extend(routed)

        reception = await receiver.execute(request, handle)
        return WebhookReceived(
            outcome=reception.outcome,
            status=http_status_for(reception.outcome),
            events=tuple(delivered) if reception.outcome == "ok" else (),
            error=reception.error,
        )

    async def _revoke(self, routed: Sequence[RoutedEvent]) -> None:
        for item in routed:
            if (item.event.kind, item.event.action) != (EventKind.AUTHORIZATION, EventAction.DELETED):
                continue
            for connection_id in {asset.connection_id for asset in item.assets}:
                await self._tokens.invalidate(
                    connection_id, "la persona quitó el acceso desde la red", status=ConnectionStatus.REVOKED
                )


def _query(request: IncomingRequest) -> dict[str, str]:
    return {str(name): str(value) for name, value in request.query}
