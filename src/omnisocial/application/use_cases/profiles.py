"""Perfiles públicos de cuentas que no se administran."""

from __future__ import annotations

from omnisocial.application.registry import Provider, ProviderRegistry
from omnisocial.application.results import AssetAccess, Done, Refusal, Refused
from omnisocial.application.use_cases.access import ResolveAssetAccess
from omnisocial.domain.errors import PermissionMissing, TokenRejected
from omnisocial.domain.handles import Handle, Network, parse_handle
from omnisocial.domain.profile import PublicProfile
from omnisocial.domain.provider import Capability

_CAPABILITY = Capability.PUBLIC_PROFILES


class LookupProfile:
    """Busca una cuenta por su nombre o su URL.

    Algunas redes solo muestran cuentas ajenas a través de una cuenta propia (el "mirador"): en Instagram,
    una cuenta profesional conectada. Si hace falta y no hay una que sirva, se niega sin llamar a la red.
    """

    def __init__(self, *, registry: ProviderRegistry, access: ResolveAssetAccess) -> None:
        self._registry = registry
        self._access = access

    async def execute(
        self,
        provider_id: str,
        *,
        network: Network | str,
        handle: str,
        viewer_asset_id: str | None = None,
    ) -> Done[PublicProfile] | Refused:
        provider = self._registry.get(provider_id)
        if provider.profiles is None or Network(network) not in provider.profiles.networks:
            return Refused(Refusal.NOT_SUPPORTED, detail=str(network), capability=_CAPABILITY)
        parsed = parse_handle(network, handle)
        if parsed is None:
            return Refused(Refusal.INVALID_HANDLE, detail=handle)
        viewer = await self._viewer(provider, parsed.network, viewer_asset_id)
        if isinstance(viewer, Refused):
            return viewer
        return await self._lookup(provider, parsed, viewer)

    async def _viewer(
        self, provider: Provider, network: Network, viewer_asset_id: str | None
    ) -> AssetAccess | Refused | None:
        kinds = provider.require_profiles().viewer_kinds(network)
        if not kinds:
            return None
        if viewer_asset_id is None:
            return Refused(Refusal.VIEWER_REQUIRED, detail=", ".join(sorted(kinds)))
        access = await self._access.execute(viewer_asset_id)
        if isinstance(access, Refused):
            return access
        if access.asset.provider != provider.id or access.asset.kind not in kinds:
            return Refused(Refusal.VIEWER_REQUIRED, detail=", ".join(sorted(kinds)))
        return access

    async def _lookup(
        self, provider: Provider, handle: Handle, viewer: AssetAccess | None
    ) -> Done[PublicProfile] | Refused:
        profiles = provider.require_profiles()
        try:
            profile = await profiles.lookup(
                handle,
                viewer=viewer.asset if viewer else None,
                token=viewer.token if viewer else None,
            )
        except TokenRejected as error:
            if viewer is None:
                raise
            return await self._access.reject(viewer, error)
        except PermissionMissing as error:
            return Refused(Refusal.MISSING_PERMISSION, detail=str(error), capability=_CAPABILITY)
        if profile is None:
            return Refused(Refusal.PROFILE_NOT_FOUND, detail=str(handle))
        return Done(profile)
