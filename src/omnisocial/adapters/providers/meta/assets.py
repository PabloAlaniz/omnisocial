"""Las páginas que administra el token y las cuentas de Instagram conectadas a cada una."""

from __future__ import annotations

from collections.abc import Sequence

from omnisocial.adapters.providers.meta.config import FACEBOOK_PAGE, INSTAGRAM_ACCOUNT
from omnisocial.adapters.providers.meta.graph import GraphClient, as_dict, as_str
from omnisocial.domain.asset import DiscoveredAsset
from omnisocial.domain.provider import Capability
from omnisocial.domain.token import Token, TokenKind

PAGE_CAPABILITIES = frozenset(
    {Capability.CONTENT, Capability.COMMENTS, Capability.MESSAGING, Capability.INSIGHTS, Capability.WEBHOOKS}
)
INSTAGRAM_CAPABILITIES = PAGE_CAPABILITIES

_FIELDS = (
    "id,name,access_token,category,tasks,instagram_business_account{id,username,name,profile_picture_url}"
)


class MetaAssetDirectory:
    """Con un token de usuario o de usuario de sistema, `me/accounts` devuelve las páginas y su token.

    La cuenta de Instagram usa el token de su página: la Graph API no tiene tokens propios de Instagram en
    este flujo.
    """

    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        found: list[DiscoveredAsset] = []
        async for page in self._graph.paginate(
            "me/accounts", token.access_token, {"fields": _FIELDS, "limit": 100}
        ):
            for item in page:
                found.extend(self._from_page(item))
        return found

    @staticmethod
    def _from_page(item: dict[str, object]) -> list[DiscoveredAsset]:
        page_id = as_str(item.get("id"))
        if not page_id:
            return []
        page_token_value = as_str(item.get("access_token"))
        page_token = Token(TokenKind.ASSET, page_token_value) if page_token_value else None
        tasks = item.get("tasks")
        metadata = {"category": as_str(item.get("category")) or ""}
        if isinstance(tasks, list):
            metadata["tasks"] = ",".join(t for t in tasks if isinstance(t, str))
        assets = [
            DiscoveredAsset(
                kind=FACEBOOK_PAGE,
                external_id=page_id,
                name=as_str(item.get("name")),
                token=page_token,
                capabilities=PAGE_CAPABILITIES,
                metadata={k: v for k, v in metadata.items() if v},
            )
        ]
        instagram = as_dict(item.get("instagram_business_account"))
        instagram_id = as_str(instagram.get("id"))
        if instagram_id:
            ig_meta = {
                "username": as_str(instagram.get("username")) or "",
                "picture": as_str(instagram.get("profile_picture_url")) or "",
            }
            assets.append(
                DiscoveredAsset(
                    kind=INSTAGRAM_ACCOUNT,
                    external_id=instagram_id,
                    name=as_str(instagram.get("name")) or as_str(instagram.get("username")),
                    parent_external_id=page_id,
                    token=page_token,
                    capabilities=INSTAGRAM_CAPABILITIES,
                    metadata={k: v for k, v in ig_meta.items() if v},
                )
            )
        return assets
