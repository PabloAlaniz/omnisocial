"""Perfiles públicos de Instagram con `business_discovery`.

Instagram muestra cuentas ajenas solo a través de una cuenta profesional propia (el mirador) y solo si la
cuenta buscada también es profesional (empresa o creador). Las páginas de Facebook ajenas necesitan
"Page Public Metadata Access", que exige revisión aparte: no se cubren.
"""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.providers.meta.config import INSTAGRAM_ACCOUNT
from omnisocial.adapters.providers.meta.graph import GraphClient, as_dict, as_int, as_str
from omnisocial.application.ports import ProfileLookup
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.handles import Handle, Network
from omnisocial.domain.profile import PublicProfile
from omnisocial.domain.token import Token

DISCOVERY_FIELDS = (
    "id,username,name,biography,website,profile_picture_url,followers_count,follows_count,media_count"
)

# "Invalid user id": la cuenta no existe o no es profesional. Para el que busca, es lo mismo.
_NOT_FOUND_CODE = "110"


def _profile(node: dict[str, object]) -> PublicProfile | None:
    external_id = as_str(node.get("id"))
    if not external_id:
        return None
    username = as_str(node.get("username"))
    return PublicProfile(
        network=Network.INSTAGRAM,
        external_id=external_id,
        username=username,
        name=as_str(node.get("name")),
        followers=as_int(node.get("followers_count")),
        following=as_int(node.get("follows_count")),
        posts=as_int(node.get("media_count")),
        bio=as_str(node.get("biography")),
        avatar_url=as_str(node.get("profile_picture_url")),
        website=as_str(node.get("website")),
        url=f"https://www.instagram.com/{username}/" if username else None,
        raw=node,
    )


class MetaProfileLookup(ProfileLookup):
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    @property
    @override
    def networks(self) -> frozenset[Network]:
        return frozenset({Network.INSTAGRAM})

    @override
    def viewer_kinds(self, network: Network) -> frozenset[str]:
        return frozenset({INSTAGRAM_ACCOUNT})

    @override
    async def lookup(
        self, handle: Handle, *, viewer: Asset | None, token: Token | None
    ) -> PublicProfile | None:
        if viewer is None or token is None:
            raise ValueError("Instagram necesita una cuenta propia como mirador.")
        fields = f"business_discovery.username({handle.value}){{{DISCOVERY_FIELDS}}}"
        try:
            body = await self._graph.get(viewer.external_id, token.access_token, {"fields": fields})
        except ProviderError as error:
            if error.code == _NOT_FOUND_CODE:
                return None
            raise
        return _profile(as_dict(body.get("business_discovery")))
