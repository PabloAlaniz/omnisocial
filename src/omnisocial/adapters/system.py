"""Reloj, identificadores y secretos de verdad."""

from __future__ import annotations

import secrets
import time
import uuid
from datetime import UTC, datetime

from typing_extensions import override

from omnisocial.application.ports import Clock, IdGenerator, SecretGenerator


class SystemClock(Clock):
    @override
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidGenerator(IdGenerator):
    @override
    def new_id(self) -> str:
        return str(uuid.uuid4())


class SystemSecrets(SecretGenerator):
    @override
    def token(self, nbytes: int) -> str:
        return secrets.token_urlsafe(nbytes)


def monotonic() -> float:
    """Un reloj que solo avanza, en segundos: para medir cuánto tardó algo."""
    return time.monotonic()


_RANDOM = secrets.SystemRandom()


def uniform_jitter(ceiling: float) -> float:
    """Un valor al azar entre 0 y `ceiling`, para repartir los reintentos en el tiempo."""
    return _RANDOM.uniform(0, ceiling)
