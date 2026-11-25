"""Webhooks de TikTok: la firma la verifica omniwebhook; acá se traducen los avisos."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from omniwebhook import Verifier, tiktok_scheme
from typing_extensions import override

from omnisocial.adapters.providers.tiktok.client import as_dict, as_int, as_str
from omnisocial.adapters.providers.tiktok.config import TIKTOK, TikTokConfig
from omnisocial.application.ports import Clock, WebhookParser
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent

_EVENTS = {
    "authorization.removed": (EventKind.AUTHORIZATION, EventAction.DELETED),
    "video.publish.completed": (EventKind.POST, EventAction.CREATED),
    "video.upload.failed": (EventKind.POST, EventAction.UNKNOWN),
}


class _UnixClock:
    """El reloj de omnisocial en el formato que pide omniwebhook: segundos desde la época Unix."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def now(self) -> int:
        return int(self._clock.now().timestamp())


class TikTokWebhookParser(WebhookParser):
    def __init__(self, config: TikTokConfig, clock: Clock) -> None:
        self._verifier = tiktok_scheme(
            secrets=list(config.webhook_secrets),
            tolerance_seconds=config.webhook_tolerance_seconds,
            clock=_UnixClock(clock),
        )

    @override
    def handshake(self, query: Mapping[str, str]) -> str | None:
        # TikTok no confirma la URL con un GET: se configura en el portal y empieza a mandar avisos.
        return None

    @property
    @override
    def verifier(self) -> Verifier:
        """El esquema `tiktok` de omniwebhook: `TikTok-Signature: t=<segundos>,s=<hex>`, con tolerancia.

        TikTok no manda un id de entrega: la clave del aviso es la huella del cuerpo.
        """
        return self._verifier

    @override
    def parse(self, body: bytes, *, query: Mapping[str, str] | None = None) -> Sequence[SocialEvent]:
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
