"""Lo que se hace con un activo: leer publicaciones, comentarios, mensajes y métricas, y responder."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from omnisocial.application.ports import Clock
from omnisocial.application.registry import Provider, ProviderRegistry
from omnisocial.application.results import AssetAccess, Done, InsightsRead, Refusal, Refused, refusal_for
from omnisocial.application.use_cases.access import ResolveAssetAccess
from omnisocial.domain.content import Comment, CommentAction, Post
from omnisocial.domain.errors import ProviderError, TokenRejected
from omnisocial.domain.lookup import Choice, LookupSpec
from omnisocial.domain.messaging import Conversation, Message, last_inbound_at
from omnisocial.domain.metrics import CanonicalMetric, MetricSeries, Period, select_metrics
from omnisocial.domain.provider import Capability
from omnisocial.domain.window import TimeWindow

_ALL_TIME = TimeWindow()

R = TypeVar("R")


Call = Callable[[Provider, AssetAccess], Awaitable[R | Refused]]


class _AssetOperation:
    capability: Capability

    def __init__(self, *, registry: ProviderRegistry, access: ResolveAssetAccess) -> None:
        self._registry = registry
        self._access = access

    async def _run(self, asset_id: str, call: Call[R]) -> R | Refused:
        """Abre el activo y hace la llamada a la red, traduciendo lo que la red decide a resultados.

        Un token rechazado deja la conexión inválida. Un permiso faltante, un límite de uso o la cuota
        agotada vuelven como negativa: la conexión sigue sana y reintentar en el momento no lo arregla.
        """
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        provider, access = opened
        try:
            return await call(provider, access)
        except TokenRejected as error:
            return await self._access.reject(access, error)
        except ProviderError as error:
            refused = refusal_for(error, self.capability)
            if refused is None:
                raise
            return refused

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
        async def call(provider: Provider, access: AssetAccess) -> Done[Sequence[Post]]:
            content = provider.require_content()
            return Done(await content.list_posts(access.asset, access.token, window=window, limit=limit))

        return await self._run(asset_id, call)


class ListChoices(_AssetOperation):
    """Lo que hay que elegir antes de publicar en un activo: tableros, comunidades, etiquetas.

    Qué consultas ofrece cada tipo de activo lo declara la red en su descripción (`spec.lookups`).
    """

    capability = Capability.PUBLISHING

    async def available(self, asset_id: str) -> Done[tuple[LookupSpec, ...]] | Refused:
        """Las consultas que ofrece ese activo. Vacío si no hay nada que elegir."""
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        provider, access = opened
        return Done(_lookups(provider, access.asset.kind))

    async def execute(
        self, asset_id: str, lookup: str, *, query: str | None = None, parent: str | None = None
    ) -> Done[Sequence[Choice]] | Refused:
        async def call(provider: Provider, access: AssetAccess) -> Done[Sequence[Choice]] | Refused:
            declared = next((s for s in _lookups(provider, access.asset.kind) if s.name == lookup), None)
            if declared is None or provider.lookups is None:
                return Refused(Refusal.UNKNOWN_LOOKUP, detail=lookup, capability=self.capability)
            if declared.parent is not None and not parent:
                return Refused(Refusal.PARENT_REQUIRED, detail=declared.parent, capability=self.capability)
            found = await provider.lookups.choices(
                access.asset, access.token, lookup=lookup, query=query or None, parent=parent
            )
            return Done(found)

        return await self._run(asset_id, call)


def _lookups(provider: Provider, kind: str) -> tuple[LookupSpec, ...]:
    if provider.spec is None or provider.lookups is None:
        return ()
    return provider.spec.lookups.get(kind, ())


class ListComments(_AssetOperation):
    capability = Capability.COMMENTS

    async def execute(self, asset_id: str, *, object_id: str) -> Done[Sequence[Comment]] | Refused:
        async def call(provider: Provider, access: AssetAccess) -> Done[Sequence[Comment]]:
            comments = provider.require_comments()
            return Done(await comments.list_comments(access.asset, access.token, object_id=object_id))

        return await self._run(asset_id, call)


class _CommentAction(_AssetOperation):
    """Una acción sobre un comentario. Antes de llamar a la red se fija si la red la ofrece para el activo."""

    capability = Capability.COMMENTS
    action: CommentAction

    async def _act(self, asset_id: str, act: Call[R]) -> R | Refused:
        async def call(provider: Provider, access: AssetAccess) -> R | Refused:
            if not provider.require_comments().supports(access.asset, self.action):
                return Refused(
                    Refusal.ACTION_NOT_OFFERED, detail=str(self.action), capability=self.capability
                )
            return await act(provider, access)

        return await self._run(asset_id, call)


class ReplyToComment(_CommentAction):
    action = CommentAction.REPLY

    async def execute(self, asset_id: str, *, comment_id: str, text: str) -> Done[str] | Refused:
        async def call(provider: Provider, access: AssetAccess) -> Done[str]:
            comments = provider.require_comments()
            return Done(await comments.reply(access.asset, access.token, comment_id=comment_id, text=text))

        return await self._act(asset_id, call)


class SetCommentHidden(_CommentAction):
    action = CommentAction.HIDE

    async def execute(self, asset_id: str, *, comment_id: str, hidden: bool) -> Done[None] | Refused:
        async def call(provider: Provider, access: AssetAccess) -> Done[None]:
            comments = provider.require_comments()
            await comments.set_hidden(access.asset, access.token, comment_id=comment_id, hidden=hidden)
            return Done(None)

        return await self._act(asset_id, call)


class DeleteComment(_CommentAction):
    action = CommentAction.DELETE

    async def execute(self, asset_id: str, *, comment_id: str) -> Done[None] | Refused:
        async def call(provider: Provider, access: AssetAccess) -> Done[None]:
            await provider.require_comments().delete(access.asset, access.token, comment_id=comment_id)
            return Done(None)

        return await self._act(asset_id, call)


class LikeComment(_CommentAction):
    action = CommentAction.LIKE

    async def execute(self, asset_id: str, *, comment_id: str) -> Done[None] | Refused:
        async def call(provider: Provider, access: AssetAccess) -> Done[None]:
            await provider.require_comments().like(access.asset, access.token, comment_id=comment_id)
            return Done(None)

        return await self._act(asset_id, call)


class ListConversations(_AssetOperation):
    capability = Capability.MESSAGING

    async def execute(
        self, asset_id: str, *, limit: int | None = None
    ) -> Done[Sequence[Conversation]] | Refused:
        async def call(provider: Provider, access: AssetAccess) -> Done[Sequence[Conversation]]:
            messaging = provider.require_messaging()
            return Done(await messaging.list_conversations(access.asset, access.token, limit=limit))

        return await self._run(asset_id, call)


class ListMessages(_AssetOperation):
    capability = Capability.MESSAGING

    async def execute(
        self, asset_id: str, *, conversation_id: str, limit: int | None = None
    ) -> Done[Sequence[Message]] | Refused:
        async def call(provider: Provider, access: AssetAccess) -> Done[Sequence[Message]]:
            messages = await provider.require_messaging().list_messages(
                access.asset, access.token, conversation_id=conversation_id, limit=limit
            )
            return Done(messages)

        return await self._run(asset_id, call)


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
        async def call(provider: Provider, access: AssetAccess) -> Done[str] | Refused:
            messaging = provider.require_messaging()
            messages = await messaging.list_messages(
                access.asset, access.token, conversation_id=conversation_id, limit=None
            )
            latest = last_inbound_at(messages)
            recipient = next(
                (
                    m.sender_id
                    for m in messages
                    if not m.from_asset and m.created_at == latest and m.sender_id
                ),
                None,
            )
            if latest is None or recipient is None:
                return Refused(Refusal.NO_RECIPIENT)
            if not messaging.reply_window.allows(latest, self._clock.now()):
                return Refused(Refusal.OUTSIDE_REPLY_WINDOW)
            return Done(await messaging.send(access.asset, access.token, recipient_id=recipient, text=text))

        return await self._run(asset_id, call)


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
        async def call(provider: Provider, access: AssetAccess) -> InsightsRead:
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

        return await self._run(asset_id, call)
