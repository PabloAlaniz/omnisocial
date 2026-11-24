"""Los posts propios de la cuenta, sin reposts ni respuestas."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.bluesky.client import BlueskyClient, as_dict, as_int, as_str, parse_time
from omnisocial.adapters.providers.bluesky.config import post_url
from omnisocial.application.ports import ContentReader
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Post
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow


def to_post(view: dict[str, object], asset_external_id: str) -> Post:
    uri = str(view["uri"])
    record = as_dict(view.get("record"))
    author = as_str(as_dict(view.get("author")).get("did")) or asset_external_id
    embed = as_str(as_dict(record.get("embed")).get("$type")) or ""
    return Post(
        external_id=uri,
        asset_external_id=asset_external_id,
        created_at=parse_time(record.get("createdAt")) or parse_time(view.get("indexedAt")),
        text=as_str(record.get("text")),
        permalink=post_url(author, uri),
        media_type=embed.rsplit(".", 1)[-1] or "text",
        like_count=as_int(view.get("likeCount")),
        comment_count=as_int(view.get("replyCount")),
        share_count=as_int(view.get("repostCount")),
        raw=view,
    )


class BlueskyContentReader(ContentReader):
    def __init__(self, client: BlueskyClient) -> None:
        self._client = client

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        query: dict[str, str | int] = {
            "actor": asset.external_id,
            "limit": self._client.config.page_size,
            "filter": "posts_no_replies",
        }
        posts: list[Post] = []
        async for page in self._client.pages("app.bsky.feed.getAuthorFeed", token, query, "feed"):
            for item in page:
                view = as_dict(item.get("post"))
                # Con `reason` es un repost o un post fijado: no es una publicación nueva de la cuenta.
                if item.get("reason") or not view.get("uri"):
                    continue
                post = to_post(view, asset.external_id)
                if window.is_before(post.created_at):
                    return posts
                if window.contains(post.created_at):
                    posts.append(post)
                if limit is not None and len(posts) >= limit:
                    return posts
        return posts
