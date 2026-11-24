from __future__ import annotations

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
)
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.entrypoints.hub import Omnisocial
from tests.adapters.stores.contract import (
    asset,
    asset_contract,
    connection,
    connection_contract,
    publication_contract,
    request,
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
