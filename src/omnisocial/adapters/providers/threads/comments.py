"""Respuestas a los posts de la cuenta: leer, responder y ocultar."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.threads.client import ThreadsClient, as_str, parse_time, unwrap
from omnisocial.adapters.providers.threads.config import THREADS
from omnisocial.application.ports import CommentGateway
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Comment, CommentAction
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.token import Token

# La API no tiene cómo dar like, y borrar solo se puede lo propio: una respuesta ajena se oculta.
_OFFERED = frozenset({CommentAction.REPLY, CommentAction.HIDE})
_FIELDS = "id,text,username,timestamp,permalink,hide_status,has_replies,is_reply_owned_by_me"
_VISIBLE = "NOT_HUSHED"


def _comment(item: dict[str, object], object_id: str) -> Comment:
    status = as_str(item.get("hide_status"))
    return Comment(
        external_id=str(item["id"]),
        object_external_id=object_id,
        created_at=parse_time(item.get("timestamp")),
        text=as_str(item.get("text")),
        # Threads identifica al autor por su nombre de usuario: no da un id.
        author_name=as_str(item.get("username")),
        hidden=status != _VISIBLE if status else None,
        raw=item,
    )


class ThreadsCommentGateway(CommentGateway):
    def __init__(self, client: ThreadsClient) -> None:
        self._client = client

    @override
    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]:
        """Las respuestas directas, de la más vieja a la más nueva. Con el id de una respuesta devuelve
        las suyas."""
        query: dict[str, str | int] = {
            "fields": _FIELDS,
            "reverse": "false",
            "limit": self._client.config.page_size,
        }
        comments: list[Comment] = []
        async for page in self._client.pages(f"{object_id}/replies", token.access_token, query):
            comments.extend(
                _comment(item, object_id)
                for item in page
                # Las respuestas de la propia cuenta (un hilo, por ejemplo) no son comentarios.
                if item.get("id") and item.get("is_reply_owned_by_me") is not True
            )
        return comments

    @override
    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        fields = {
            "media_type": "TEXT",
            "text": text,
            "reply_to_id": comment_id,
            # Un post de texto sale en un solo paso.
            "auto_publish_text": "true",
        }
        response = await self._client.post(f"{asset.external_id}/threads", token.access_token, fields)
        reply_id = as_str(unwrap(response).get("id"))
        if reply_id is None:
            raise ProviderError(THREADS, "Threads no devolvió el id de la respuesta.")
        return reply_id

    @override
    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None:
        response = await self._client.post(
            f"{comment_id}/manage_reply", token.access_token, {"hide": "true" if hidden else "false"}
        )
        unwrap(response)

    @override
    async def delete(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        raise ProviderError(THREADS, "Threads no deja borrar la respuesta de otra cuenta: se puede ocultar.")

    @override
    async def like(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        raise ProviderError(THREADS, "La API de Threads no permite dar like.")

    @override
    def supports(self, asset: Asset, action: CommentAction) -> bool:
        return action in _OFFERED
