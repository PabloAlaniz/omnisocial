"""En Threads el activo es la cuenta de quien autorizó."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.threads.client import ThreadsClient, as_str
from omnisocial.adapters.providers.threads.config import THREADS_ACCOUNT
from omnisocial.adapters.providers.threads.oauth import own_profile
from omnisocial.adapters.providers.threads.spec import ACCOUNT_CAPABILITIES
from omnisocial.application.ports import AssetDirectory
from omnisocial.domain.asset import DiscoveredAsset
from omnisocial.domain.token import Token


class ThreadsAssetDirectory(AssetDirectory):
    def __init__(self, client: ThreadsClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        profile = await own_profile(self._client, token)
        username = as_str(profile.get("username"))
        # Sin token propio: se usa el de la conexión, que es el de la cuenta.
        return [
            DiscoveredAsset(
                THREADS_ACCOUNT,
                str(profile["id"]),
                name=as_str(profile.get("name")) or username,
                capabilities=ACCOUNT_CAPABILITIES,
                metadata={"username": username} if username else {},
            )
        ]
