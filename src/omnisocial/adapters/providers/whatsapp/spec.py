"""La descripción de WhatsApp Business: sus capacidades y qué quiere decir cada error."""

from __future__ import annotations

from datetime import date, timedelta

from omnisocial.adapters.providers.whatsapp.config import WHATSAPP, WHATSAPP_NUMBER
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.lookup import LookupSpec
from omnisocial.domain.messaging import MessagingLimits, ReplyWindow
from omnisocial.domain.provider import Capability
from omnisocial.domain.spec import ApiPin, ErrorTable, NetworkSpec, OAuthSpec

NUMBER_CAPABILITIES = frozenset({Capability.MESSAGING, Capability.WEBHOOKS})

PERMISSION = "permission"
"""Los códigos 10 y 200 a 299 de la Graph API: al token le falta un permiso."""

ERRORS = ErrorTable(
    codes={
        # El token venció o lo revocaron.
        "190": ErrorKind.TOKEN_DEAD,
        PERMISSION: ErrorKind.MISSING_PERMISSION,
        # El número llegó a su tope de mensajes por segundo.
        "130429": ErrorKind.RATE_LIMITED,
        # Demasiados mensajes al mismo destinatario en poco tiempo.
        "131056": ErrorKind.RATE_LIMITED,
        # El número quedó limitado por mandar mensajes que la gente marca como no deseados.
        "131048": ErrorKind.RATE_LIMITED,
        # La cuenta de WhatsApp Business llegó a su tope de llamadas.
        "80007": ErrorKind.RATE_LIMITED,
        # Pasaron más de 24 horas desde el último mensaje de la persona: solo sale una plantilla.
        "131047": ErrorKind.INVALID_REQUEST,
        # No se puede entregar: no usa WhatsApp, no aceptó los términos o tiene una versión vieja.
        "131026": ErrorKind.INVALID_REQUEST,
        "131009": ErrorKind.INVALID_REQUEST,
        "131051": ErrorKind.INVALID_REQUEST,
        # La plantilla no existe o no está aprobada en ese idioma, o sus variables no coinciden.
        "132000": ErrorKind.INVALID_REQUEST,
        "132001": ErrorKind.INVALID_REQUEST,
    },
)

REPLY_WINDOW = ReplyWindow(timedelta(hours=24))
"""Cada mensaje de la persona abre 24 horas para escribirle libremente. Fuera de eso, una plantilla."""

NUMBER_LIMITS = MessagingLimits(
    max_text=4096,
    max_attachments=1,
    attachments_by_url=True,
    templates=True,
    # No hay forma de leer los mensajes pasados: llegan por avisos.
    history=False,
)
MAX_CAPTION = 1024

TEMPLATES = LookupSpec("templates", "Las plantillas de la cuenta, con su idioma y su estado.")


def oauth_spec(authorize_url: str, token_url: str) -> OAuthSpec:
    """El diálogo de Facebook. Los permisos van separados por comas y no hay PKCE."""
    return OAuthSpec(authorize_url=authorize_url, token_url=token_url, scope_separator=",", pkce=False)


SPEC = NetworkSpec(
    id=WHATSAPP,
    name="WhatsApp Business",
    capabilities=frozenset({Capability.LOGIN, Capability.ASSETS, Capability.MESSAGING, Capability.WEBHOOKS}),
    assets={WHATSAPP_NUMBER: NUMBER_CAPABILITIES},
    errors=ERRORS,
    oauth=oauth_spec(
        "https://www.facebook.com/v26.0/dialog/oauth", "https://graph.facebook.com/v26.0/oauth/access_token"
    ),
    docs="docs/whatsapp.md",
    api=ApiPin(
        "v26.0",
        reviewed=date(2026, 11, 24),
        changelog="https://developers.facebook.com/docs/graph-api/changelog",
    ),
    lookups={WHATSAPP_NUMBER: (TEMPLATES,)},
)
