"""Comentarios de las publicaciones de una página: leer, responder, borrar y reaccionar.

Un comentario se identifica con su URN, que lleva adentro la publicación:
`urn:li:comment:(urn:li:activity:123,456)`. De ahí salen la publicación y el número del comentario.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.linkedin.client import (
    LinkedInClient,
    as_dict,
    as_int,
    as_str,
    encode,
    from_millis,
    unwrap,
)
from omnisocial.adapters.providers.linkedin.config import LINKEDIN, urn
from omnisocial.application.ports import CommentGateway
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Comment, CommentAction
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.token import Token

_COMMENT_URN = re.compile(r"urn:li:comment:\((urn:li:[A-Za-z]+:[^,()]+),([^,()]+)\)")
# LinkedIn no tiene cómo ocultar un comentario: solo cerrar los comentarios de toda la publicación.
_OFFERED = frozenset({CommentAction.REPLY, CommentAction.DELETE, CommentAction.LIKE})


def _parts(comment_urn: str) -> tuple[str, str]:
    """La publicación y el número del comentario."""
    match = _COMMENT_URN.fullmatch(comment_urn)
    if match is None:
        raise ProviderError(LINKEDIN, f"'{comment_urn}' no es el URN de un comentario de LinkedIn.")
    return match.group(1), match.group(2)


def _comment(node: dict[str, object], object_id: str) -> Comment | None:
    comment_urn = as_str(node.get("commentUrn"))
    if comment_urn is None:
        return None
    return Comment(
        external_id=comment_urn,
        object_external_id=as_str(node.get("parentComment")) or object_id,
        created_at=from_millis(as_dict(node.get("created")).get("time")),
        text=as_str(as_dict(node.get("message")).get("text")),
        author_id=as_str(node.get("actor")),
        like_count=as_int(as_dict(node.get("likesSummary")).get("totalLikes")),
        reply_count=as_int(as_dict(node.get("commentsSummary")).get("aggregatedTotalComments")),
        raw=node,
    )


class LinkedInCommentGateway(CommentGateway):
    def __init__(self, client: LinkedInClient) -> None:
        self._client = client

    @override
    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]:
        """Los comentarios de primer nivel. `object_id` puede ser una publicación o un comentario: con el
        URN de un comentario devuelve sus respuestas."""
        path = f"socialActions/{encode(object_id)}/comments?"
        comments: list[Comment] = []
        async for page in self._client.pages(path, token.access_token):
            found = (_comment(node, object_id) for node in page)
            comments.extend(comment for comment in found if comment is not None)
        return comments

    @override
    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        post, _ = _parts(comment_id)
        body = {
            "actor": urn(asset.kind, asset.external_id),
            "object": post,
            "message": {"text": text},
            "parentComment": comment_id,
        }
        response = await self._client.call(
            "POST", f"socialActions/{encode(post)}/comments", token.access_token, json=body
        )
        created = unwrap(response)
        reply_urn = as_str(created.get("commentUrn")) or response.header("x-restli-id")
        if not reply_urn:
            raise ProviderError(LINKEDIN, "LinkedIn no devolvió el id de la respuesta.")
        return reply_urn

    @override
    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None:
        raise ProviderError(LINKEDIN, "La API de LinkedIn no permite ocultar un comentario.")

    @override
    async def delete(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        post, number = _parts(comment_id)
        actor = encode(urn(asset.kind, asset.external_id))
        path = f"socialActions/{encode(post)}/comments/{encode(number)}?actor={actor}"
        unwrap(await self._client.call("DELETE", path, token.access_token))

    @override
    async def like(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        actor = encode(urn(asset.kind, asset.external_id))
        body = {"root": comment_id, "reactionType": "LIKE"}
        unwrap(await self._client.call("POST", f"reactions?actor={actor}", token.access_token, json=body))

    @override
    def supports(self, asset: Asset, action: CommentAction) -> bool:
        return action in _OFFERED
