"""WhatsApp Business cumple el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.whatsapp.provider import whatsapp_provider
from omnisocial.adapters.providers.whatsapp.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.whatsapp.conftest import BASE, INSPECTED, ME, NUMBERS, config, failure

_ERRORS = {
    ErrorKind.TOKEN_DEAD: failure(401, 190, "Error validating access token"),
    ErrorKind.MISSING_PERMISSION: failure(403, 200, "Permissions error"),
    ErrorKind.RATE_LIMITED: failure(429, 130429, "Rate limit hit"),
}
TEMPLATES = {"data": [{"name": "recordatorio", "language": "es_AR", "status": "APPROVED"}]}


class WhatsAppHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return whatsapp_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        self.transport.on(
            "POST", "oauth/access_token", {"access_token": "EAAG-acceso", "token_type": "bearer"}
        )
        self.transport.on("GET", "me", ME)
        self.transport.on("GET", "debug_token", INSPECTED)
        self.transport.on("GET", "102290129340398/phone_numbers", NUMBERS)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return _ERRORS.get(kind)

    @override
    def script_lookups(self) -> None:
        self.transport.on("GET", "102290129340398/message_templates", TEMPLATES)


class TestWhatsAppCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return WhatsAppHarness()
