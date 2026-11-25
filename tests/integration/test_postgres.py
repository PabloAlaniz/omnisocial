from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from omniwebhook.postgres import AsyncPostgresIdempotencyStore, AsyncPsycopgClient
from psycopg_pool import AsyncConnectionPool

from omnisocial.adapters.crypto.aes_gcm import AesGcmTokenCipher
from omnisocial.adapters.stores.postgres import (
    PostgresAssetRepository,
    PostgresAuthorizationStateStore,
    PostgresConnectionRepository,
    PostgresPublicationRepository,
    PostgresQuotaLedger,
    PostgresRateLimitStore,
    PostgresServerAppStore,
)
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.entrypoints.hub import Omnisocial
from tests.adapters.stores.contract import (
    asset,
    asset_contract,
    connection,
    connection_contract,
    publication_contract,
    quota_contract,
    request,
    server_app_contract,
    state_contract,
)
from tests.fakes import FakeClock, FakeNetwork, incoming, sign

pytestmark = pytest.mark.integration

Pool = AsyncConnectionPool[Any]


async def test_conexiones(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    await connection_contract(PostgresConnectionRepository(pool, cipher))


async def test_activos(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    await asset_contract(PostgresConnectionRepository(pool, cipher), PostgresAssetRepository(pool, cipher))


async def test_estados(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    await state_contract(PostgresAuthorizationStateStore(pool, cipher, FakeClock()))


async def test_publicaciones(pool: Pool) -> None:
    await publication_contract(PostgresPublicationRepository(pool))


async def test_apps_por_servidor(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    await server_app_contract(PostgresServerAppStore(pool, cipher))
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT client_secret FROM omnisocial_server_apps")
        assert "secreto-1" not in repr(await cur.fetchall())


async def test_el_servidor_del_token_se_guarda_con_el(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    connections = PostgresConnectionRepository(pool, cipher)
    federated = connection("c9", subject="u9")
    token = replace(federated.token, server="mastodon.social")
    await connections.add(replace(federated, token=token))
    stored = await connections.get("c9")
    assert stored is not None
    assert stored.token.server == "mastodon.social"


async def test_cuota(pool: Pool) -> None:
    await quota_contract(PostgresQuotaLedger(pool))


async def test_los_turnos_se_comparten_y_una_espera_no_acorta_otra(pool: Pool) -> None:
    limits = PostgresRateLimitStore(pool)
    assert await limits.reserve("reddit", 2.0) == 0.0
    # El segundo que pide tiene que esperar lo que dejó el primero.
    assert 1.5 < await limits.reserve("reddit", 2.0) <= 2.0
    assert await limits.reserve("pinterest", 2.0) == 0.0
    await limits.pause("pinterest", 60)
    await limits.pause("pinterest", 5)
    assert 59 < await limits.reserve("pinterest", 0) <= 60
    await limits.pause("nueva", 30)
    assert 29 < await limits.reserve("nueva", 0) <= 30


async def test_los_tokens_quedan_cifrados_en_la_base(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    connections = PostgresConnectionRepository(pool, cipher)
    await connections.add(connection())
    await PostgresAssetRepository(pool, cipher).replace_for_connection("c1", [asset("a1", "p1")])
    await PostgresAuthorizationStateStore(pool, cipher, FakeClock()).put(request("s1"))
    async with pool.connection() as conn:
        dump = []
        for table in ("omnisocial_connections", "omnisocial_assets", "omnisocial_authorization_states"):
            cur = await conn.execute(f"SELECT * FROM {table}")
            dump.append(repr(await cur.fetchall()))
    text = "\n".join(dump)
    for secret in ("acceso", "renovar", "tok-p1", "verificador"):
        assert secret not in text


async def test_un_token_movido_de_fila_no_se_descifra(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    connections = PostgresConnectionRepository(pool, cipher)
    await connections.add(connection("c1"))
    await connections.add(connection("c2", subject="u2"))
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE omnisocial_connections SET token_secret = "
            "(SELECT token_secret FROM omnisocial_connections WHERE id = 'c1') WHERE id = 'c2'"
        )
    with pytest.raises(Exception, match="descifrar"):
        await connections.get("c2")


async def test_webhooks_sin_duplicados_entre_procesos(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    """Dos instancias de la app con la misma base: el aviso repetido no se procesa dos veces."""

    def instance() -> Omnisocial:
        clock = FakeClock()
        return Omnisocial.build(
            providers=[FakeNetwork().provider()],
            connections=PostgresConnectionRepository(pool, cipher),
            assets=PostgresAssetRepository(pool, cipher),
            states=PostgresAuthorizationStateStore(pool, cipher, clock),
            webhook_events=AsyncPostgresIdempotencyStore(AsyncPsycopgClient(pool.connection)),
            redirect_uri_for=lambda provider: f"https://api/{provider}",
            return_urls=ReturnUrlPolicy.of("https://app.ejemplo.com"),
            clock=clock,
        )

    received: list[object] = []

    async def on_events(events: object) -> None:
        received.append(events)

    request = incoming(b"pag-1", sign(b"pag-1"))
    first = await instance().handle_webhook.execute("falsa", request=request, on_events=on_events)
    second = await instance().handle_webhook.execute("falsa", request=request, on_events=on_events)
    assert (first.outcome, second.outcome) == ("ok", "duplicate")
    assert len(received) == 1
