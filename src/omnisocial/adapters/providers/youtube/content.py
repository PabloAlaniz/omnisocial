"""Los videos del canal.

Se listan desde la playlist de subidas y nunca con una búsqueda: la búsqueda tiene un cupo diario chico.
La playlist da los ids del más nuevo al más viejo; los datos y contadores se piden después, de a 50.
"""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.youtube.assets import UPLOADS
from omnisocial.adapters.providers.youtube.client import (
    YouTubeClient,
    as_dict,
    as_int,
    as_list,
    as_str,
    parse_time,
)
from omnisocial.adapters.providers.youtube.oauth import own_channel, thumbnail
from omnisocial.application.ports import ContentReader
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Post
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

_BATCH = 50


def _post(video: dict[str, object], asset: Asset) -> Post:
    video_id = str(video["id"])
    snippet = as_dict(video.get("snippet"))
    statistics = as_dict(video.get("statistics"))
    return Post(
        external_id=video_id,
        asset_external_id=asset.external_id,
        created_at=parse_time(snippet.get("publishedAt")),
        text=as_str(snippet.get("title")),
        permalink=f"https://www.youtube.com/watch?v={video_id}",
        media_type="video",
        media_url=thumbnail(snippet),
        # Un video puede ocultar los likes o tener los comentarios desactivados: el contador no viene.
        like_count=as_int(statistics.get("likeCount")),
        comment_count=as_int(statistics.get("commentCount")),
        view_count=as_int(statistics.get("viewCount")),
        raw=video,
    )


class YouTubeContentReader(ContentReader):
    def __init__(self, client: YouTubeClient) -> None:
        self._client = client

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        ids = await self._video_ids(asset, token, window, limit)
        posts: list[Post] = []
        for start in range(0, len(ids), _BATCH):
            data = await self._client.get(
                "videos",
                token.access_token,
                {"part": "snippet,statistics", "id": ",".join(ids[start : start + _BATCH])},
            )
            posts.extend(_post(video, asset) for video in as_list(data.get("items")) if video.get("id"))
        return posts

    async def _video_ids(
        self, asset: Asset, token: Token, window: TimeWindow, limit: int | None
    ) -> list[str]:
        playlist = asset.metadata.get(UPLOADS) or await self._uploads_playlist(token)
        if not playlist:
            return []
        query: dict[str, str | int] = {
            "part": "contentDetails",
            "playlistId": playlist,
            "maxResults": self._client.config.page_size,
        }
        ids: list[str] = []
        async for page in self._client.pages("playlistItems", token.access_token, query):
            for details in (as_dict(item.get("contentDetails")) for item in page):
                published = parse_time(details.get("videoPublishedAt"))
                video_id = as_str(details.get("videoId"))
                if window.is_before(published):
                    return ids
                if video_id and window.contains(published):
                    ids.append(video_id)
                if limit is not None and len(ids) >= limit:
                    return ids
        return ids

    async def _uploads_playlist(self, token: Token) -> str | None:
        """Para un activo guardado sin la playlist (o que nunca subió nada)."""
        channel = await own_channel(self._client, token, "contentDetails")
        playlists = as_dict(as_dict(channel.get("contentDetails")).get("relatedPlaylists"))
        return as_str(playlists.get(UPLOADS))
