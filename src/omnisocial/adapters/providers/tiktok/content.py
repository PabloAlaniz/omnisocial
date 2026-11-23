"""Los videos públicos de la cuenta (`/video/list/`)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

from typing_extensions import override

from omnisocial.adapters.providers.tiktok.client import TikTokClient, as_int, as_list, as_str
from omnisocial.application.ports import ContentReader
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Post
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

VIDEO_FIELDS = (
    "id",
    "create_time",
    "title",
    "video_description",
    "share_url",
    "embed_link",
    "cover_image_url",
    "duration",
    "like_count",
    "comment_count",
    "share_count",
    "view_count",
)


def _created(item: dict[str, object]) -> datetime | None:
    seconds = as_int(item.get("create_time"))
    return datetime.fromtimestamp(seconds, UTC) if seconds is not None else None


def _post(item: dict[str, object], asset: Asset) -> Post:
    return Post(
        external_id=str(item["id"]),
        asset_external_id=asset.external_id,
        created_at=_created(item),
        text=as_str(item.get("video_description")) or as_str(item.get("title")),
        permalink=as_str(item.get("share_url")) or as_str(item.get("embed_link")),
        media_type="video",
        # La portada es un link que vence a las 6 horas.
        media_url=as_str(item.get("cover_image_url")),
        like_count=as_int(item.get("like_count")),
        comment_count=as_int(item.get("comment_count")),
        share_count=as_int(item.get("share_count")),
        view_count=as_int(item.get("view_count")),
        raw=item,
    )


class TikTokContentReader(ContentReader):
    """TikTok no filtra por fecha: devuelve del más nuevo al más viejo, y el cursor es un instante en ms.

    Se arranca desde el final de la ventana (pasándolo como cursor) y se corta al pasar el principio.
    """

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        posts: list[Post] = []
        async for page in self._pages(token, window):
            for post in (_post(item, asset) for item in page):
                if window.is_before(post.created_at):
                    return posts
                if window.contains(post.created_at):
                    posts.append(post)
                if limit is not None and len(posts) >= limit:
                    return posts
        return posts

    async def _pages(self, token: Token, window: TimeWindow) -> AsyncIterator[list[dict[str, object]]]:
        cursor = int(window.until.timestamp() * 1000) if window.until else None
        while True:
            body: dict[str, object] = {"max_count": self._client.config.page_size}
            if cursor is not None:
                body["cursor"] = cursor
            data = await self._client.query("video/list", token.access_token, fields=VIDEO_FIELDS, body=body)
            yield [item for item in as_list(data.get("videos")) if as_str(item.get("id"))]
            cursor = as_int(data.get("cursor"))
            if data.get("has_more") is not True or cursor is None:
                return
