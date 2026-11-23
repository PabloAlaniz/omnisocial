from __future__ import annotations

from typing import Any

import pytest
from psycopg_pool import AsyncConnectionPool

from omnisocial.adapters.crypto.aes_gcm import AesGcmTokenCipher
from omnisocial.adapters.stores.postgres import (
    PostgresAssetRepository,
    PostgresAuthorizationStateStore,
    PostgresConnectionRepository,
)
from tests.adapters.stores.contract import (
    asset,
    asset_contract,
    connection,
    connection_contract,
    request,
    state_contract,
)
from tests.fakes import FakeClock

pytestmark = pytest.mark.integration

Pool = AsyncConnectionPool[Any]


async def test_conexiones(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    await connection_contract(PostgresConnectionRepository(pool, cipher))


async def test_activos(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    await asset_contract(PostgresConnectionRepository(pool, cipher), PostgresAssetRepository(pool, cipher))


async def test_estados(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    await state_contract(PostgresAuthorizationStateStore(pool, cipher, FakeClock()))


async def test_los_tokens_quedan_cifrados_en_la_base(pool: Pool, cipher: AesGcmTokenCipher) -> None:
    connections = PostgresConnectionRepository(pool, cipher)
    await connections.add(connection())
    await PostgresAssetRepository(pool, cipher).replace_for_connection("c1", [asset("a1", "p1")])
    await PostgresAuthorizationStateStore(pool, cipher, FakeClock()).put(request("s1"))
    async with pool.connection() as conn:
        dump = []
        for table in ("omnisocial_connections", "omnisocial_assets", "omnisocial_authorization_states"):
            cur = await conn.execute(f"SELECT * FROM {table}")  # noqa: S608
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
