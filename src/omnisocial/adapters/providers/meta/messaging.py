"""Mensajes privados de Messenger y de Instagram, por la página."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from omnisocial.adapters.providers.meta.config import INSTAGRAM_ACCOUNT, META
from omnisocial.adapters.providers.meta.graph import (
    GraphClient,
    as_dict,
    as_list,
    as_str,
    parse_time,
)
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.messaging import Conversation, Message, ReplyWindow
from omnisocial.domain.token import Token

STANDARD_REPLY_WINDOW = ReplyWindow(timedelta(hours=24))
"""Fuera de las 24 horas solo se puede escribir con etiquetas especiales, que esta librería no usa."""


def _page_id(asset: Asset) -> str:
    """Los mensajes de Instagram también se leen y se mandan por la página conectada."""
    if asset.kind == INSTAGRAM_ACCOUNT:
        if not asset.parent_external_id:
            raise ProviderError(META, "La cuenta de Instagram no tiene página conectada.")
        return asset.parent_external_id
    return asset.external_id


def _platform(asset: Asset) -> str:
    return "instagram" if asset.kind == INSTAGRAM_ACCOUNT else "messenger"


class MetaMessagingGateway:
    reply_window = STANDARD_REPLY_WINDOW

    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def list_conversations(
        self, asset: Asset, token: Token, *, limit: int | None
    ) -> Sequence[Conversation]:
        items = await self._graph.collect(
            f"{_page_id(asset)}/conversations",
            token.access_token,
            {"platform": _platform(asset), "fields": "id,updated_time,participants", "limit": 25},
            limit=limit,
        )
        conversations = []
        for item in items:
            external_id = as_str(item.get("id"))
            if not external_id:
                continue
            participants = as_list(as_dict(item.get("participants")).get("data"))
            conversations.append(
                Conversation(
                    external_id=external_id,
                    asset_external_id=asset.external_id,
                    updated_at=parse_time(item.get("updated_time")),
                    participant_ids=tuple(p for p in (as_str(x.get("id")) for x in participants) if p),
                    channel=_platform(asset),
                    raw=item,
                )
            )
        return conversations

    async def list_messages(
        self, asset: Asset, token: Token, *, conversation_id: str, limit: int | None
    ) -> Sequence[Message]:
        items = await self._graph.collect(
            f"{conversation_id}/messages",
            token.access_token,
            {"fields": "id,message,from,created_time", "limit": 50},
            limit=limit,
        )
        own_ids = {asset.external_id, _page_id(asset)}
        messages = []
        for item in items:
            external_id = as_str(item.get("id"))
            if not external_id:
                continue
            sender = as_str(as_dict(item.get("from")).get("id"))
            messages.append(
                Message(
                    external_id=external_id,
                    conversation_external_id=conversation_id,
                    created_at=parse_time(item.get("created_time")),
                    sender_id=sender,
                    text=as_str(item.get("message")),
                    from_asset=sender in own_ids,
                    raw=item,
                )
            )
        return messages

    async def send(self, asset: Asset, token: Token, *, recipient_id: str, text: str) -> str:
        body = await self._graph.post(
            f"{_page_id(asset)}/messages",
            token.access_token,
            json={"recipient": {"id": recipient_id}, "message": {"text": text}, "messaging_type": "RESPONSE"},
        )
        message_id = as_str(body.get("message_id"))
        if not message_id:
            raise ProviderError(META, "Meta no devolvió el id del mensaje.")
        return message_id
