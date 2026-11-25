"""El perfil de quien autorizó y las páginas de empresa que administra."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.linkedin.client import LinkedInClient, as_dict, as_str
from omnisocial.adapters.providers.linkedin.config import LINKEDIN_MEMBER, LINKEDIN_ORGANIZATION
from omnisocial.adapters.providers.linkedin.oauth import LinkedInIdentity
from omnisocial.adapters.providers.linkedin.spec import MEMBER_CAPABILITIES, ORGANIZATION_CAPABILITIES
from omnisocial.application.ports import AssetDirectory
from omnisocial.domain.asset import DiscoveredAsset
from omnisocial.domain.errors import PermissionMissing
from omnisocial.domain.token import Token

_ACLS = "organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED"
_PREFIX = "urn:li:organization:"


class LinkedInAssetDirectory(AssetDirectory):
    def __init__(self, client: LinkedInClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        person = await LinkedInIdentity(self._client).identity(token)
        member = DiscoveredAsset(
            LINKEDIN_MEMBER, person.external_id, name=person.name, capabilities=MEMBER_CAPABILITIES
        )
        try:
            organizations = await self._organizations(token)
        except PermissionMissing:
            # Sin la Community Management API no se ven las páginas: queda el perfil, que alcanza para
            # publicar como persona.
            return [member]
        return [member, *organizations]

    async def _organizations(self, token: Token) -> list[DiscoveredAsset]:
        ids: list[str] = []
        async for page in self._client.pages(_ACLS, token.access_token):
            for acl in page:
                # Según la página de resultados, el campo se llama de una forma u otra.
                target = as_str(acl.get("organization")) or as_str(acl.get("organizationTarget")) or ""
                if target.startswith(_PREFIX):
                    ids.append(target.removeprefix(_PREFIX))
        if not ids:
            return []
        names = await self._names(token, ids)
        return [
            DiscoveredAsset(
                LINKEDIN_ORGANIZATION,
                organization_id,
                name=names.get(organization_id, {}).get("name"),
                capabilities=ORGANIZATION_CAPABILITIES,
                metadata={k: v for k, v in names.get(organization_id, {}).items() if k == "vanity_name"},
            )
            for organization_id in dict.fromkeys(ids)
        ]

    async def _names(self, token: Token, ids: Sequence[str]) -> dict[str, dict[str, str]]:
        data = await self._client.get(f"organizations?ids=List({','.join(ids)})", token.access_token)
        found: dict[str, dict[str, str]] = {}
        for organization_id, node in as_dict(data.get("results")).items():
            details = as_dict(node)
            fields = {
                "name": as_str(details.get("localizedName")),
                "vanity_name": as_str(details.get("vanityName")),
            }
            found[str(organization_id)] = {key: value for key, value in fields.items() if value}
        return found
