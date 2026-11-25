"""Respuestas a los posts de la cuenta: leer, responder, ocultar y dar like.

Las respuestas se buscan en la conversación del post, y la búsqueda de X solo llega a los últimos 7 días.
"""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.x.client import XClient, as_dict, as_int, as_list, as_str, parse_time
from omnisocial.adapters.providers.x.config import X
from omnisocial.application.ports import CommentGateway
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Comment, CommentAction
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.token import Token

# Borrar solo se puede lo propio: una respuesta ajena se oculta, no se borra.
_OFFERED = frozenset({CommentAction.REPLY, CommentAction.HIDE, CommentAction.LIKE})
_FIELDS = "created_at,public_metrics,conversation_id,author_id,in_reply_to_user_id"


def _comment(item: dict[str, object], object_id: str, authors: dict[str, str]) -> Comment:
    metrics = as_dict(item.get("public_metrics"))
    author = as_str(item.get("author_id"))
    return Comment(
        external_id=str(item["id"]),
        object_external_id=object_id,
        created_at=parse_time(item.get("created_at")),
        text=as_str(item.get("text")),
        author_id=author,
        author_name=authors.get(author or ""),
        like_count=as_int(metrics.get("like_count")),
        reply_count=as_int(metrics.get("reply_count")),
        raw=item,
    )


class XCommentGateway(CommentGateway):
    def __init__(self, client: XClient) -> None:
        self._client = client

    @override
    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]:
        query: dict[str, str | int] = {
            "query": f"conversation_id:{object_id} is:reply",
            "max_results": self._client.config.page_size,
            self._client.config.post_fields_param: _FIELDS,
            "expansions": "author_id",
            "user.fields": "username,name",
        }
        comments: list[Comment] = []
        async for page in self._client.pages("tweets/search/recent", token.access_token, query):
            users = as_list(as_dict(page.get("includes")).get("users"))
            authors = {str(u["id"]): as_str(u.get("username")) or "" for u in users if u.get("id")}
            comments.extend(
                _comment(item, object_id, authors)
                for item in as_list(page.get("data"))
                # Las respuestas de la propia cuenta (un hilo, por ejemplo) no son comentarios.
                if item.get("id") and item.get("author_id") != asset.external_id
            )
        return comments

    @override
    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        body = {"text": text, "reply": {"in_reply_to_tweet_id": comment_id}}
        response = await self._client.call("POST", "tweets", token.access_token, json=body)
        created = as_dict(self._client.unwrap(response).get("data"))
        reply_id = as_str(created.get("id"))
        if reply_id is None:
            raise ProviderError(X, "X no devolvió el id de la respuesta.")
        return reply_id

    @override
    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None:
        response = await self._client.call(
            "PUT", f"tweets/{comment_id}/hidden", token.access_token, json={"hidden": hidden}
        )
        self._client.unwrap(response)

    @override
    async def delete(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        raise ProviderError(X, "X no deja borrar la respuesta de otra cuenta: se puede ocultar.")

    @override
    async def like(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        response = await self._client.call(
            "POST", f"users/{asset.external_id}/likes", token.access_token, json={"tweet_id": comment_id}
        )
        self._client.unwrap(response)

    @override
    def supports(self, asset: Asset, action: CommentAction) -> bool:
        return action in _OFFERED
