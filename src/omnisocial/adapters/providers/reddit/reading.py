"""Lo que se lee de Reddit: la cuenta, sus publicaciones, sus comunidades y los comentarios."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.reddit.client import (
    RedditClient,
    as_dict,
    as_int,
    as_list,
    as_str,
    from_epoch,
)
from omnisocial.adapters.providers.reddit.config import REDDIT, REDDIT_ACCOUNT, SITE, community
from omnisocial.adapters.providers.reddit.oauth import me
from omnisocial.adapters.providers.reddit.spec import ACCOUNT_CAPABILITIES, FLAIRS
from omnisocial.application.ports import AssetDirectory, CommentGateway, ContentReader, LookupReader
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.content import Comment, CommentAction, Post
from omnisocial.domain.errors import ErrorKind, ProviderError
from omnisocial.domain.lookup import Choice
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

USERNAME = "username"
_COMMENT = "t1"
# Dar like es votar, y Reddit pide que los votos los emita una persona: no se ofrece.
_OFFERED = frozenset({CommentAction.REPLY, CommentAction.HIDE, CommentAction.DELETE})
_NOT_THERE = frozenset({403, 404})


def username(asset: Asset) -> str:
    name = asset.metadata.get(USERNAME)
    if not name:
        raise ProviderError(REDDIT, "El activo no tiene el nombre de usuario: hay que sincronizarlo.")
    return name


def post_id(value: str) -> str:
    """El id corto de una publicación, venga como `t3_abc` o como `abc`."""
    return value.removeprefix("t3_")


class RedditAssetDirectory(AssetDirectory):
    def __init__(self, client: RedditClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        external_id, name, _ = await me(self._client, token)
        return [
            DiscoveredAsset(
                REDDIT_ACCOUNT,
                external_id,
                name=f"u/{name}",
                capabilities=ACCOUNT_CAPABILITIES,
                metadata={USERNAME: name},
            )
        ]


def _post(item: dict[str, object], asset: Asset) -> Post:
    title, body = as_str(item.get("title")), as_str(item.get("selftext"))
    path = as_str(item.get("permalink"))
    is_self = item.get("is_self") is True
    return Post(
        external_id=str(item["name"]),
        asset_external_id=asset.external_id,
        created_at=from_epoch(item.get("created_utc")),
        text="\n\n".join(part for part in (title, body) if part) or None,
        permalink=f"{SITE}{path}" if path else None,
        media_type="self" if is_self else "link",
        media_url=None if is_self else as_str(item.get("url")),
        like_count=as_int(item.get("score")),
        comment_count=as_int(item.get("num_comments")),
        raw=item,
    )


class RedditContentReader(ContentReader):
    def __init__(self, client: RedditClient) -> None:
        self._client = client

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        """Las publicaciones de la cuenta en cualquier comunidad, de la más nueva a la más vieja."""
        posts: list[Post] = []
        path = f"user/{username(asset)}/submitted"
        async for page in self._client.listing(path, token.access_token, {"sort": "new"}):
            for post in (_post(item, asset) for item in page if as_str(item.get("name"))):
                if window.is_before(post.created_at):
                    return posts
                if window.contains(post.created_at):
                    posts.append(post)
                if limit is not None and len(posts) >= limit:
                    return posts
        return posts


def _comment(item: dict[str, object]) -> Comment:
    children = as_list(as_dict(as_dict(item.get("replies")).get("data")).get("children"))
    replies = tuple(_comment(as_dict(c.get("data"))) for c in children if c.get("kind") == _COMMENT)
    return Comment(
        external_id=str(item.get("name")),
        object_external_id=as_str(item.get("parent_id")) or "",
        created_at=from_epoch(item.get("created_utc")),
        text=as_str(item.get("body")),
        author_id=as_str(item.get("author_fullname")),
        author_name=as_str(item.get("author")),
        like_count=as_int(item.get("score")),
        reply_count=len(replies),
        replies=replies,
        raw={key: value for key, value in item.items() if key != "replies"},
    )


class RedditCommentGateway(CommentGateway):
    def __init__(self, client: RedditClient) -> None:
        self._client = client

    @override
    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]:
        """El árbol de comentarios de una publicación, hasta donde Reddit lo manda en un pedido. Las ramas
        que deja para pedir aparte ("cargar más comentarios") no se siguen."""
        data = await self._client.get(
            f"comments/{post_id(object_id)}",
            token.access_token,
            {"limit": self._client.config.page_size, "sort": "new"},
        )
        # La respuesta son dos listados: la publicación y sus comentarios.
        listings = as_list(data)
        children = as_list(as_dict(listings[1].get("data")).get("children")) if len(listings) > 1 else []
        return [_comment(as_dict(c.get("data"))) for c in children if c.get("kind") == _COMMENT]

    @override
    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        data = await self._client.act(
            "api/comment", token.access_token, {"thing_id": comment_id, "text": text}
        )
        things = as_list(data.get("things"))
        name = as_str(as_dict(things[0].get("data")).get("name")) if things else None
        if name is None:
            raise ProviderError(REDDIT, "Reddit no devolvió el id del comentario.")
        return name

    @override
    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None:
        """Quitar un comentario o volver a aprobarlo. Solo en las comunidades que la cuenta modera."""
        if hidden:
            await self._client.act("api/remove", token.access_token, {"id": comment_id, "spam": "false"})
        else:
            await self._client.act("api/approve", token.access_token, {"id": comment_id})

    @override
    async def delete(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        """Borra un comentario propio. Uno ajeno no se borra: se quita, si la cuenta modera."""
        await self._client.act("api/del", token.access_token, {"id": comment_id})

    @override
    async def like(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        raise ProviderError(REDDIT, "En Reddit los votos los emite una persona: no se ofrece.")

    @override
    def supports(self, asset: Asset, action: CommentAction) -> bool:
        return action in _OFFERED


def _community(item: dict[str, object]) -> Choice | None:
    name = as_str(item.get("display_name"))
    if name is None:
        return None
    facts = {
        "subscribers": as_int(item.get("subscribers")),
        # `any`, `link` o `self`: qué clase de publicaciones acepta.
        "submission_type": as_str(item.get("submission_type")),
        "subreddit_type": as_str(item.get("subreddit_type")),
        "over18": item.get("over18") if isinstance(item.get("over18"), bool) else None,
    }
    return Choice(
        name,
        as_str(item.get("display_name_prefixed")) or f"r/{name}",
        detail=as_str(item.get("title")) or as_str(item.get("public_description")),
        data={key: str(value).lower() for key, value in facts.items() if value is not None},
    )


class RedditLookups(LookupReader):
    def __init__(self, client: RedditClient) -> None:
        self._client = client

    @override
    async def choices(
        self, asset: Asset, token: Token, *, lookup: str, query: str | None, parent: str | None
    ) -> Sequence[Choice]:
        if lookup == FLAIRS.name:
            return await self._flairs(token, community(parent or ""))
        if query:
            data = await self._client.get(
                "subreddits/search", token.access_token, {"q": query, "limit": self._client.config.page_size}
            )
            children = as_list(as_dict(as_dict(data).get("data")).get("children"))
            pages = [[as_dict(child.get("data")) for child in children]]
        else:
            pages = [
                page async for page in self._client.listing("subreddits/mine/subscriber", token.access_token)
            ]
        return [choice for page in pages for item in page if (choice := _community(item)) is not None]

    async def _flairs(self, token: Token, name: str) -> list[Choice]:
        try:
            data = await self._client.get(f"r/{name}/api/link_flair_v2", token.access_token)
        except ProviderError as error:
            # Una comunidad sin etiquetas, o que no deja verlas, responde 403 o 404: no hay qué elegir.
            if error.kind is ErrorKind.UNKNOWN and error.status in _NOT_THERE:
                return []
            raise
        return [
            Choice(
                flair_id,
                as_str(item.get("text")) or flair_id,
                data={"text_editable": str(item.get("text_editable") is True).lower()},
            )
            for item in as_list(data)
            if (flair_id := as_str(item.get("id"))) is not None
        ]
