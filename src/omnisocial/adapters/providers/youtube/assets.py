"""En YouTube el activo es el canal de quien autorizó."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.youtube.client import YouTubeClient, as_dict, as_str
from omnisocial.adapters.providers.youtube.config import YOUTUBE_CHANNEL
from omnisocial.adapters.providers.youtube.oauth import own_channel
from omnisocial.adapters.providers.youtube.spec import CHANNEL_CAPABILITIES
from omnisocial.application.ports import AssetDirectory
from omnisocial.domain.asset import DiscoveredAsset
from omnisocial.domain.token import Token

UPLOADS = "uploads"
"""La playlist con todo lo que subió el canal: de ahí se listan los videos sin gastar una búsqueda."""


class YouTubeAssetDirectory(AssetDirectory):
    def __init__(self, client: YouTubeClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        channel = await own_channel(self._client, token, "snippet,contentDetails")
        snippet = as_dict(channel.get("snippet"))
        playlists = as_dict(as_dict(channel.get("contentDetails")).get("relatedPlaylists"))
        metadata = {
            UPLOADS: as_str(playlists.get(UPLOADS)) or "",
            "handle": as_str(snippet.get("customUrl")) or "",
        }
        # Sin token propio: se usa el de la conexión, que es el del canal.
        return [
            DiscoveredAsset(
                YOUTUBE_CHANNEL,
                str(channel["id"]),
                name=as_str(snippet.get("title")),
                capabilities=CHANNEL_CAPABILITIES,
                metadata={key: value for key, value in metadata.items() if value},
            )
        ]
