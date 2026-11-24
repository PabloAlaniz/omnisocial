"""En X el activo es la cuenta de quien autorizó."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.x.client import XClient, as_str
from omnisocial.adapters.providers.x.config import X_ACCOUNT
from omnisocial.adapters.providers.x.oauth import own_account
from omnisocial.adapters.providers.x.spec import ACCOUNT_CAPABILITIES
from omnisocial.application.ports import AssetDirectory
from omnisocial.domain.asset import DiscoveredAsset
from omnisocial.domain.token import Token


class XAssetDirectory(AssetDirectory):
    def __init__(self, client: XClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        account = await own_account(self._client, token)
        username = as_str(account.get("username"))
        # Sin token propio: se usa el de la conexión, que es el de la cuenta.
        return [
            DiscoveredAsset(
                X_ACCOUNT,
                str(account["id"]),
                name=as_str(account.get("name")) or username,
                capabilities=ACCOUNT_CAPABILITIES,
                metadata={"username": username} if username else {},
            )
        ]
