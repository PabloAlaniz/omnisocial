"""Perfiles públicos de cualquier cuenta, con el token de la app y sin que nadie autorice."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.providers.x.client import XClient, as_dict, as_int, as_str
from omnisocial.adapters.providers.x.insights import post_count
from omnisocial.adapters.providers.x.oauth import USER_FIELDS
from omnisocial.application.ports import ProfileLookup
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.handles import Handle, HandleKind, Network
from omnisocial.domain.profile import PublicProfile
from omnisocial.domain.token import Token

_NOT_FOUND = 404


def _profile(account: dict[str, object]) -> PublicProfile:
    metrics = as_dict(account.get("public_metrics"))
    username = as_str(account.get("username"))
    verified = account.get("verified")
    return PublicProfile(
        Network.X,
        str(account["id"]),
        username=username,
        name=as_str(account.get("name")),
        followers=as_int(metrics.get("followers_count")),
        following=as_int(metrics.get("following_count")),
        posts=post_count(metrics),
        bio=as_str(account.get("description")),
        avatar_url=as_str(account.get("profile_image_url")),
        website=as_str(account.get("url")),
        verified=verified if isinstance(verified, bool) else None,
        url=f"https://x.com/{username}" if username else None,
        raw=account,
    )


class XProfileLookup(ProfileLookup):
    def __init__(self, client: XClient) -> None:
        self._client = client

    @property
    @override
    def networks(self) -> frozenset[Network]:
        return frozenset({Network.X})

    @override
    def viewer_kinds(self, network: Network) -> frozenset[str]:
        return frozenset()

    @override
    async def lookup(
        self, handle: Handle, *, viewer: Asset | None, token: Token | None
    ) -> PublicProfile | None:
        path = (
            f"users/{handle.value}" if handle.kind is HandleKind.ID else f"users/by/username/{handle.value}"
        )
        try:
            data = await self._client.get_public(path, {"user.fields": USER_FIELDS})
        except ProviderError as error:
            if error.status == _NOT_FOUND:
                return None
            raise
        # Una cuenta que no existe o está suspendida vuelve con 200 y sin `data`.
        account = as_dict(data.get("data"))
        return _profile(account) if account.get("id") else None
