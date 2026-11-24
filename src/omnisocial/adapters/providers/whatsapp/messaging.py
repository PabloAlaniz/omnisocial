"""Los números de una cuenta, mandar mensajes y las plantillas."""

from __future__ import annotations

import re
from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.whatsapp.client import WhatsAppClient, as_dict, as_list, as_str
from omnisocial.adapters.providers.whatsapp.config import WHATSAPP, WHATSAPP_NUMBER
from omnisocial.adapters.providers.whatsapp.spec import (
    MAX_CAPTION,
    NUMBER_CAPABILITIES,
    NUMBER_LIMITS,
    REPLY_WINDOW,
)
from omnisocial.application.ports import AssetDirectory, LookupReader, MessagingGateway
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.errors import ErrorKind, ProviderError
from omnisocial.domain.lookup import Choice
from omnisocial.domain.messaging import Conversation, Message, MessagingLimits, OutboundMessage
from omnisocial.domain.publishing import MediaKind
from omnisocial.domain.token import Token

_SCOPES = frozenset({"whatsapp_business_management", "whatsapp_business_messaging"})
_USER_ID = re.compile(r"[A-Z]{2}\.[A-Za-z0-9]+")
"""Un id de usuario propio del negocio (`AR.1349…`), que WhatsApp manda cuando no da el teléfono."""
_NO_HISTORY = "WhatsApp no deja leer los mensajes pasados: llegan por avisos."


class WhatsAppAssetDirectory(AssetDirectory):
    def __init__(self, client: WhatsAppClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        """Los números de las cuentas de WhatsApp Business a las que el token tiene acceso."""
        found: dict[str, DiscoveredAsset] = {}
        for account in await self._accounts(token):
            async for page in self._client.pages(
                f"{account}/phone_numbers",
                token.access_token,
                {"fields": "id,display_phone_number,verified_name,quality_rating"},
            ):
                for number in page:
                    number_id = as_str(number.get("id"))
                    if number_id is None:
                        continue
                    fields = {
                        "display_phone_number": as_str(number.get("display_phone_number")),
                        "quality_rating": as_str(number.get("quality_rating")),
                    }
                    found.setdefault(
                        number_id,
                        DiscoveredAsset(
                            WHATSAPP_NUMBER,
                            number_id,
                            name=as_str(number.get("verified_name")) or fields["display_phone_number"],
                            parent_external_id=account,
                            capabilities=NUMBER_CAPABILITIES,
                            metadata={key: value for key, value in fields.items() if value},
                        ),
                    )
        return list(found.values())

    async def _accounts(self, token: Token) -> list[str]:
        """El token dice a qué cuentas le dieron acceso. Si no lo dice (tiene acceso a todo el
        portfolio), se listan las del portfolio configurado."""
        info = await self._client.inspect(token.access_token)
        accounts = [
            str(target)
            for scope in as_list(info.get("granular_scopes"))
            if scope.get("scope") in _SCOPES and isinstance(scope.get("target_ids"), list)
            for target in scope["target_ids"]  # type: ignore[attr-defined]
        ]
        business = self._client.config.business_id
        if not accounts and business:
            for edge in ("owned_whatsapp_business_accounts", "client_whatsapp_business_accounts"):
                async for page in self._client.pages(f"{business}/{edge}", token.access_token):
                    accounts.extend(account_id for item in page if (account_id := as_str(item.get("id"))))
        return list(dict.fromkeys(accounts))


def _content(message: OutboundMessage) -> dict[str, object]:
    if message.template is not None:
        template: dict[str, object] = {
            "name": message.template.name,
            "language": {"code": message.template.language},
        }
        if message.template.components:
            template["components"] = [dict(component) for component in message.template.components]
        return {"type": "template", "template": template}
    if not message.attachments:
        return {"type": "text", "text": {"body": message.text, "preview_url": True}}
    media = message.attachments[0]
    if len(message.text) > MAX_CAPTION:
        raise ProviderError(
            WHATSAPP,
            f"El texto que acompaña a un adjunto tiene hasta {MAX_CAPTION} caracteres.",
            kind=ErrorKind.INVALID_REQUEST,
        )
    kind = "video" if media.kind is MediaKind.VIDEO else "image"
    attachment: dict[str, object] = {"link": media.public_url}
    if message.text:
        attachment["caption"] = message.text
    return {"type": kind, kind: attachment}


class WhatsAppMessagingGateway(MessagingGateway):
    reply_window = REPLY_WINDOW

    def __init__(self, client: WhatsAppClient) -> None:
        self._client = client

    @override
    def limits_for(self, asset: Asset) -> MessagingLimits:
        return NUMBER_LIMITS

    @override
    async def list_conversations(
        self, asset: Asset, token: Token, *, limit: int | None
    ) -> Sequence[Conversation]:
        raise ProviderError(WHATSAPP, _NO_HISTORY)

    @override
    async def list_messages(
        self, asset: Asset, token: Token, *, conversation_id: str, limit: int | None
    ) -> Sequence[Message]:
        raise ProviderError(WHATSAPP, _NO_HISTORY)

    @override
    async def send(self, asset: Asset, token: Token, *, recipient_id: str, message: OutboundMessage) -> str:
        """`recipient_id` es el teléfono con código de país o el id de usuario que vino en el aviso."""
        to = "recipient" if _USER_ID.fullmatch(recipient_id) else "to"
        body: dict[str, object] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            to: recipient_id,
            **_content(message),
        }
        if message.reply_to:
            body["context"] = {"message_id": message.reply_to}
        sent = await self._client.post(f"{asset.external_id}/messages", token.access_token, body)
        messages = as_list(sent.get("messages"))
        message_id = as_str(messages[0].get("id")) if messages else None
        if message_id is None:
            raise ProviderError(WHATSAPP, "WhatsApp no devolvió el id del mensaje.")
        return message_id


class WhatsAppLookups(LookupReader):
    def __init__(self, client: WhatsAppClient) -> None:
        self._client = client

    @override
    async def choices(
        self, asset: Asset, token: Token, *, lookup: str, query: str | None, parent: str | None
    ) -> Sequence[Choice]:
        """Las plantillas de la cuenta del número. Solo las que están `APPROVED` se pueden mandar."""
        if not asset.parent_external_id:
            raise ProviderError(WHATSAPP, "El número no tiene su cuenta: hay que sincronizarlo.")
        found: list[Choice] = []
        async for page in self._client.pages(
            f"{asset.parent_external_id}/message_templates",
            token.access_token,
            {"fields": "name,language,status,category"},
        ):
            for item in page:
                name, language = as_str(item.get("name")), as_str(item.get("language"))
                if name is None or language is None:
                    continue
                facts = {
                    "language": language,
                    "status": as_str(item.get("status")),
                    "category": as_str(item.get("category")),
                }
                found.append(Choice(name, name, detail=language, data={k: v for k, v in facts.items() if v}))
        return found


__all__ = ["WhatsAppAssetDirectory", "WhatsAppLookups", "WhatsAppMessagingGateway", "as_dict"]
