"""El callback de borrado de datos de Meta: el `signed_request` que llega cuando alguien quita la app.

Meta lo manda como `<firma>.<datos>`, los dos en base64url sin relleno. La firma es HMAC-SHA256 de la parte
de datos (tal como llega, en base64) con el secreto de la app.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from omnisocial.adapters.providers.meta.config import MetaConfig
from omnisocial.domain.errors import OmnisocialError

_ALGORITHM = "HMAC-SHA256"
_PARTS = 2


class InvalidSignedRequest(OmnisocialError):
    """El `signed_request` está mal formado, usa otro algoritmo o la firma no coincide."""


@dataclass(frozen=True, slots=True)
class DeletionRequest:
    user_id: str
    """El id de la persona *para esta app* (no es el mismo en otras apps)."""
    issued_at: datetime | None
    payload: dict[str, object] = field(repr=False)


@dataclass(frozen=True, slots=True)
class DeletionReceipt:
    """Lo que Meta espera de vuelta: dónde la persona consulta el estado y un código para reclamar."""

    status_url: str
    confirmation_code: str


def _b64decode(value: str) -> bytes:
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidSignedRequest("El signed_request no es base64url.") from error


def _decode_payload(encoded: str) -> dict[str, object]:
    try:
        payload = json.loads(_b64decode(encoded))
    except ValueError as error:
        raise InvalidSignedRequest("Los datos del signed_request no son JSON.") from error
    if not isinstance(payload, dict):
        raise InvalidSignedRequest("Los datos del signed_request no son un objeto.")
    return payload


def parse_signed_request(signed_request: str, secrets: Sequence[str]) -> DeletionRequest:
    """Verifica la firma con alguno de los secretos (el actual o uno anterior, al rotar) y la decodifica."""
    parts = signed_request.split(".")
    if len(parts) != _PARTS or not all(parts):
        raise InvalidSignedRequest("El signed_request no tiene la forma <firma>.<datos>.")
    signature, encoded = parts
    given = _b64decode(signature)
    if not any(
        hmac.compare_digest(given, hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest())
        for secret in secrets
        if secret
    ):
        raise InvalidSignedRequest("La firma del signed_request no coincide.")
    payload = _decode_payload(encoded)
    if str(payload.get("algorithm", "")).upper() != _ALGORITHM:
        raise InvalidSignedRequest("El signed_request no usa HMAC-SHA256.")
    user_id = payload.get("user_id")
    if not isinstance(user_id, str | int) or isinstance(user_id, bool) or not str(user_id):
        raise InvalidSignedRequest("El signed_request no trae user_id.")
    issued = payload.get("issued_at")
    issued_at = (
        datetime.fromtimestamp(issued, UTC)
        if isinstance(issued, int) and not isinstance(issued, bool)
        else None
    )
    return DeletionRequest(user_id=str(user_id), issued_at=issued_at, payload=payload)


class MetaDeletionRequests:
    """Lo que necesita la ruta del callback: verificar con los secretos de la app."""

    def __init__(self, config: MetaConfig) -> None:
        _, app_secret = config.require_app
        self._secrets = (app_secret, *config.previous_app_secrets)

    def parse(self, signed_request: str) -> DeletionRequest:
        return parse_signed_request(signed_request, self._secrets)
