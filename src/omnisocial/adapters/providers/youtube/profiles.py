"""Perfiles públicos de cualquier canal, con una clave de API y sin que nadie autorice."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.providers.youtube.client import YouTubeClient, as_dict, as_int, as_list, as_str
from omnisocial.adapters.providers.youtube.oauth import thumbnail
from omnisocial.application.ports import ProfileLookup
from omnisocial.domain.asset import Asset
from omnisocial.domain.handles import Handle, HandleKind, Network
from omnisocial.domain.profile import PublicProfile
from omnisocial.domain.token import Token


def _profile(channel: dict[str, object]) -> PublicProfile:
    channel_id = str(channel["id"])
    snippet = as_dict(channel.get("snippet"))
    statistics = as_dict(channel.get("statistics"))
    hidden = statistics.get("hiddenSubscriberCount") is True
    return PublicProfile(
        Network.YOUTUBE,
        channel_id,
        username=as_str(snippet.get("customUrl")),
        name=as_str(snippet.get("title")),
        followers=None if hidden else as_int(statistics.get("subscriberCount")),
        posts=as_int(statistics.get("videoCount")),
        bio=as_str(snippet.get("description")),
        avatar_url=thumbnail(snippet),
        url=f"https://www.youtube.com/channel/{channel_id}",
        raw=channel,
    )


class YouTubeProfileLookup(ProfileLookup):
    def __init__(self, client: YouTubeClient) -> None:
        self._client = client

    @property
    @override
    def networks(self) -> frozenset[Network]:
        return frozenset({Network.YOUTUBE})

    @override
    def viewer_kinds(self, network: Network) -> frozenset[str]:
        return frozenset()

    @override
    async def lookup(
        self, handle: Handle, *, viewer: Asset | None, token: Token | None
    ) -> PublicProfile | None:
        """Por id (`UC…`) o por nombre (`@marca`). Nunca con una búsqueda: una cuenta que no existe no
        gasta el cupo de búsquedas."""
        by = {"id": handle.value} if handle.kind is HandleKind.ID else {"forHandle": handle.value}
        data = await self._client.get_public("channels", {"part": "snippet,statistics", **by})
        channels = [channel for channel in as_list(data.get("items")) if channel.get("id")]
        return _profile(channels[0]) if channels else None
