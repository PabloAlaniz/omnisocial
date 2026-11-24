from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from omnisocial.adapters.http.transport import HttpResponse, Params
from omnisocial.adapters.providers.tiktok.client import TikTokClient
from omnisocial.adapters.providers.tiktok.config import TikTokConfig
from tests.fakes import FakeClock

BASE = "https://open.tiktokapis.com/v2/"


@dataclass
class Call:
    method: str
    path: str
    params: dict[str, str | int]
    json: Mapping[str, object] | None
    form: Mapping[str, str] | None
    headers: Mapping[str, str] | None
    retry_safe: str | None


@dataclass
class FakeTikTok:
    """Responde por método y ruta (sin la base). Cada ruta puede tener varias respuestas en orden."""

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
        form: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        retry_safe: str | None = None,
        content: bytes | None = None,
    ) -> HttpResponse:
        path = url.removeprefix(BASE)
        self.calls.append(Call(method, path, dict(params or {}), json, form, headers, retry_safe))
        queue = self.routes.get((method, path))
        if not queue:
            raise AssertionError(f"Sin respuesta para {method} {path}")
        return queue.pop(0) if len(queue) > 1 else queue[0]


def ok(data: object) -> dict[str, object]:
    return {"data": data, "error": {"code": "ok", "message": "", "log_id": "l"}}


def failure(code: str, message: str = "falló") -> dict[str, object]:
    return {"data": {}, "error": {"code": code, "message": message, "log_id": "l"}}


def config(**overrides: object) -> TikTokConfig:
    values: dict[str, object] = {"client_key": "clave", "client_secret": "secreto"}
    values.update(overrides)
    return TikTokConfig(**values)  # type: ignore[arg-type]


@pytest.fixture
def fake() -> FakeTikTok:
    return FakeTikTok()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(fake: FakeTikTok) -> TikTokClient:
    return TikTokClient(config(), fake)
