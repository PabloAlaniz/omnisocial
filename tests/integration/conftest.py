from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from psycopg_pool import AsyncConnectionPool

from omnisocial.adapters.crypto.aes_gcm import AesGcmTokenCipher, generate_key
from omnisocial.adapters.stores.postgres import create_schema

URL = os.environ.get("OMNISOCIAL_PG_URL", "postgresql://postgres:prueba@127.0.0.1:55499/postgres")


@pytest.fixture
async def pool() -> AsyncIterator[AsyncConnectionPool[Any]]:
    async with AsyncConnectionPool(URL, min_size=1, max_size=4, open=False, timeout=10) as pool:
        await pool.wait(timeout=10)
        async with pool.connection() as conn:
            await conn.execute(
                "DROP TABLE IF EXISTS omnisocial_assets, omnisocial_connections, "
                "omnisocial_authorization_states, omnisocial_publications, omniwebhook_events"
            )
        await create_schema(pool)
        yield pool


@pytest.fixture
def cipher() -> AesGcmTokenCipher:
    return AesGcmTokenCipher({"k1": generate_key()}, active="k1")
