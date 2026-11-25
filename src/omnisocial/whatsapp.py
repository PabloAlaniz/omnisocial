"""WhatsApp Business. `pip install omnisocial[httpx]` para el transporte por defecto."""

from omnisocial.adapters.providers.whatsapp.config import (
    BUSINESS_SCOPES,
    CONNECT_SCOPES,
    WHATSAPP,
    WHATSAPP_NUMBER,
    WhatsAppConfig,
)
from omnisocial.adapters.providers.whatsapp.provider import whatsapp_provider
from omnisocial.adapters.providers.whatsapp.spec import ERRORS, NUMBER_LIMITS, REPLY_WINDOW, SPEC, TEMPLATES
from omnisocial.adapters.providers.whatsapp.webhooks import SIGNATURE_HEADER

__all__ = [
    "BUSINESS_SCOPES",
    "CONNECT_SCOPES",
    "ERRORS",
    "NUMBER_LIMITS",
    "REPLY_WINDOW",
    "SIGNATURE_HEADER",
    "SPEC",
    "TEMPLATES",
    "WHATSAPP",
    "WHATSAPP_NUMBER",
    "WhatsAppConfig",
    "whatsapp_provider",
]
