"""Cada red contra su API real, con una cuenta de prueba.

Se corre con `uv run pytest -m live --no-cov tests/live`. Una red sin su variable se saltea. Por defecto
solo lee; con `OMNISOCIAL_LIVE_WRITE=1` y un armado que traiga `write`, además publica un texto y lo
borra.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from omniwebhook import AsyncMemoryIdempotencyStore

from omnisocial.adapters.http.httpx_transport import HttpxTransport
from omnisocial.adapters.http.retrying import RetryingTransport
from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
)
from omnisocial.adapters.system import SystemClock
from omnisocial.application.results import Connected, Done, Refusal, Refused
from omnisocial.domain.asset import Asset
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import Draft
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.entrypoints.hub import Omnisocial
from tests.live.armado import NETWORKS, REPORT, WRITE, Setup, build, options, parse, variable

pytestmark = pytest.mark.live


class Report:
    """Qué se comprobó y cómo salió. Solo nombres y motivos: nunca un token ni el contenido de una cuenta."""

    def __init__(self, network: str) -> None:
        self.network = network
        self.checks: list[dict[str, object]] = []

    def add(self, name: str, result: object) -> None:
        ok = not isinstance(result, Refused) or result.reason is Refusal.NOT_SUPPORTED
        reason = str(result.reason) if isinstance(result, Refused) else None
        self.checks.append({"check": name, "ok": ok, "reason": reason})

    @property
    def failed(self) -> list[str]:
        return [f"{check['check']}: {check['reason']}" for check in self.checks if not check["ok"]]

    def save(self) -> None:
        path = os.environ.get(REPORT)
        if not path:
            return
        line = {"network": self.network, "at": datetime.now(UTC).isoformat(), "checks": self.checks}
        with Path(path).open("a", encoding="utf-8") as report:
            report.write(json.dumps(line) + "\n")


def _social(setup: Setup) -> Omnisocial:
    clock = SystemClock()
    return Omnisocial.build(
        providers=[build(setup, RetryingTransport(HttpxTransport()))],
        connections=InMemoryConnectionRepository(),
        assets=InMemoryAssetRepository(),
        states=InMemoryAuthorizationStateStore(clock),
        webhook_events=AsyncMemoryIdempotencyStore(),
        redirect_uri_for=lambda _: "https://ejemplo.invalid/callback",
        return_urls=ReturnUrlPolicy.of("https://ejemplo.invalid"),
        clock=clock,
    )


async def _connect(social: Omnisocial, setup: Setup) -> object:
    if setup.token is not None:
        return await social.register_system_connection.execute(
            setup.network, owner="en-vivo", token=setup.token
        )
    return await social.connect_with_credentials.execute(
        setup.network, owner="en-vivo", credentials=setup.credentials
    )


async def _read(social: Omnisocial, asset: Asset, report: Report) -> None:
    """Lo que se puede leer sin cambiar nada en la cuenta."""
    if Capability.CONTENT in asset.capabilities:
        posts = await social.list_posts.execute(asset.id, limit=1)
        report.add(f"{asset.kind}: publicaciones", posts)
        if isinstance(posts, Done) and posts.value and Capability.COMMENTS in asset.capabilities:
            comments = await social.list_comments.execute(asset.id, object_id=posts.value[0].external_id)
            report.add(f"{asset.kind}: comentarios", comments)
    available = await social.list_choices.available(asset.id)
    for lookup in available.value if isinstance(available, Done) else ():
        if lookup.parent is None:
            report.add(
                f"{asset.kind}: consulta {lookup.name}",
                await social.list_choices.execute(asset.id, lookup.name),
            )
    if Capability.MESSAGING in asset.capabilities:
        report.add(
            f"{asset.kind}: conversaciones", await social.list_conversations.execute(asset.id, limit=1)
        )


async def _write(social: Omnisocial, asset: Asset, setup: Setup, report: Report) -> None:
    """Publica un texto y lo borra. Solo si se pidió, y en la cuenta de prueba."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    draft = Draft(f"Prueba automática de omnisocial ({stamp} UTC). Se borra sola.", options=options(setup))
    published = await social.publish.execute(asset.id, draft)
    report.add(f"{asset.kind}: publicar", published)
    if isinstance(published, Done) and published.value.post_id:
        deleted = await social.delete_post.execute(asset.id, post_id=published.value.post_id)
        report.add(f"{asset.kind}: borrar", deleted)


Step = Callable[[], Awaitable[None]]


@pytest.mark.parametrize("network", NETWORKS)
async def test_la_red_responde_como_espera_el_adaptador(network: str) -> None:
    raw = os.environ.get(variable(network))
    if not raw:
        pytest.skip(f"Sin {variable(network)}: esta red no se prueba en vivo.")
    setup = parse(network, raw)
    social = _social(setup)
    report = Report(network)
    try:
        connected = await _connect(social, setup)
        report.add("conectar", connected)
        if isinstance(connected, Connected):
            writes = os.environ.get(WRITE) == "1" and setup.write is not None
            for asset in connected.assets:
                await _read(social, asset, report)
                if writes and Capability.PUBLISHING in asset.capabilities:
                    await _write(social, asset, setup, report)
    finally:
        report.save()
    assert not report.failed, f"{network}: {'; '.join(report.failed)}"
