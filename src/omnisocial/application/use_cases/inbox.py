"""La bandeja de un activo: lo que le escribieron, venga de donde venga."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from omnisocial.application.registry import ProviderRegistry
from omnisocial.application.results import Done, Refusal, Refused
from omnisocial.application.use_cases.access import ResolveAssetAccess
from omnisocial.application.use_cases.operations import (
    ListComments,
    ListConversations,
    ListMessages,
    ListPosts,
)
from omnisocial.domain.asset import Asset
from omnisocial.domain.inbox import InboxItem, arrange, from_comment, from_message

_STOP = frozenset(
    {
        Refusal.NOT_FOUND,
        Refusal.CONNECTION_EXPIRED,
        Refusal.CONNECTION_INVALID,
        Refusal.CONNECTION_REVOKED,
    }
)
"""Con estas no tiene sentido seguir: el activo no existe o su conexión no sirve."""


@dataclass(frozen=True, slots=True)
class Skipped:
    source: str
    """`comments` o `messages`."""
    refused: Refused


@dataclass(frozen=True, slots=True)
class Inbox:
    items: tuple[InboxItem, ...]
    """De lo más nuevo a lo más viejo."""
    skipped: tuple[Skipped, ...] = ()
    """Lo que no se pudo leer y por qué (un permiso que falta, un límite de uso). Lo demás sí vino."""


@dataclass(frozen=True, slots=True)
class InboxSources:
    posts: ListPosts
    comments: ListComments
    conversations: ListConversations
    messages: ListMessages


class _Stop(Exception):
    def __init__(self, refused: Refused) -> None:
        super().__init__(refused.reason)
        self.refused = refused


class ReadInbox:
    """Junta los comentarios de las últimas publicaciones, las reseñas y los mensajes de un activo.

    Es una lectura: sirve para llenar la bandeja al conectar una cuenta o para ponerse al día. Lo que
    llega después conviene recibirlo por avisos (`from_event`), que no gastan cuota.

    Hace varias llamadas a la red: una por publicación y una por conversación. `posts` y `conversations`
    dicen cuántas mirar. Las redes que no dejan leer sus mensajes (WhatsApp, Telegram) no aportan nada
    acá: sus mensajes solo llegan por avisos.
    """

    def __init__(
        self, *, registry: ProviderRegistry, access: ResolveAssetAccess, sources: InboxSources
    ) -> None:
        self._registry = registry
        self._access = access
        self._sources = sources

    async def execute(
        self, asset_id: str, *, since: datetime | None = None, posts: int = 10, conversations: int = 10
    ) -> Done[Inbox] | Refused:
        access = await self._access.execute(asset_id)
        if isinstance(access, Refused):
            return access
        asset = access.asset
        items: list[InboxItem] = []
        skipped: list[Skipped] = []
        try:
            found = {
                "comments": await self._comments(asset, posts),
                "messages": await self._messages(asset, conversations),
            }
        except _Stop as stop:
            return stop.refused
        for source, read in found.items():
            if isinstance(read, Refused):
                skipped.append(Skipped(source, read))
            else:
                items.extend(read)
        return Done(Inbox(arrange(items, since=since), tuple(skipped)))

    @staticmethod
    def _check(result: Done[Sequence[object]] | Refused) -> Refused | None:
        """`None` si se leyó. Una negativa que corta todo se lanza; "no lo soporta" no es un problema."""
        if not isinstance(result, Refused):
            return None
        if result.reason in _STOP:
            raise _Stop(result)
        return result

    async def _comments(self, asset: Asset, posts: int) -> list[InboxItem] | Refused:
        spec = self._registry.get(asset.provider).spec
        if spec is not None and asset.kind in spec.asset_comments:
            # Reseñas: son del activo, no de una publicación.
            targets = [asset.external_id]
        else:
            listed = await self._sources.posts.execute(asset.id, limit=posts)
            refused = self._check(listed)  # type: ignore[arg-type]
            if refused is not None or isinstance(listed, Refused):
                return _unless_unsupported(refused)
            targets = [post.external_id for post in listed.value]
        items: list[InboxItem] = []
        for target in targets:
            comments = await self._sources.comments.execute(asset.id, object_id=target)
            refused = self._check(comments)  # type: ignore[arg-type]
            if refused is not None or isinstance(comments, Refused):
                return _unless_unsupported(refused)
            for comment in comments.value:
                items.extend(from_comment(asset.provider, asset.external_id, comment))
        return items

    async def _messages(self, asset: Asset, conversations: int) -> list[InboxItem] | Refused:
        listed = await self._sources.conversations.execute(asset.id, limit=conversations)
        refused = self._check(listed)  # type: ignore[arg-type]
        if refused is not None or isinstance(listed, Refused):
            return _unless_unsupported(refused)
        items: list[InboxItem] = []
        for conversation in listed.value:
            messages = await self._sources.messages.execute(
                asset.id, conversation_id=conversation.external_id
            )
            refused = self._check(messages)  # type: ignore[arg-type]
            if refused is not None or isinstance(messages, Refused):
                return _unless_unsupported(refused)
            items.extend(from_message(asset.provider, asset.external_id, m) for m in messages.value)
        return items


def _unless_unsupported(refused: Refused | None) -> list[InboxItem] | Refused:
    """Que la red no tenga comentarios o mensajes no es algo que avisar: simplemente no aporta."""
    if refused is None or refused.reason is Refusal.NOT_SUPPORTED:
        return []
    return refused
