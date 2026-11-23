from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import pytest

from omnisocial.adapters.http.transport import HttpResponse, Params
from omnisocial.adapters.providers.meta.config import MetaConfig
from omnisocial.adapters.providers.meta.graph import GraphClient
from tests.fakes import FakeClock

BASE = "https://graph.facebook.com/v24.0/"


@dataclass
class Call:
    method: str
    url: str
    params: dict[str, str | int]
    json: Mapping[str, object] | None

    @property
    def path(self) -> str:
        url = self.url.removeprefix(BASE)
        return urlsplit(url).path if url.startswith("http") else url


@dataclass
class FakeGraph:
    """Responde por método y ruta. Cada ruta puede tener varias respuestas en orden."""

    routes: dict[tuple[str, str], list[HttpResponse]] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)

    def on(self, method: str, path: str, *responses: object, status: int = 200) -> None:
        self.routes.setdefault((method, path), []).extend(
            r if isinstance(r, HttpResponse) else HttpResponse(status, r, "x") for r in responses
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Params | None = None,
        json: Mapping[str, object] | None = None,
    ) -> HttpResponse:
        call = Call(method, url, dict(params or {}), json)
        self.calls.append(call)
        key = (method, url.removeprefix(BASE)) if not url.startswith("next:") else (method, url)
        queue = self.routes.get(key)
        if not queue:
            raise AssertionError(f"Sin respuesta para {method} {url}")
        return queue.pop(0) if len(queue) > 1 else queue[0]


def config(**overrides: object) -> MetaConfig:
    values: dict[str, object] = {
        "app_id": "app",
        "app_secret": "secreto",
        "api_version": "v24.0",
        "webhook_verify_token": "verificar",
    }
    values.update(overrides)
    return MetaConfig(**values)  # type: ignore[arg-type]


@pytest.fixture
def fake() -> FakeGraph:
    return FakeGraph()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def graph(fake: FakeGraph) -> GraphClient:
    return GraphClient(config(), fake)
