"""Lo que se hace con un activo: leer publicaciones, comentarios, mensajes y métricas, y responder."""

from __future__ import annotations

from collections.abc import Sequence

from omnisocial.application.ports import Clock
from omnisocial.application.registry import Provider, ProviderRegistry
from omnisocial.application.results import AssetAccess, Done, InsightsRead, Refusal, Refused
from omnisocial.application.use_cases.access import ResolveAssetAccess
from omnisocial.domain.content import Comment, Post
from omnisocial.domain.messaging import Conversation, Message, last_inbound_at
from omnisocial.domain.metrics import CanonicalMetric, MetricSeries, Period, select_metrics
from omnisocial.domain.provider import Capability
from omnisocial.domain.window import TimeWindow

_ALL_TIME = TimeWindow()


class _AssetOperation:
    capability: Capability

    def __init__(self, *, registry: ProviderRegistry, access: ResolveAssetAccess) -> None:
        self._registry = registry
        self._access = access

    async def _open(self, asset_id: str) -> tuple[Provider, AssetAccess] | Refused:
        access = await self._access.execute(asset_id)
        if isinstance(access, Refused):
            return access
        provider = self._registry.get(access.asset.provider)
        if self.capability not in provider.capabilities or (
            access.asset.capabilities and not access.asset.supports(self.capability)
        ):
            return Refused(Refusal.NOT_SUPPORTED, capability=self.capability)
        return provider, access


class ListPosts(_AssetOperation):
    capability = Capability.CONTENT

    async def execute(
        self, asset_id: str, *, window: TimeWindow = _ALL_TIME, limit: int | None = None
    ) -> Done[Sequence[Post]] | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        provider, access = opened
        posts = await provider.require_content().list_posts(
            access.asset, access.token, window=window, limit=limit
        )
        return Done(posts)


class ListComments(_AssetOperation):
    capability = Capability.COMMENTS

    async def execute(self, asset_id: str, *, object_id: str) -> Done[Sequence[Comment]] | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        provider, access = opened
        comments = await provider.require_comments().list_comments(
            access.asset, access.token, object_id=object_id
        )
        return Done(comments)


class ReplyToComment(_AssetOperation):
    capability = Capability.COMMENTS

    async def execute(self, asset_id: str, *, comment_id: str, text: str) -> Done[str] | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        provider, access = opened
        new_id = await provider.require_comments().reply(
            access.asset, access.token, comment_id=comment_id, text=text
        )
        return Done(new_id)


class SetCommentHidden(_AssetOperation):
    capability = Capability.COMMENTS

    async def execute(self, asset_id: str, *, comment_id: str, hidden: bool) -> Done[None] | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        provider, access = opened
        await provider.require_comments().set_hidden(
            access.asset, access.token, comment_id=comment_id, hidden=hidden
        )
        return Done(None)


class ListConversations(_AssetOperation):
    capability = Capability.MESSAGING

    async def execute(
        self, asset_id: str, *, limit: int | None = None
    ) -> Done[Sequence[Conversation]] | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        provider, access = opened
        return Done(
            await provider.require_messaging().list_conversations(access.asset, access.token, limit=limit)
        )


class ListMessages(_AssetOperation):
    capability = Capability.MESSAGING

    async def execute(
        self, asset_id: str, *, conversation_id: str, limit: int | None = None
    ) -> Done[Sequence[Message]] | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        provider, access = opened
        messages = await provider.require_messaging().list_messages(
            access.asset, access.token, conversation_id=conversation_id, limit=limit
        )
        return Done(messages)


class SendMessage(_AssetOperation):
    """Responde en una conversación respetando la ventana de la red.

    El destinatario es quien escribió último. Si pasó la ventana, se niega antes de llamar a la red: la
    red rechazaría el mensaje igual, y repetirlo puede costar la cuenta.
    """

    capability = Capability.MESSAGING

    def __init__(self, *, registry: ProviderRegistry, access: ResolveAssetAccess, clock: Clock) -> None:
        super().__init__(registry=registry, access=access)
        self._clock = clock

    async def execute(self, asset_id: str, *, conversation_id: str, text: str) -> Done[str] | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        provider, access = opened
        messaging = provider.require_messaging()
        messages = await messaging.list_messages(
            access.asset, access.token, conversation_id=conversation_id, limit=None
        )
        latest = last_inbound_at(messages)
        recipient = next(
            (m.sender_id for m in messages if not m.from_asset and m.created_at == latest and m.sender_id),
            None,
        )
        if latest is None or recipient is None:
            return Refused(Refusal.NO_RECIPIENT)
        if not messaging.reply_window.allows(latest, self._clock.now()):
            return Refused(Refusal.OUTSIDE_REPLY_WINDOW)
        message_id = await messaging.send(access.asset, access.token, recipient_id=recipient, text=text)
        return Done(message_id)


class ReadInsights(_AssetOperation):
    """Lee métricas por su nombre en la red o por un nombre común del catálogo."""

    capability = Capability.INSIGHTS

    async def execute(
        self,
        asset_id: str,
        *,
        metrics: Sequence[str | CanonicalMetric],
        period: Period,
        window: TimeWindow,
    ) -> InsightsRead | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        provider, access = opened
        reader = provider.require_insights()
        selection = select_metrics(
            metrics, catalog=reader.catalog, asset_kind=access.asset.kind, version=reader.api_version
        )
        if not selection.native:
            return InsightsRead(series=(), unresolved=selection.unresolved)
        series = await reader.read(
            access.asset, access.token, metrics=selection.native, period=period, window=window
        )
        labelled = [
            MetricSeries(
                name=s.name,
                period=s.period,
                points=s.points,
                canonical=s.canonical
                or reader.catalog.canonical_for(access.asset.kind, s.name, reader.api_version),
            )
            for s in series
        ]
        return InsightsRead(series=labelled, unresolved=selection.unresolved)
