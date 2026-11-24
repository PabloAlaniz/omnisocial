"""Publicar en TikTok con la Content Posting API (publicación directa).

Siempre es en etapas: se inicia la publicación, TikTok descarga el video o las fotos de su URL y los
procesa, y el estado se consulta después. La URL tiene que ser de un dominio verificado en la app.
"""

from __future__ import annotations

from collections.abc import Mapping

from typing_extensions import override

from omnisocial.adapters.providers.tiktok.client import TikTokClient, as_str
from omnisocial.adapters.providers.tiktok.config import TIKTOK, TikTokOptions
from omnisocial.application.ports import Publisher
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.publishing import (
    Draft,
    MediaKind,
    Outcome,
    PublicationStatus,
    TextCount,
    text_length,
)
from omnisocial.domain.token import Token

_PUBLISH_ID = "publish_id"
_COMPLETE = "PUBLISH_COMPLETE"
_FAILED = "FAILED"
_PHOTO_TITLE_MAX = 90


def _short_title(text: str) -> str:
    title = text
    while text_length(title, TextCount.UTF16) > _PHOTO_TITLE_MAX:
        title = title[:-1]
    return title


def _video(draft: Draft, options: TikTokOptions) -> dict[str, object]:
    return {
        "post_info": {
            "title": draft.text,
            "privacy_level": options.privacy_level,
            "disable_comment": options.disable_comment,
            "disable_duet": options.disable_duet,
            "disable_stitch": options.disable_stitch,
            "brand_content_toggle": options.brand_content,
            "brand_organic_toggle": options.brand_organic,
        },
        "source_info": {"source": "PULL_FROM_URL", "video_url": draft.media[0].public_url},
    }


def _photos(draft: Draft, options: TikTokOptions) -> dict[str, object]:
    return {
        "post_info": {
            "title": options.photo_title or _short_title(draft.text),
            "description": draft.text,
            "privacy_level": options.privacy_level,
            "disable_comment": options.disable_comment,
            "brand_content_toggle": options.brand_content,
            "brand_organic_toggle": options.brand_organic,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": 0,
            "photo_images": [media.public_url for media in draft.media],
        },
        "post_mode": "DIRECT_POST",
        "media_type": "PHOTO",
    }


class TikTokPublisher(Publisher):
    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options if isinstance(draft.options, TikTokOptions) else TikTokOptions()
        if draft.media[0].kind is MediaKind.VIDEO:
            path, body = "post/publish/video/init", _video(draft, options)
        else:
            path, body = "post/publish/content/init", _photos(draft, options)
        started = await self._client.command(path, token.access_token, body)
        publish_id = as_str(started.get(_PUBLISH_ID))
        if not publish_id:
            raise ProviderError(TIKTOK, "TikTok no devolvió el id de la publicación.")
        return Outcome(PublicationStatus.PENDING, resume={_PUBLISH_ID: publish_id})

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        publish_id = resume.get(_PUBLISH_ID)
        if not publish_id:
            raise ProviderError(TIKTOK, "La publicación no tiene nada para retomar.")
        state = await self._client.command(
            "post/publish/status/fetch", token.access_token, {_PUBLISH_ID: publish_id}, read=True
        )
        status = as_str(state.get("status"))
        if status == _FAILED:
            reason = as_str(state.get("fail_reason")) or "sin motivo"
            return Outcome(PublicationStatus.FAILED, error=f"TikTok no pudo publicarla: {reason}")
        if status != _COMPLETE:
            return Outcome(PublicationStatus.PENDING, resume=resume)
        # El id público solo viene si la publicación la puede ver cualquiera (y con ese nombre, mal escrito).
        public_ids = state.get("publicaly_available_post_id")
        post_id = as_str(public_ids[0]) if isinstance(public_ids, list) and public_ids else None
        return Outcome(PublicationStatus.PUBLISHED, post_id=post_id)

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        raise ProviderError(TIKTOK, "La API de TikTok no permite borrar publicaciones.")
