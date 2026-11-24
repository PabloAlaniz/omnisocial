"""Publicar en un activo, retomar una publicación en curso y borrarla."""

from __future__ import annotations

from dataclasses import dataclass

from omnisocial.application.ports import Clock, IdGenerator, PublicationRepository
from omnisocial.application.registry import Provider, ProviderRegistry
from omnisocial.application.results import AssetAccess, Done, Refusal, Refused, refusal_for
from omnisocial.application.use_cases.access import ResolveAssetAccess
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ErrorKind, ProviderError, TokenRejected
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import (
    Draft,
    DraftProblem,
    Publication,
    PublicationStatus,
    PublishLimits,
    check_draft,
)

_CAPABILITY = Capability.PUBLISHING
_MAX_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class _Opened:
    provider: Provider
    access: AssetAccess
    limits: PublishLimits


class _Publishing:
    def __init__(self, *, registry: ProviderRegistry, access: ResolveAssetAccess) -> None:
        self._registry = registry
        self._access = access

    async def _open(self, asset_id: str) -> _Opened | Refused:
        access = await self._access.execute(asset_id)
        if isinstance(access, Refused):
            return access
        provider = self._registry.get(access.asset.provider)
        limits = _limits(provider, access.asset)
        if limits is None:
            return Refused(Refusal.NOT_SUPPORTED, capability=_CAPABILITY)
        return _Opened(provider, access, limits)

    async def _refused(self, opened: _Opened, error: TokenRejected | ProviderError) -> Refused | None:
        """La negativa que corresponde a lo que dijo la red, o `None` si no se sabe qué pasó."""
        if isinstance(error, TokenRejected):
            return await self._access.reject(opened.access, error)
        if error.kind is ErrorKind.INVALID_REQUEST:
            return Refused(Refusal.CONTENT_REJECTED, detail=str(error), capability=_CAPABILITY)
        return refusal_for(error, _CAPABILITY)


def _limits(provider: Provider, asset: Asset) -> PublishLimits | None:
    """Los límites de ese activo, o `None` si la red o el activo no publican."""
    if provider.publisher is None or provider.spec is None:
        return None
    if asset.capabilities and not asset.supports(_CAPABILITY):
        return None
    return provider.spec.publishing.get(asset.kind)


class ValidateDraft(_Publishing):
    """Qué impide publicar un borrador en un activo, sin llamar a la red. Vacío si se puede."""

    async def execute(self, asset_id: str, draft: Draft) -> Done[tuple[DraftProblem, ...]] | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        return Done(check_draft(draft, opened.limits))


class Publish(_Publishing):
    """Publica un borrador.

    Antes de llamar a la red valida el borrador y reserva la publicación. Con `idempotency_key`, repetir
    el pedido devuelve la publicación que ya existe en vez de publicar de nuevo.

    Si la red dice con certeza que no salió (borrador rechazado, permiso faltante, límite de uso), vuelve
    una negativa y la reserva se libera: se puede reintentar con la misma clave. Si no se sabe qué pasó
    (la red no respondió), la excepción sigue y la publicación queda `STARTED`: está en duda, y repetir el
    pedido con la misma clave la devuelve así en vez de arriesgar un duplicado.
    """

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        access: ResolveAssetAccess,
        publications: PublicationRepository,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        super().__init__(registry=registry, access=access)
        self._publications = publications
        self._clock = clock
        self._ids = ids

    async def execute(
        self, asset_id: str, draft: Draft, *, idempotency_key: str | None = None
    ) -> Done[Publication] | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        problems = check_draft(draft, opened.limits)
        if problems:
            detail = " ".join(problem.detail for problem in problems)
            return Refused(Refusal.INVALID_DRAFT, detail=detail, capability=_CAPABILITY, problems=problems)
        reserved = await self._reserve(opened.access.asset, idempotency_key)
        if reserved is None:
            # Otra llamada con la misma clave ya la envió o la está enviando: no se envía de nuevo.
            return await self._existing(opened.access.asset, idempotency_key)
        return await self._send(opened, reserved, draft)

    async def _reserve(self, asset: Asset, key: str | None) -> Publication | None:
        """La publicación recién reservada, o `None` si ese activo ya tiene una con esa clave."""
        now = self._clock.now()
        fresh = Publication(
            id=self._ids.new_id(),
            asset_id=asset.id,
            owner=asset.owner,
            provider=asset.provider,
            status=PublicationStatus.STARTED,
            created_at=now,
            updated_at=now,
            idempotency_key=key,
        )
        return fresh if await self._publications.add(fresh) else None

    async def _existing(self, asset: Asset, key: str | None) -> Done[Publication] | Refused:
        existing = await self._publications.find_by_key(asset.id, key) if key is not None else None
        if existing is None:
            # La otra llamada terminó en una negativa y liberó la reserva entre el alta y la búsqueda.
            return Refused(Refusal.NOT_FOUND, detail="la publicación con esa clave ya no existe")
        return Done(existing)

    async def _send(
        self, opened: _Opened, reserved: Publication, draft: Draft
    ) -> Done[Publication] | Refused:
        publisher = opened.provider.require_publisher()
        try:
            outcome = await publisher.publish(opened.access.asset, opened.access.token, draft=draft)
        except (TokenRejected, ProviderError) as error:
            refused = await self._refused(opened, error)
            if refused is None:
                raise
            await self._publications.remove(reserved.id)
            return refused
        published = reserved.with_outcome(outcome, self._clock.now())
        await self._publications.save(published, expected_version=reserved.version)
        return Done(published)


class CheckPublication(_Publishing):
    """El estado de una publicación. Si la red la estaba procesando, la retoma y guarda el avance."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        access: ResolveAssetAccess,
        publications: PublicationRepository,
        clock: Clock,
    ) -> None:
        super().__init__(registry=registry, access=access)
        self._publications = publications
        self._clock = clock

    async def execute(self, publication_id: str) -> Done[Publication] | Refused:
        for _ in range(_MAX_ATTEMPTS):
            publication = await self._publications.get(publication_id)
            if publication is None:
                return Refused(Refusal.NOT_FOUND)
            if publication.status is not PublicationStatus.PENDING:
                return Done(publication)
            advanced = await self._advance(publication)
            if isinstance(advanced, Refused):
                return advanced
            if await self._publications.save(advanced, expected_version=publication.version):
                return Done(advanced)
            # Otro proceso la retomó primero: se relee y se devuelve lo que guardó.
        return Refused(Refusal.NOT_FOUND, detail="la publicación cambia demasiado rápido")  # pragma: no cover

    async def _advance(self, publication: Publication) -> Publication | Refused:
        opened = await self._open(publication.asset_id)
        if isinstance(opened, Refused):
            return opened
        publisher = opened.provider.require_publisher()
        try:
            outcome = await publisher.resume(
                opened.access.asset, opened.access.token, resume=publication.resume
            )
        except (TokenRejected, ProviderError) as error:
            refused = await self._refused(opened, error)
            if refused is None:
                raise
            return refused
        return publication.with_outcome(outcome, self._clock.now())


class DeletePost(_Publishing):
    async def execute(self, asset_id: str, *, post_id: str) -> Done[None] | Refused:
        opened = await self._open(asset_id)
        if isinstance(opened, Refused):
            return opened
        if not opened.limits.delete:
            return Refused(Refusal.ACTION_NOT_OFFERED, detail="delete", capability=_CAPABILITY)
        publisher = opened.provider.require_publisher()
        try:
            await publisher.delete(opened.access.asset, opened.access.token, post_id=post_id)
        except (TokenRejected, ProviderError) as error:
            refused = await self._refused(opened, error)
            if refused is None:
                raise
            return refused
        return Done(None)
