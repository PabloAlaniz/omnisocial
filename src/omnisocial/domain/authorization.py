"""El pedido de autorización que viaja entre el inicio y el callback."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from omnisocial.domain.provider import ProviderId

DEFAULT_STATE_TTL = timedelta(minutes=10)


class Purpose(StrEnum):
    LOGIN = "login"
    """Solo saber quién es la persona. No se guarda ningún token."""
    CONNECT = "connect"
    """Guardar la conexión y descubrir sus activos para usarlos después."""


def pkce_challenge(verifier: str) -> str:
    """El `code_challenge` S256 de PKCE (RFC 7636)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    state: str
    provider: ProviderId
    purpose: Purpose
    redirect_uri: str
    created_at: datetime
    expires_at: datetime
    scopes: tuple[str, ...]
    owner: str | None = None
    return_url: str | None = None
    code_verifier: str | None = field(default=None, repr=False)

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    @property
    def code_challenge(self) -> str | None:
        return pkce_challenge(self.code_verifier) if self.code_verifier else None
