"""Google Business Profile cumple el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.google_business.provider import google_business_provider
from omnisocial.adapters.providers.google_business.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.google_business.conftest import (
    ACCOUNT_LIST,
    ACCOUNTS,
    LOCATION_LIST,
    LOCATIONS,
    PERSON,
    TOKEN_URL,
    USERINFO_URL,
    config,
    failure,
)

_ERRORS = {
    ErrorKind.TOKEN_DEAD: failure(401, "UNAUTHENTICATED"),
    ErrorKind.MISSING_PERMISSION: failure(403, "PERMISSION_DENIED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"),
    ErrorKind.RATE_LIMITED: failure(429, "RESOURCE_EXHAUSTED", "RATE_LIMIT_EXCEEDED"),
}


class GoogleBusinessHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport()

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return google_business_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        self.transport.on(
            "POST",
            TOKEN_URL,
            {"access_token": "ya29-acceso", "refresh_token": "1//renovar", "expires_in": 3599},
        )
        self.transport.on("GET", USERINFO_URL, PERSON)
        self.transport.on("GET", ACCOUNTS, ACCOUNT_LIST)
        self.transport.on("GET", LOCATIONS, LOCATION_LIST)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return _ERRORS.get(kind)


class TestGoogleBusinessCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return GoogleBusinessHarness()
