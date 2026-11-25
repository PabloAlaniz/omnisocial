"""Los posts propios de la cuenta, sin reposts ni respuestas."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.x.client import XClient, as_dict, as_int, as_list, as_str, iso, parse_time
from omnisocial.application.ports import ContentReader
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Post
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

POST_FIELDS = "created_at,public_metrics,conversation_id,attachments"


def permalink(post_id: str) -> str:
    return f"https://x.com/i/web/status/{post_id}"


def to_post(item: dict[str, object], asset_external_id: str) -> Post:
    post_id = str(item["id"])
    metrics = as_dict(item.get("public_metrics"))
    reposts = as_int(metrics.get("retweet_count"))
    return Post(
        external_id=post_id,
        asset_external_id=asset_external_id,
        created_at=parse_time(item.get("created_at")),
        text=as_str(item.get("text")),
        permalink=permalink(post_id),
        media_type="media" if as_dict(item.get("attachments")).get("media_keys") else "text",
        like_count=as_int(metrics.get("like_count")),
        comment_count=as_int(metrics.get("reply_count")),
        # Según la versión de la respuesta, los reposts vienen con un nombre o con el otro.
        share_count=reposts if reposts is not None else as_int(metrics.get("repost_count")),
        view_count=as_int(metrics.get("impression_count")),
        raw=item,
    )


class XContentReader(ContentReader):
    def __init__(self, client: XClient) -> None:
        self._client = client

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        config = self._client.config
        query: dict[str, str | int] = {
            "max_results": config.page_size,
            "exclude": "retweets,replies",
            config.post_fields_param: POST_FIELDS,
        }
        # X filtra por fecha: no hace falta traer de más y cortar. Cada post leído se cobra.
        if window.since is not None:
            query["start_time"] = iso(window.since)
        if window.until is not None:
            query["end_time"] = iso(window.until)
        posts: list[Post] = []
        path = f"users/{asset.external_id}/tweets"
        async for page in self._client.pages(path, token.access_token, query):
            for item in as_list(page.get("data")):
                if not item.get("id"):
                    continue
                posts.append(to_post(item, asset.external_id))
                if limit is not None and len(posts) >= limit:
                    return posts
        return posts
