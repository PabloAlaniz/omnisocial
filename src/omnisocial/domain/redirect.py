"""A dónde se puede volver después de autorizar."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _origin(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.scheme == "http" and parts.hostname not in _LOCAL_HOSTS:
        return None
    if parts.username or parts.password:
        return None
    default = 443 if parts.scheme == "https" else 80
    return f"{parts.scheme}://{parts.hostname.lower()}:{port or default}"


@dataclass(frozen=True, slots=True)
class ReturnUrlPolicy:
    """Solo se vuelve a orígenes conocidos, para que el callback no sirva de redirección abierta.

    Compara esquema, host y puerto exactos. `http` solo se acepta para `localhost`.
    """

    allowed_origins: frozenset[str]

    @classmethod
    def of(cls, *origins: str) -> ReturnUrlPolicy:
        normalized = {o for o in (_origin(origin) for origin in origins) if o is not None}
        return cls(frozenset(normalized))

    def allows(self, url: str) -> bool:
        origin = _origin(url)
        return origin is not None and origin in self.allowed_origins
