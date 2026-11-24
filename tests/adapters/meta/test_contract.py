"""Meta cumple el contrato común de las redes."""

from __future__ import annotations

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.meta.provider import meta_provider
from omnisocial.adapters.providers.meta.spec import SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.spec import NetworkSpec
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.adapters.meta.conftest import BASE, config

_CODES = {ErrorKind.TOKEN_DEAD: 190, ErrorKind.MISSING_PERMISSION: 200, ErrorKind.RATE_LIMITED: 4}


class MetaHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return SPEC

    @override
    def provider(self) -> Provider:
        return meta_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        self.transport.on(
            "GET",
            "oauth/access_token",
            {"access_token": "corto"},
            {"access_token": "largo", "expires_in": 5184000},
        )
        self.transport.on("GET", "me/permissions", {"data": []})
        self.transport.on("GET", "me", {"id": "persona-1", "name": "Ana"})
        page = {
            "id": "p1",
            "name": "Página",
            "access_token": "tok-p1",
            "instagram_business_account": {"id": "ig1"},
        }
        self.transport.on("GET", "me/accounts", {"data": [page]})

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        code = _CODES.get(kind)
        if code is None:
            return None
        return HttpResponse(400, {"error": {"code": code, "message": "no"}}, "")


class TestMetaCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return MetaHarness()
