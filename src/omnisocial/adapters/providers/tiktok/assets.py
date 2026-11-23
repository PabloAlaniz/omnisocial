"""En TikTok el activo es la cuenta misma de quien autorizó: no hay páginas ni cuentas colgadas."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.tiktok.client import TikTokClient, as_dict, as_str
from omnisocial.adapters.providers.tiktok.config import TIKTOK, TIKTOK_ACCOUNT
from omnisocial.application.ports import AssetDirectory
from omnisocial.domain.asset import DiscoveredAsset
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.provider import Capability
from omnisocial.domain.token import Token

ACCOUNT_CAPABILITIES = frozenset({Capability.CONTENT, Capability.INSIGHTS})


class TikTokAssetDirectory(AssetDirectory):
    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        data = await self._client.get("user/info", token.access_token, fields=("open_id", "display_name"))
        user = as_dict(data.get("user"))
        open_id = as_str(user.get("open_id"))
        if not open_id:
            raise ProviderError(TIKTOK, "TikTok no devolvió el open_id de la cuenta.")
        # Sin token propio: se usa el de la conexión, que es el de la cuenta.
        return [
            DiscoveredAsset(
                TIKTOK_ACCOUNT,
                open_id,
                name=as_str(user.get("display_name")),
                capabilities=ACCOUNT_CAPABILITIES,
            )
        ]
