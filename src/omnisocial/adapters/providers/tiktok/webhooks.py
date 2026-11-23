"""Webhooks de TikTok: firma con marca de tiempo y traducción de los avisos.

`TikTok-Signature: t=<segundos>,s=<hex>`, donde la firma es HMAC-SHA256 de `"<t>.<cuerpo crudo>"` con el
secreto de la app. Es el mismo esquema que Stripe con otra cabecera y otra clave para la firma.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from omniwebhook import IncomingRequest, Rejected, Verification, Verified, Verifier
from typing_extensions import override

from omnisocial.adapters.providers.tiktok.client import as_dict, as_int, as_str
from omnisocial.adapters.providers.tiktok.config import TIKTOK, TikTokConfig
from omnisocial.application.ports import Clock, WebhookParser
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent

SIGNATURE_HEADER = "tiktok-signature"

_EVENTS = {
    "authorization.removed": (EventKind.AUTHORIZATION, EventAction.DELETED),
    "video.publish.completed": (EventKind.POST, EventAction.CREATED),
    "video.upload.failed": (EventKind.POST, EventAction.UNKNOWN),
}


def _pairs(header: str) -> dict[str, list[str]]:
    pairs: dict[str, list[str]] = {}
    for part in header.split(","):
        key, sep, value = part.strip().partition("=")
        if sep:
            pairs.setdefault(key.strip(), []).append(value.strip())
    return pairs


def _read(request: IncomingRequest) -> tuple[str, list[str]] | Rejected:
    """La marca de tiempo tal como llegó (es parte de lo firmado) y las firmas, o por qué no se puede leer."""
    headers = [value for name, value in request.headers if name.lower() == SIGNATURE_HEADER]
    if len(headers) != 1:
        return Rejected("missing" if not headers else "ambiguous")
    pairs = _pairs(headers[0])
    times, signatures = pairs.get("t", []), [s.lower() for s in pairs.get("s", [])]
    if len(times) != 1 or not signatures or not times[0].isdigit():
        return Rejected("malformed")
    return times[0], signatures


class TikTokSignatureVerifier(Verifier):
    """El esquema de firma de TikTok, sobre el puerto `Verifier` de omniwebhook."""

    def __init__(self, secrets: Sequence[str], clock: Clock, *, tolerance_seconds: int) -> None:
        self._keys = tuple(secret.encode() for secret in secrets if secret)
        self._clock = clock
        self._tolerance = tolerance_seconds

    @override
    def verify(self, request: IncomingRequest) -> Verification:
        if not self._keys:
            return Rejected("unconfigured")
        reading = _read(request)
        if isinstance(reading, Rejected):
            return reading
        raw_timestamp, signatures = reading
        signed = raw_timestamp.encode() + b"." + request.body
        expected = [hmac.new(key, signed, hashlib.sha256).hexdigest() for key in self._keys]
        if not any(hmac.compare_digest(e, s) for e in expected for s in signatures):
            return Rejected("invalid")
        timestamp = int(raw_timestamp)
        if abs(self._clock.now().timestamp() - timestamp) > self._tolerance:
            return Rejected("stale")
        # TikTok no manda id de entrega: la clave es la huella del cuerpo (los reintentos llegan iguales).
        return Verified(event_key=f"tiktok:{hashlib.sha256(request.body).hexdigest()}", timestamp=timestamp)


class TikTokWebhookParser(WebhookParser):
    def __init__(self, config: TikTokConfig, clock: Clock) -> None:
        self._verifier = TikTokSignatureVerifier(
            config.webhook_secrets, clock, tolerance_seconds=config.webhook_tolerance_seconds
        )

    @override
    def handshake(self, query: Mapping[str, str]) -> str | None:
        # TikTok no confirma la URL con un GET: se configura en el portal y empieza a mandar avisos.
        return None

    @property
    @override
    def verifier(self) -> Verifier:
        return self._verifier

    @override
    def parse(self, body: bytes) -> Sequence[SocialEvent]:
        try:
            payload = as_dict(json.loads(body))
        except ValueError:
            return []
        name = as_str(payload.get("event"))
        open_id = as_str(payload.get("user_openid"))
        if not name or not open_id:
            return []
        kind, action = _EVENTS.get(name, (EventKind.OTHER, EventAction.UNKNOWN))
        created = as_int(payload.get("create_time"))
        try:
            content = as_dict(json.loads(as_str(payload.get("content")) or "{}"))
        except ValueError:
            content = {}
        return [
            SocialEvent(
                provider=TIKTOK,
                kind=kind,
                action=action,
                asset_external_id=open_id,
                object_external_id=as_str(content.get("share_id")),
                occurred_at=datetime.fromtimestamp(created, UTC) if created is not None else None,
                raw={"event": name, **payload, "content": content},
            )
        ]
