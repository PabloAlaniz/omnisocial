"""Reloj, identificadores y secretos de verdad."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidGenerator:
    def new_id(self) -> str:
        return str(uuid.uuid4())


class SystemSecrets:
    def token(self, nbytes: int) -> str:
        return secrets.token_urlsafe(nbytes)
