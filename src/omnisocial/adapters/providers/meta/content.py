"""Publicaciones de páginas y media de Instagram."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.meta.config import INSTAGRAM_ACCOUNT
from omnisocial.adapters.providers.meta.graph import (
    PERMISSION_CODE,
    GraphClient,
    as_int,
    as_str,
    parse_time,
    summary_count,
    unix,
)
from omnisocial.application.ports import ContentReader
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Post
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

PAGE_POST_FIELDS = (
    "id,message,story,created_time,permalink_url,full_picture,status_type,"
    "likes.summary(true).limit(0),comments.summary(true).limit(0)"
)
PAGE_POST_BASIC_FIELDS = "id,message,story,created_time,permalink_url,full_picture,status_type"
MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,permalink,timestamp,media_url,thumbnail_url,"
    "like_count,comments_count"
)


class MetaContentReader(ContentReader):
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        if asset.kind == INSTAGRAM_ACCOUNT:
            return await self._instagram(asset, token, window, limit)
        return await self._page(asset, token, window, limit)

    async def _page(self, asset: Asset, token: Token, window: TimeWindow, limit: int | None) -> list[Post]:
        def params(fields: str) -> dict[str, str | int]:
            out: dict[str, str | int] = {"fields": fields, "limit": self._graph.config.page_size}
            if window.since is not None:
                out["since"] = unix(window.since)
            if window.until is not None:
                out["until"] = unix(window.until)
            return out

        path = f"{asset.external_id}/posts"
        try:
            items = await self._graph.collect(
                path,
                token.access_token,
                params(PAGE_POST_FIELDS),
                time_field="created_time",
                window=window,
                limit=limit,
            )
        except ProviderError as error:
            # Sin `pages_read_user_content` la Graph API niega los contadores de likes y comentarios.
            # Se traen las publicaciones igual, sin contadores, en vez de no traer nada.
            if error.code != PERMISSION_CODE:
                raise
            items = await self._graph.collect(
                path,
                token.access_token,
                params(PAGE_POST_BASIC_FIELDS),
                time_field="created_time",
                window=window,
                limit=limit,
            )
        return [
            Post(
                external_id=str(item["id"]),
                asset_external_id=asset.external_id,
                created_at=parse_time(item.get("created_time")),
                text=as_str(item.get("message")) or as_str(item.get("story")),
                permalink=as_str(item.get("permalink_url")),
                media_type=as_str(item.get("status_type")),
                media_url=as_str(item.get("full_picture")),
                like_count=summary_count(item.get("likes")),
                comment_count=summary_count(item.get("comments")),
                raw=item,
            )
            for item in items
            if as_str(item.get("id"))
        ]

    async def _instagram(
        self, asset: Asset, token: Token, window: TimeWindow, limit: int | None
    ) -> list[Post]:
        items = await self._graph.collect(
            f"{asset.external_id}/media",
            token.access_token,
            {"fields": MEDIA_FIELDS, "limit": self._graph.config.page_size},
            time_field="timestamp",
            window=window,
            limit=limit,
        )
        return [
            Post(
                external_id=str(item["id"]),
                asset_external_id=asset.external_id,
                created_at=parse_time(item.get("timestamp")),
                text=as_str(item.get("caption")),
                permalink=as_str(item.get("permalink")),
                media_type=as_str(item.get("media_product_type")) or as_str(item.get("media_type")),
                media_url=as_str(item.get("media_url")) or as_str(item.get("thumbnail_url")),
                like_count=as_int(item.get("like_count")),
                comment_count=as_int(item.get("comments_count")),
                raw=item,
            )
            for item in items
            if as_str(item.get("id"))
        ]
