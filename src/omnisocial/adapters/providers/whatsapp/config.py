"""Configuración de la app de Meta para WhatsApp Business."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId

WHATSAPP = ProviderId("whatsapp")

WHATSAPP_NUMBER = "whatsapp_number"
"""Un número de teléfono de una cuenta de WhatsApp Business. Es el que manda y recibe."""

CONNECT_SCOPES: tuple[str, ...] = ("whatsapp_business_management", "whatsapp_business_messaging")
"""Ver las cuentas, sus números y sus plantillas, y mandar mensajes."""
BUSINESS_SCOPES: tuple[str, ...] = (*CONNECT_SCOPES, "business_management")
"""Además, listar las cuentas de WhatsApp de un portfolio (`business_id`)."""

GRAPH_BASE = "https://graph.facebook.com"
DIALOG_BASE = "https://www.facebook.com"


@dataclass(frozen=True, slots=True, kw_only=True)
class WhatsAppConfig:
    app_id: str
    app_secret: str = field(repr=False)
    api_version: str = "v26.0"
    config_id: str | None = None
    """La configuración de "Facebook Login for Business" con que se autoriza: define qué se pide y qué
    cuentas puede elegir la persona."""
    business_id: str | None = None
    """El portfolio del que se listan las cuentas cuando el token no dice a cuáles tiene acceso (un
    usuario de sistema con acceso a todo)."""
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    webhook_verify_token: str | None = field(default=None, repr=False)
    """El texto que se le dio a Meta al configurar el webhook. Sin él no se confirma la URL."""
    previous_app_secrets: tuple[str, ...] = field(default=(), repr=False)
    """Secretos anteriores que siguen valiendo para verificar avisos mientras se rota el secreto."""
    graph_base: str = GRAPH_BASE
    dialog_base: str = DIALOG_BASE

    @property
    def api_base(self) -> str:
        return f"{self.graph_base}/{self.api_version}"

    @property
    def authorize_url(self) -> str:
        return f"{self.dialog_base}/{self.api_version}/dialog/oauth"
