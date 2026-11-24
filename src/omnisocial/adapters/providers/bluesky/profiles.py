"""Perfiles públicos de cualquier cuenta, sin que nadie conecte."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.providers.bluesky.client import BlueskyClient, as_dict, as_int, as_str
from omnisocial.application.ports import ProfileLookup
from omnisocial.domain.asset import Asset
from omnisocial.domain.handles import Handle, Network
from omnisocial.domain.profile import PublicProfile
from omnisocial.domain.token import Token

_BAD_REQUEST = 400


class BlueskyProfileLookup(ProfileLookup):
    def __init__(self, client: BlueskyClient) -> None:
        self._client = client

    @property
    @override
    def networks(self) -> frozenset[Network]:
        return frozenset({Network.BLUESKY})

    @override
    def viewer_kinds(self, network: Network) -> frozenset[str]:
        return frozenset()

    @override
    async def lookup(
        self, handle: Handle, *, viewer: Asset | None, token: Token | None
    ) -> PublicProfile | None:
        """Por nombre (`ana.bsky.social`) o por DID. La identidad es el DID: el nombre puede cambiar."""
        response = await self._client.get_public("app.bsky.actor.getProfile", {"actor": handle.value})
        # Una cuenta que no existe responde 400, no 404.
        if response.status == _BAD_REQUEST and as_dict(response.data).get("error") == "InvalidRequest":
            return None
        profile = self._client.unwrap(response)
        did = as_str(profile.get("did"))
        if did is None:
            return None
        username = as_str(profile.get("handle"))
        return PublicProfile(
            Network.BLUESKY,
            did,
            username=username,
            name=as_str(profile.get("displayName")),
            followers=as_int(profile.get("followersCount")),
            following=as_int(profile.get("followsCount")),
            posts=as_int(profile.get("postsCount")),
            bio=as_str(profile.get("description")),
            avatar_url=as_str(profile.get("avatar")),
            url=f"https://bsky.app/profile/{username or did}",
            raw=profile,
        )
