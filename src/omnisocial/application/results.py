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
from omnisocial.domain.identity import Identity
from omnisocial.domain.metrics import CanonicalMetric, MetricSeries
from omnisocial.domain.provider import Capability
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
    OUTSIDE_REPLY_WINDOW = "outside_reply_window"
    NO_RECIPIENT = "no_recipient"


@dataclass(frozen=True, slots=True)
class Refused:
    reason: Refusal
    detail: str | None = None
    return_url: str | None = None
    capability: Capability | None = None


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
