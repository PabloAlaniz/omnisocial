"""Comentarios: leer, responder y ocultar, en páginas y en Instagram."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.meta.config import INSTAGRAM_ACCOUNT, META
from omnisocial.adapters.providers.meta.graph import (
    GraphClient,
    as_dict,
    as_int,
    as_list,
    as_str,
    parse_time,
)
from omnisocial.application.ports import CommentGateway
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Comment
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.token import Token

PAGE_COMMENT_FIELDS = "id,message,from{id,name},created_time,like_count,comment_count,is_hidden,parent{id}"
_IG_FIELDS = "id,text,username,timestamp,like_count,hidden,from{id,username}"
INSTAGRAM_COMMENT_FIELDS = f"{_IG_FIELDS},replies{{{_IG_FIELDS}}}"


def _page_comment(item: dict[str, object], object_id: str) -> Comment:
    author = as_dict(item.get("from"))
    parent = as_str(as_dict(item.get("parent")).get("id"))
    hidden = item.get("is_hidden")
    return Comment(
        external_id=str(item["id"]),
        object_external_id=parent or object_id,
        created_at=parse_time(item.get("created_time")),
        text=as_str(item.get("message")),
        author_id=as_str(author.get("id")),
        author_name=as_str(author.get("name")),
        like_count=as_int(item.get("like_count")),
        reply_count=as_int(item.get("comment_count")),
        hidden=hidden if isinstance(hidden, bool) else None,
        raw=item,
    )


def _instagram_comment(item: dict[str, object], object_id: str) -> Comment:
    author = as_dict(item.get("from"))
    hidden = item.get("hidden")
    replies = tuple(
        _instagram_comment(reply, str(item["id"]))
        for reply in as_list(as_dict(item.get("replies")).get("data"))
        if as_str(reply.get("id"))
    )
    return Comment(
        external_id=str(item["id"]),
        object_external_id=object_id,
        created_at=parse_time(item.get("timestamp")),
        text=as_str(item.get("text")),
        author_id=as_str(author.get("id")),
        author_name=as_str(item.get("username")) or as_str(author.get("username")),
        like_count=as_int(item.get("like_count")),
        reply_count=len(replies),
        hidden=hidden if isinstance(hidden, bool) else None,
        replies=replies,
        raw=item,
    )


class MetaCommentGateway(CommentGateway):
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    @override
    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]:
        if asset.kind == INSTAGRAM_ACCOUNT:
            items = await self._graph.collect(
                f"{object_id}/comments", token.access_token, {"fields": INSTAGRAM_COMMENT_FIELDS, "limit": 50}
            )
            return [_instagram_comment(item, object_id) for item in items if as_str(item.get("id"))]
        items = await self._graph.collect(
            f"{object_id}/comments",
            token.access_token,
            {"fields": PAGE_COMMENT_FIELDS, "filter": "stream", "limit": 100},
        )
        return [_page_comment(item, object_id) for item in items if as_str(item.get("id"))]

    @override
    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        edge = "replies" if asset.kind == INSTAGRAM_ACCOUNT else "comments"
        body = await self._graph.post(f"{comment_id}/{edge}", token.access_token, params={"message": text})
        new_id = as_str(body.get("id"))
        if not new_id:
            raise ProviderError(META, "Meta no devolvió el id de la respuesta.")
        return new_id

    @override
    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None:
        key = "hide" if asset.kind == INSTAGRAM_ACCOUNT else "is_hidden"
        await self._graph.post(comment_id, token.access_token, params={key: "true" if hidden else "false"})
