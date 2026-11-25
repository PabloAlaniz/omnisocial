"""Comentarios de los videos del canal: leer, responder y moderar.

Escribir cuesta 50 unidades de cuota por llamada y necesita el permiso `youtube.force-ssl`.
"""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.youtube.client import (
    WRITE,
    YouTubeClient,
    api_error,
    as_dict,
    as_int,
    as_list,
    as_str,
    error_reason,
    parse_time,
    unwrap,
)
from omnisocial.adapters.providers.youtube.config import YOUTUBE
from omnisocial.adapters.providers.youtube.spec import COMMENTS_DISABLED
from omnisocial.application.ports import CommentGateway
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Comment, CommentAction
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.token import Token

_FORBIDDEN = 403
_CLIENT_ERROR = 400
_OFFERED = frozenset({CommentAction.REPLY, CommentAction.HIDE, CommentAction.DELETE})


def _comment(node: dict[str, object], parent_id: str, replies: tuple[Comment, ...] = ()) -> Comment:
    snippet = as_dict(node.get("snippet"))
    status = as_str(snippet.get("moderationStatus"))
    return Comment(
        external_id=str(node["id"]),
        object_external_id=parent_id,
        created_at=parse_time(snippet.get("publishedAt")),
        # `textOriginal` solo se le muestra al autor del comentario.
        text=as_str(snippet.get("textOriginal")) or as_str(snippet.get("textDisplay")),
        author_id=as_str(as_dict(snippet.get("authorChannelId")).get("value")),
        author_name=as_str(snippet.get("authorDisplayName")),
        like_count=as_int(snippet.get("likeCount")),
        hidden=status != "published" if status else None,
        replies=replies,
        raw=node,
    )


def _thread(thread: dict[str, object], video_id: str) -> Comment | None:
    snippet = as_dict(thread.get("snippet"))
    top = as_dict(snippet.get("topLevelComment"))
    if not top.get("id"):
        return None
    top_id = str(top["id"])
    # Puede venir solo una parte de las respuestas; `reply_count` dice cuántas hay en total.
    replies = tuple(
        _comment(reply, top_id)
        for reply in as_list(as_dict(thread.get("replies")).get("comments"))
        if reply.get("id")
    )
    comment = _comment(top, video_id, replies)
    return Comment(
        external_id=comment.external_id,
        object_external_id=video_id,
        created_at=comment.created_at,
        text=comment.text,
        author_id=comment.author_id,
        author_name=comment.author_name,
        like_count=comment.like_count,
        reply_count=as_int(snippet.get("totalReplyCount")),
        hidden=comment.hidden,
        replies=replies,
        raw=thread,
    )


class YouTubeCommentGateway(CommentGateway):
    def __init__(self, client: YouTubeClient) -> None:
        self._client = client

    @override
    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]:
        query: dict[str, str | int] = {
            "part": "snippet,replies",
            "videoId": object_id,
            "maxResults": self._client.config.comments_page_size,
            "textFormat": "plainText",
        }
        comments: list[Comment] = []
        while True:
            response = await self._client.call("GET", "commentThreads", token.access_token, params=query)
            if response.status == _FORBIDDEN and error_reason(response) == COMMENTS_DISABLED:
                # No es un error: el video tiene los comentarios desactivados.
                return []
            page = unwrap(response)
            threads = (_thread(item, object_id) for item in as_list(page.get("items")))
            comments.extend(thread for thread in threads if thread is not None)
            next_token = as_str(page.get("nextPageToken"))
            if next_token is None:
                return comments
            query["pageToken"] = next_token

    @override
    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        body = {"snippet": {"parentId": comment_id, "textOriginal": text}}
        created = await self._client.write(
            "POST", "comments", token.access_token, params={"part": "snippet"}, json=body
        )
        reply_id = as_str(created.get("id"))
        if reply_id is None:
            raise ProviderError(YOUTUBE, "YouTube no devolvió el id de la respuesta.")
        return reply_id

    @override
    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None:
        """Ocultar es retenerlo para revisión: deja de verse y se puede volver a publicar."""
        await self._moderate(token, comment_id, "heldForReview" if hidden else "published")

    @override
    async def delete(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        """Rechazarlo: lo saca para todos, con sus respuestas, y no tiene vuelta atrás.

        La API solo deja borrar de verdad un comentario a su autor; para los de otros, moderar es lo que hay.
        """
        await self._moderate(token, comment_id, "rejected")

    @override
    async def like(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        raise ProviderError(YOUTUBE, "La API de YouTube no permite dar like a un comentario.")

    @override
    def supports(self, asset: Asset, action: CommentAction) -> bool:
        return action in _OFFERED

    async def _moderate(self, token: Token, comment_id: str, status: str) -> None:
        response = await self._client.call(
            "POST",
            "comments/setModerationStatus",
            token.access_token,
            params={"id": comment_id, "moderationStatus": status},
            cost=WRITE,
        )
        if response.status >= _CLIENT_ERROR:
            raise api_error(response)
