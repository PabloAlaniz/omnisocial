"""La bandeja: comentarios, mensajes y reseñas de cualquier red, con la misma forma.

Lo que llega a una marca se parece en todas las redes: alguien escribió algo, en algún hilo, y espera
respuesta. Acá se le da una sola forma, venga de una lectura o de un aviso.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from omnisocial.domain.content import Comment
from omnisocial.domain.messaging import Attachment, Message
from omnisocial.domain.provider import ProviderId
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent


class InboxKind(StrEnum):
    COMMENT = "comment"
    MESSAGE = "message"
    REVIEW = "review"
    MENTION = "mention"


@dataclass(frozen=True, slots=True)
class InboxItem:
    kind: InboxKind
    provider: ProviderId
    asset_external_id: str
    external_id: str
    """El id del comentario, del mensaje o de la reseña. Es con lo que se responde un comentario."""
    thread_external_id: str | None
    """Dónde está: la publicación (o el comentario) al que responde, la conversación o la sede. Es con lo
    que se responde un mensaje."""
    created_at: datetime | None
    text: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    from_asset: bool = False
    """Lo escribió la marca. Sirve para saber si lo último de un hilo ya es una respuesta."""
    rating: int | None = None
    attachments: tuple[Attachment, ...] = ()
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)


def from_comment(provider: ProviderId, asset_external_id: str, comment: Comment) -> Iterator[InboxItem]:
    """El comentario y, aplanadas, sus respuestas. Con estrellas es una reseña."""
    yield InboxItem(
        kind=InboxKind.REVIEW if comment.rating is not None else InboxKind.COMMENT,
        provider=provider,
        asset_external_id=asset_external_id,
        external_id=comment.external_id,
        thread_external_id=comment.object_external_id or None,
        created_at=comment.created_at,
        text=comment.text,
        author_id=comment.author_id,
        author_name=comment.author_name,
        rating=comment.rating,
        raw=comment.raw,
    )
    for reply in comment.replies:
        yield from from_comment(provider, asset_external_id, reply)


def from_message(provider: ProviderId, asset_external_id: str, message: Message) -> InboxItem:
    return InboxItem(
        kind=InboxKind.MESSAGE,
        provider=provider,
        asset_external_id=asset_external_id,
        external_id=message.external_id,
        thread_external_id=message.conversation_external_id,
        created_at=message.created_at,
        text=message.text,
        author_id=message.sender_id,
        from_asset=message.from_asset,
        attachments=message.attachments,
        raw=message.raw,
    )


_EVENT_KINDS = {
    EventKind.COMMENT: InboxKind.COMMENT,
    EventKind.MESSAGE: InboxKind.MESSAGE,
    EventKind.MENTION: InboxKind.MENTION,
}


def from_event(event: SocialEvent) -> InboxItem | None:
    """Lo que un aviso suma a la bandeja: algo nuevo que alguien escribió. Una edición, un borrado o el
    estado de un mensaje enviado no suman nada: devuelve `None`."""
    kind = _EVENT_KINDS.get(event.kind)
    if kind is None or event.action is not EventAction.CREATED or event.object_external_id is None:
        return None
    return InboxItem(
        kind=kind,
        provider=event.provider,
        asset_external_id=event.asset_external_id,
        external_id=event.object_external_id,
        thread_external_id=event.conversation_external_id,
        created_at=event.occurred_at,
        text=event.text,
        author_id=event.actor_id,
        author_name=event.actor_name,
        attachments=event.attachments,
        raw=event.raw,
    )


def arrange(items: Iterable[InboxItem], *, since: datetime | None = None) -> tuple[InboxItem, ...]:
    """Sin repetidos, desde `since` y de lo más nuevo a lo más viejo. Lo que no tiene fecha queda al final."""
    unique: dict[tuple[InboxKind, str], InboxItem] = {}
    for item in items:
        if since is not None and item.created_at is not None and item.created_at < since:
            continue
        unique.setdefault((item.kind, item.external_id), item)
    dated = sorted(
        (item for item in unique.values() if item.created_at is not None),
        key=lambda item: item.created_at or datetime.min,  # noqa: DTZ901  # nunca se usa: ya se filtró
        reverse=True,
    )
    return (*dated, *(item for item in unique.values() if item.created_at is None))
