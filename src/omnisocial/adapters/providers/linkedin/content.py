"""Las publicaciones de una página de empresa.

Se piden ordenadas por fecha de creación. Con el orden por defecto (última modificación) una publicación
vieja que alguien editó aparece primera, y cortar al salir de la ventana perdería las que siguen.
"""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.linkedin.client import (
    LinkedInClient,
    as_dict,
    as_str,
    encode,
    from_millis,
)
from omnisocial.adapters.providers.linkedin.config import urn
from omnisocial.adapters.providers.linkedin.text import plain
from omnisocial.application.ports import ContentReader
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import Post
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

_MEDIA_TYPES = ("multiImage", "article", "media", "poll", "carousel")


def permalink(post_urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{post_urn}/"


def _post(item: dict[str, object], asset: Asset) -> Post:
    post_urn = str(item["id"])
    content = as_dict(item.get("content"))
    commentary = as_str(item.get("commentary"))
    return Post(
        external_id=post_urn,
        asset_external_id=asset.external_id,
        created_at=from_millis(item.get("createdAt")) or from_millis(item.get("publishedAt")),
        text=plain(commentary) if commentary else None,
        permalink=permalink(post_urn),
        media_type=next((kind for kind in _MEDIA_TYPES if kind in content), None),
        # Los contadores están en otra API, de a una publicación por llamada: acá no vienen.
        raw=item,
    )


class LinkedInContentReader(ContentReader):
    def __init__(self, client: LinkedInClient) -> None:
        self._client = client

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        author = encode(urn(asset.kind, asset.external_id))
        posts: list[Post] = []
        async for page in self._client.pages(
            f"posts?author={author}&q=author&sortBy=CREATED", token.access_token
        ):
            for post in (_post(item, asset) for item in page if item.get("id")):
                if window.is_before(post.created_at):
                    return posts
                if window.contains(post.created_at):
                    posts.append(post)
                if limit is not None and len(posts) >= limit:
                    return posts
        return posts
