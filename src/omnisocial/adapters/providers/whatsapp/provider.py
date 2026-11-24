"""Arma el proveedor de WhatsApp Business."""

from __future__ import annotations

from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.whatsapp.client import WhatsAppClient
from omnisocial.adapters.providers.whatsapp.config import WHATSAPP, WhatsAppConfig
from omnisocial.adapters.providers.whatsapp.messaging import (
    WhatsAppAssetDirectory,
    WhatsAppLookups,
    WhatsAppMessagingGateway,
)
from omnisocial.adapters.providers.whatsapp.oauth import WhatsAppIdentity, whatsapp_oauth
from omnisocial.adapters.providers.whatsapp.spec import SPEC
from omnisocial.adapters.providers.whatsapp.webhooks import WhatsAppWebhookParser
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import Clock
from omnisocial.application.registry import Provider


def whatsapp_provider(
    config: WhatsAppConfig, transport: HttpTransport, *, clock: Clock | None = None
) -> Provider:
    """Se conecta con el diálogo de Facebook o, si el token se obtuvo de otra forma (el alta embebida, un
    usuario de sistema), con `register_system_connection`."""
    client = WhatsAppClient(config, transport)
    return Provider(
        id=WHATSAPP,
        oauth=whatsapp_oauth(client, clock or SystemClock()),
        identity=WhatsAppIdentity(client),
        assets=WhatsAppAssetDirectory(client),
        messaging=WhatsAppMessagingGateway(client),
        webhooks=WhatsAppWebhookParser(config),
        lookups=WhatsAppLookups(client),
        spec=SPEC,
    )
