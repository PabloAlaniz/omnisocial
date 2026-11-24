"""LinkedIn cumple el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.linkedin.provider import linkedin_provider
from omnisocial.adapters.providers.linkedin.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.linkedin.conftest import (
    ACLS,
    BASE,
    ORGANIZATIONS,
    PERSON,
    TOKEN_URL,
    USERINFO,
    config,
    failure,
)

_ERRORS = {
    ErrorKind.TOKEN_DEAD: failure(401, message="Invalid access token"),
    ErrorKind.MISSING_PERMISSION: failure(403, "ACCESS_DENIED", "Not enough permissions"),
    ErrorKind.RATE_LIMITED: failure(429, "TOO_MANY_REQUESTS", "throttle limit reached"),
}


class LinkedInHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return linkedin_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        self.transport.on("POST", TOKEN_URL, {"access_token": "AQV-acceso", "expires_in": 5184000})
        self.transport.on("GET", USERINFO, PERSON)
        self.transport.on("GET", "organizationAcls", ACLS)
        self.transport.on("GET", "organizations", ORGANIZATIONS)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        return _ERRORS.get(kind)


class TestLinkedInCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return LinkedInHarness()
