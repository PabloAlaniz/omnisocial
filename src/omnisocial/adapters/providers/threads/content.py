"""Los posts de la cuenta."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.threads.client import ThreadsClient, as_str, parse_time
from omnisocial.application.ports import ContentReader
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Post
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

POST_FIELDS = "id,media_product_type,media_type,media_url,permalink,username,text,timestamp,thumbnail_url"


def _post(item: dict[str, object], asset: Asset) -> Post:
    return Post(
        external_id=str(item["id"]),
        asset_external_id=asset.external_id,
        created_at=parse_time(item.get("timestamp")),
        text=as_str(item.get("text")),
        permalink=as_str(item.get("permalink")),
        media_type=as_str(item.get("media_type")),
        media_url=as_str(item.get("media_url")) or as_str(item.get("thumbnail_url")),
        # Los contadores de cada post están en sus métricas, de a un post por llamada: acá no vienen.
        raw=item,
    )


class ThreadsContentReader(ContentReader):
    def __init__(self, client: ThreadsClient) -> None:
        self._client = client

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        query: dict[str, str | int] = {"fields": POST_FIELDS, "limit": self._client.config.page_size}
        if window.since is not None:
            query["since"] = int(window.since.timestamp())
        if window.until is not None:
            query["until"] = int(window.until.timestamp())
        posts: list[Post] = []
        path = f"{asset.external_id}/threads"
        async for page in self._client.pages(path, token.access_token, query):
            for item in page:
                if not item.get("id"):
                    continue
                posts.append(_post(item, asset))
                if limit is not None and len(posts) >= limit:
                    return posts
        return posts
