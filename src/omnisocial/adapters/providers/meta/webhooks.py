"""Webhooks de Meta: suscripción, firma y traducción de los avisos."""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping, Sequence

from omniwebhook import Verifier, hmac_body_scheme
from typing_extensions import override

from omnisocial.adapters.providers.meta.config import META, MetaConfig
from omnisocial.adapters.providers.meta.graph import as_dict, as_list, as_str, parse_time
from omnisocial.application.ports import WebhookParser
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent

SIGNATURE_HEADER = "x-hub-signature-256"

_ACTIONS = {
    "add": EventAction.CREATED,
    "edited": EventAction.UPDATED,
    "edit": EventAction.UPDATED,
    "remove": EventAction.DELETED,
}
_POST_ITEMS = frozenset({"post", "status", "photo", "video", "share"})


def verify_subscription(query: Mapping[str, str], expected_token: str | None) -> str | None:
    """El GET con que Meta confirma la URL del webhook. Devuelve el `hub.challenge` a responder, o `None`."""
    if not expected_token or query.get("hub.mode") != "subscribe":
        return None
    given = query.get("hub.verify_token", "")
    if not hmac.compare_digest(given.encode(), expected_token.encode()):
        return None
    return query.get("hub.challenge")


class MetaWebhookParser(WebhookParser):
    def __init__(self, config: MetaConfig) -> None:
        _, app_secret = config.require_app
        self._config = config
        self._verifier = hmac_body_scheme(
            secrets=[secret for secret in (app_secret, *config.previous_app_secrets) if secret],
            header=SIGNATURE_HEADER,
            prefix="sha256=",
            name="meta",
        )

    @override
    def handshake(self, query: Mapping[str, str]) -> str | None:
        return verify_subscription(query, self._config.webhook_verify_token)

    @property
    @override
    def verifier(self) -> Verifier:
        """`X-Hub-Signature-256: sha256=<hex>`: HMAC-SHA256 del cuerpo crudo con el secreto de la app.

        Meta no manda un id de entrega, así que la clave del aviso es la huella del cuerpo: los reintentos
        llegan con el mismo cuerpo y se reconocen como duplicados.
        """
        return self._verifier

    @override
    def parse(self, body: bytes, *, query: Mapping[str, str] | None = None) -> Sequence[SocialEvent]:
        try:
            payload = as_dict(json.loads(body))
        except ValueError:
            return []
        events: list[SocialEvent] = []
        for entry in as_list(payload.get("entry")):
            asset_id = as_str(entry.get("id"))
            if not asset_id:
                continue
            occurred = parse_time(entry.get("time"))
            events.extend(
                self._change(asset_id, change, occurred) for change in as_list(entry.get("changes"))
            )
            messages = (self._message(asset_id, item) for item in as_list(entry.get("messaging")))
            events.extend(event for event in messages if event is not None)
        return events

    @staticmethod
    def _change(asset_id: str, change: dict[str, object], occurred: object) -> SocialEvent:
        field = as_str(change.get("field"))
        value = as_dict(change.get("value"))
        author = as_dict(value.get("from"))
        base = {
            "provider": META,
            "asset_external_id": asset_id,
            "occurred_at": parse_time(value.get("created_time")) or occurred,
            "actor_id": as_str(author.get("id")),
            "raw": change,
        }
        if field == "feed":
            item = as_str(value.get("item"))
            action = _ACTIONS.get(as_str(value.get("verb")) or "", EventAction.UNKNOWN)
            if item == "comment":
                return SocialEvent(
                    kind=EventKind.COMMENT,
                    action=action,
                    object_external_id=as_str(value.get("comment_id")),
                    text=as_str(value.get("message")),
                    **base,  # type: ignore[arg-type]
                )
            if item in _POST_ITEMS:
                return SocialEvent(
                    kind=EventKind.POST,
                    action=action,
                    object_external_id=as_str(value.get("post_id")),
                    text=as_str(value.get("message")),
                    **base,  # type: ignore[arg-type]
                )
        if field in {"comments", "live_comments"}:
            return SocialEvent(
                kind=EventKind.COMMENT,
                action=EventAction.CREATED,
                object_external_id=as_str(value.get("id")),
                text=as_str(value.get("text")),
                **base,  # type: ignore[arg-type]
            )
        if field == "mentions":
            return SocialEvent(
                kind=EventKind.MENTION,
                action=EventAction.CREATED,
                object_external_id=as_str(value.get("comment_id")) or as_str(value.get("media_id")),
                **base,  # type: ignore[arg-type]
            )
        return SocialEvent(
            kind=EventKind.OTHER,
            action=EventAction.UNKNOWN,
            object_external_id=None,
            **base,  # type: ignore[arg-type]
        )

    @staticmethod
    def _message(asset_id: str, messaging: dict[str, object]) -> SocialEvent | None:
        message = as_dict(messaging.get("message"))
        if not message:
            return None
        action = EventAction.DELETED if message.get("is_deleted") is True else EventAction.CREATED
        return SocialEvent(
            provider=META,
            kind=EventKind.MESSAGE,
            action=action,
            asset_external_id=asset_id,
            object_external_id=as_str(message.get("mid")),
            occurred_at=parse_time(messaging.get("timestamp")),
            actor_id=as_str(as_dict(messaging.get("sender")).get("id")),
            text=as_str(message.get("text")),
            raw=messaging,
        )
