"""Resultados tipados de los casos de uso.

Cada caso de uso devuelve un éxito o una negativa con su motivo. El código que llama decide con un
`match` en vez de atrapar excepciones.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

from omnisocial.domain.asset import Asset
from omnisocial.domain.connection import Connection
from omnisocial.domain.errors import (
    NotPublished,
    PermissionMissing,
    ProviderError,
    QuotaExhausted,
    RateLimited,
)
from omnisocial.domain.identity import Identity
from omnisocial.domain.metrics import CanonicalMetric, MetricSeries
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import DraftProblem
from omnisocial.domain.token import Token

T = TypeVar("T")


class Refusal(StrEnum):
    RETURN_URL_NOT_ALLOWED = "return_url_not_allowed"
    OWNER_REQUIRED = "owner_required"
    UNKNOWN_STATE = "unknown_state"
    EXPIRED_STATE = "expired_state"
    PROVIDER_DENIED = "provider_denied"
    NOT_FOUND = "not_found"
    CONNECTION_EXPIRED = "connection_expired"
    CONNECTION_INVALID = "connection_invalid"
    CONNECTION_REVOKED = "connection_revoked"
    NOT_SUPPORTED = "not_supported"
    ACTION_NOT_OFFERED = "action_not_offered"
    """La red no ofrece esa acción para ese activo (dar like a un comentario de Instagram, por ejemplo)."""
    MISSING_PERMISSION = "missing_permission"
    """Al token le falta un permiso: se resuelve volviendo a conectar la cuenta."""
    INVALID_HANDLE = "invalid_handle"
    """Lo que se pasó no es un nombre de cuenta válido para esa red."""
    VIEWER_REQUIRED = "viewer_required"
    """La red solo muestra cuentas ajenas a través de una cuenta propia, y no se indicó una que sirva."""
    PROFILE_NOT_FOUND = "profile_not_found"
    NO_ASSETS = "no_assets"
    """El token es válido pero no administra ningún activo: no se guarda."""
    OUTSIDE_REPLY_WINDOW = "outside_reply_window"
    NO_RECIPIENT = "no_recipient"
    RATE_LIMITED = "rate_limited"
    """La red pide bajar el ritmo. `retry_after` trae los segundos que pidió esperar, si lo dijo."""
    QUOTA_EXHAUSTED = "quota_exhausted"
    """Se acabó la cuota o el crédito de la app en la red. La conexión sigue sana."""
    INVALID_DRAFT = "invalid_draft"
    """El borrador no entra en ese activo. `problems` dice por qué. No se llamó a la red."""
    CONTENT_REJECTED = "content_rejected"
    """La red no aceptó el contenido. No salió, y repetirlo igual da lo mismo."""
    NOT_PUBLISHED = "not_published"
    """Falló antes de que la red creara nada (se cortó la subida, por ejemplo). Se puede reintentar."""


_REFUSAL_BY_ERROR: dict[type[ProviderError], Refusal] = {
    PermissionMissing: Refusal.MISSING_PERMISSION,
    QuotaExhausted: Refusal.QUOTA_EXHAUSTED,
    NotPublished: Refusal.NOT_PUBLISHED,
}


@dataclass(frozen=True, slots=True)
class Refused:
    reason: Refusal
    detail: str | None = None
    return_url: str | None = None
    capability: Capability | None = None
    retry_after: float | None = None
    problems: tuple[DraftProblem, ...] = ()


def refusal_for(error: ProviderError, capability: Capability) -> Refused | None:
    """La negativa que corresponde a un error de la red, o `None` si no es una decisión de negocio.

    Permiso faltante, límite de uso y cuota agotada no invalidan la conexión ni se arreglan reintentando en
    el momento: vuelven como negativa para que la app decida. Lo demás sigue siendo una excepción.
    """
    if isinstance(error, RateLimited):
        return Refused(
            Refusal.RATE_LIMITED, detail=str(error), capability=capability, retry_after=error.retry_after
        )
    reason = _REFUSAL_BY_ERROR.get(type(error))
    return Refused(reason, detail=str(error), capability=capability) if reason else None


# ── Autorización ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AuthorizationStarted:
    url: str
    state: str


@dataclass(frozen=True, slots=True)
class LoggedIn:
    identity: Identity
    token: Token = field(repr=False)
    return_url: str | None = None


@dataclass(frozen=True, slots=True)
class Connected:
    connection: Connection
    assets: Sequence[Asset]
    return_url: str | None = None
    reconnected: bool = False


# ── Acceso ──────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ValidToken:
    connection: Connection
    token: Token = field(repr=False)


@dataclass(frozen=True, slots=True)
class AssetAccess:
    asset: Asset
    token: Token = field(repr=False)


# ── Lecturas y acciones ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Done(Generic[T]):
    value: T


@dataclass(frozen=True, slots=True)
class InsightsRead:
    series: Sequence[MetricSeries]
    unresolved: Sequence[CanonicalMetric] = ()
