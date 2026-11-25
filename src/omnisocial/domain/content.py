"""Publicaciones y comentarios."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class CommentAction(StrEnum):
    """Lo que se puede hacer sobre un comentario. No todas las redes ofrecen todas para todos los activos."""

    REPLY = "reply"
    HIDE = "hide"
    DELETE = "delete"
    LIKE = "like"


@dataclass(frozen=True, slots=True)
class Post:
    external_id: str
    asset_external_id: str
    created_at: datetime | None
    text: str | None = None
    permalink: str | None = None
    media_type: str | None = None
    media_url: str | None = None
    like_count: int | None = None
    """`None` quiere decir que la red no lo informó, no que sea cero."""
    comment_count: int | None = None
    share_count: int | None = None
    view_count: int | None = None
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)


@dataclass(frozen=True, slots=True)
class Comment:
    external_id: str
    object_external_id: str
    """La publicación (o el comentario) al que responde."""
    created_at: datetime | None
    text: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    like_count: int | None = None
    reply_count: int | None = None
    hidden: bool | None = None
    rating: int | None = None
    """Si es una reseña, cuántas estrellas puso (de 1 a 5)."""
    replies: tuple[Comment, ...] = ()
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)
