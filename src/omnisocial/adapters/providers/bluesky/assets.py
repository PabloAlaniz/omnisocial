"""En Bluesky el activo es la cuenta de quien conectó."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.bluesky.client import BlueskyClient, as_str
from omnisocial.adapters.providers.bluesky.config import BLUESKY_ACCOUNT
from omnisocial.adapters.providers.bluesky.session import own_session
from omnisocial.adapters.providers.bluesky.spec import ACCOUNT_CAPABILITIES
from omnisocial.application.ports import AssetDirectory
from omnisocial.domain.asset import DiscoveredAsset
from omnisocial.domain.token import Token


class BlueskyAssetDirectory(AssetDirectory):
    def __init__(self, client: BlueskyClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        session = await own_session(self._client, token)
        handle = as_str(session.get("handle"))
        # Sin token propio: se usa el de la conexión, que es el de la cuenta.
        return [
            DiscoveredAsset(
                BLUESKY_ACCOUNT,
                str(session["did"]),
                name=handle,
                capabilities=ACCOUNT_CAPABILITIES,
                metadata={"handle": handle} if handle else {},
            )
        ]
