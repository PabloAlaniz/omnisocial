"""Respuestas a los posts de la cuenta: leer, responder y dar like.

Para responder o dar like hace falta el contenido exacto del post (`cid`), además de su dirección (`uri`):
se le pide a Bluesky antes.
"""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.bluesky.client import (
    BlueskyClient,
    as_dict,
    as_int,
    as_list,
    as_str,
    iso,
    parse_time,
)
from omnisocial.adapters.providers.bluesky.config import BLUESKY, LIKE, POST
from omnisocial.adapters.providers.bluesky.richtext import facets
from omnisocial.application.ports import CommentGateway
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Comment, CommentAction
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.token import Token

# Ocultar una respuesta existe, pero es editar una regla del hilo entero: todavía no se ofrece. Borrar
# solo se puede lo propio.
_OFFERED = frozenset({CommentAction.REPLY, CommentAction.LIKE})


def _comment(view: dict[str, object], object_id: str) -> Comment:
    record = as_dict(view.get("record"))
    author = as_dict(view.get("author"))
    return Comment(
        external_id=str(view["uri"]),
        object_external_id=object_id,
        created_at=parse_time(record.get("createdAt")),
        text=as_str(record.get("text")),
        author_id=as_str(author.get("did")),
        author_name=as_str(author.get("handle")),
        like_count=as_int(view.get("likeCount")),
        reply_count=as_int(view.get("replyCount")),
        raw=view,
    )


def reference(view: dict[str, object]) -> dict[str, str]:
    return {"uri": str(view.get("uri") or ""), "cid": str(view.get("cid") or "")}


class BlueskyCommentGateway(CommentGateway):
    def __init__(self, client: BlueskyClient) -> None:
        self._client = client

    @override
    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]:
        """Las respuestas directas. Con la dirección de una respuesta devuelve las suyas."""
        data = await self._client.get("app.bsky.feed.getPostThread", token, {"uri": object_id, "depth": 1})
        replies = as_list(as_dict(data.get("thread")).get("replies"))
        views = (as_dict(reply.get("post")) for reply in replies)
        return [
            _comment(view, object_id)
            for view in views
            # Una respuesta borrada o bloqueada viene sin post. Las de la propia cuenta (un hilo) no son
            # comentarios.
            if view.get("uri") and as_dict(view.get("author")).get("did") != asset.external_id
        ]

    async def view(self, token: Token, uri: str) -> dict[str, object]:
        data = await self._client.get("app.bsky.feed.getPosts", token, {"uris": uri})
        posts = as_list(data.get("posts"))
        if not posts or not posts[0].get("cid"):
            raise ProviderError(BLUESKY, "El post ya no existe en Bluesky.")
        return posts[0]

    async def _create(self, asset: Asset, token: Token, collection: str, record: dict[str, object]) -> str:
        body = {"repo": asset.external_id, "collection": collection, "record": record}
        response = await self._client.call("com.atproto.repo.createRecord", token, body)
        uri = as_str(self._client.unwrap(response).get("uri"))
        if uri is None:
            raise ProviderError(BLUESKY, "Bluesky no devolvió la dirección de lo que se creó.")
        return uri

    @override
    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        parent = await self.view(token, comment_id)
        # La raíz del hilo es la del post al que se responde; si no tiene, es ese post.
        root = as_dict(as_dict(as_dict(parent.get("record")).get("reply")).get("root")) or reference(parent)
        record: dict[str, object] = {
            "$type": POST,
            "text": text,
            "createdAt": iso(self._client.clock.now()),
            "reply": {"root": root, "parent": reference(parent)},
        }
        marks = facets(text)
        if marks:
            record["facets"] = marks
        return await self._create(asset, token, POST, record)

    @override
    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None:
        raise ProviderError(BLUESKY, "Ocultar una respuesta en Bluesky todavía no se ofrece.")

    @override
    async def delete(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        raise ProviderError(BLUESKY, "Bluesky no deja borrar la respuesta de otra cuenta.")

    @override
    async def like(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        subject = reference(await self.view(token, comment_id))
        record: dict[str, object] = {
            "$type": LIKE,
            "subject": subject,
            "createdAt": iso(self._client.clock.now()),
        }
        await self._create(asset, token, LIKE, record)

    @override
    def supports(self, asset: Asset, action: CommentAction) -> bool:
        return action in _OFFERED
