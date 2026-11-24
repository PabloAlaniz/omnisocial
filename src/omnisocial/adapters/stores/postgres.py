"""Repositorios en PostgreSQL con psycopg 3.

Los tokens se guardan cifrados con un `TokenCipher`. El resto de los datos va en claro para poder
consultarlos: dueño, red, activo, vencimiento.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from omniwebhook.postgres import postgres_store_schema
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from typing_extensions import override

from omnisocial.application.ports import (
    AssetRepository,
    AuthorizationStateStore,
    Clock,
    ConnectionRepository,
    PublicationRepository,
    QuotaLedger,
    ServerAppStore,
    TokenCipher,
)
from omnisocial.domain.asset import Asset
from omnisocial.domain.authorization import AuthorizationRequest, Purpose, ServerApp
from omnisocial.domain.connection import Connection, ConnectionStatus
from omnisocial.domain.identity import Identity
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.publishing import Publication, PublicationStatus
from omnisocial.domain.token import Token, TokenKind

SCHEMA = """
CREATE TABLE IF NOT EXISTS omnisocial_connections (
    id               text PRIMARY KEY,
    provider         text NOT NULL,
    owner            text NOT NULL,
    subject_id       text NOT NULL,
    subject_name     text,
    subject_email    text,
    subject_avatar   text,
    token_kind       text NOT NULL,
    token_secret     text NOT NULL,
    token_expires_at timestamptz,
    token_scopes     text[] NOT NULL DEFAULT '{}',
    status           text NOT NULL,
    status_reason    text,
    version          integer NOT NULL,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL,
    UNIQUE (owner, provider, subject_id)
);

CREATE TABLE IF NOT EXISTS omnisocial_assets (
    id                 text PRIMARY KEY,
    connection_id      text NOT NULL REFERENCES omnisocial_connections (id) ON DELETE CASCADE,
    provider           text NOT NULL,
    owner              text NOT NULL,
    kind               text NOT NULL,
    external_id        text NOT NULL,
    name               text,
    parent_external_id text,
    token_kind         text,
    token_secret       text,
    token_expires_at   timestamptz,
    capabilities       text[] NOT NULL DEFAULT '{}',
    metadata           jsonb NOT NULL DEFAULT '{}',
    UNIQUE (connection_id, kind, external_id)
);
CREATE INDEX IF NOT EXISTS omnisocial_assets_external ON omnisocial_assets (provider, external_id);
CREATE INDEX IF NOT EXISTS omnisocial_assets_owner ON omnisocial_assets (owner, provider);

CREATE TABLE IF NOT EXISTS omnisocial_authorization_states (
    state      text PRIMARY KEY,
    request    text NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS omnisocial_states_expiry ON omnisocial_authorization_states (expires_at);

CREATE TABLE IF NOT EXISTS omnisocial_publications (
    id              text PRIMARY KEY,
    asset_id        text NOT NULL,
    owner           text NOT NULL,
    provider        text NOT NULL,
    status          text NOT NULL,
    idempotency_key text,
    post_id         text,
    url             text,
    error           text,
    resume          jsonb NOT NULL DEFAULT '{}',
    version         integer NOT NULL,
    created_at      timestamptz NOT NULL,
    updated_at      timestamptz NOT NULL,
    UNIQUE (asset_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS omnisocial_publications_owner ON omnisocial_publications (owner, created_at);

CREATE TABLE IF NOT EXISTS omnisocial_server_apps (
    provider      text NOT NULL,
    server        text NOT NULL,
    redirect_uri  text NOT NULL,
    client_id     text NOT NULL,
    client_secret text NOT NULL,
    PRIMARY KEY (provider, server)
);

CREATE TABLE IF NOT EXISTS omnisocial_quota (
    key    text NOT NULL,
    period text NOT NULL,
    used   integer NOT NULL,
    PRIMARY KEY (key, period)
);
"""


async def create_schema(pool: AsyncConnectionPool[Any]) -> None:
    """Las tablas de omnisocial y la de reservas de webhooks de omniwebhook."""
    async with pool.connection() as conn:
        await conn.execute(SCHEMA)
        await conn.execute(postgres_store_schema())


def _seal(cipher: TokenCipher, token: Token, context: str) -> str:
    secret = {
        "access_token": token.access_token,
        "refresh_token": token.refresh_token,
        "server": token.server,
    }
    return cipher.encrypt(json.dumps(secret), context=context)


def _open(cipher: TokenCipher, row: dict[str, Any], context: str) -> Token:
    secret = json.loads(cipher.decrypt(row["token_secret"], context=context))
    return Token(
        kind=TokenKind(row["token_kind"]),
        access_token=secret["access_token"],
        refresh_token=secret.get("refresh_token"),
        expires_at=row["token_expires_at"],
        scopes=frozenset(row.get("token_scopes") or ()),
        server=secret.get("server"),
    )


class PostgresConnectionRepository(ConnectionRepository):
    def __init__(self, pool: AsyncConnectionPool[Any], cipher: TokenCipher) -> None:
        self._pool = pool
        self._cipher = cipher

    @staticmethod
    def _context(connection_id: str) -> str:
        return f"omnisocial|connection|{connection_id}"

    def _row_to_connection(self, row: dict[str, Any]) -> Connection:
        provider = ProviderId(row["provider"])
        return Connection(
            id=row["id"],
            provider=provider,
            owner=row["owner"],
            subject=Identity(
                provider,
                row["subject_id"],
                name=row["subject_name"],
                email=row["subject_email"],
                avatar_url=row["subject_avatar"],
            ),
            token=_open(self._cipher, row, self._context(row["id"])),
            status=ConnectionStatus(row["status"]),
            status_reason=row["status_reason"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def _fetch(self, sql: str, params: Sequence[object]) -> list[Connection]:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return [self._row_to_connection(row) for row in await cur.fetchall()]

    @override
    async def get(self, connection_id: str) -> Connection | None:
        rows = await self._fetch("SELECT * FROM omnisocial_connections WHERE id = %s", [connection_id])
        return rows[0] if rows else None

    @override
    async def find(self, *, owner: str, provider: ProviderId, subject_id: str) -> Connection | None:
        rows = await self._fetch(
            "SELECT * FROM omnisocial_connections WHERE owner = %s AND provider = %s AND subject_id = %s",
            [owner, provider, subject_id],
        )
        return rows[0] if rows else None

    @override
    async def list_by_owner(self, owner: str) -> Sequence[Connection]:
        return await self._fetch(
            "SELECT * FROM omnisocial_connections WHERE owner = %s ORDER BY created_at, id", [owner]
        )

    @override
    async def list_expiring(self, before: datetime, *, limit: int) -> Sequence[Connection]:
        return await self._fetch(
            "SELECT * FROM omnisocial_connections WHERE status = %s AND token_expires_at <= %s "
            "ORDER BY token_expires_at, id LIMIT %s",
            [ConnectionStatus.ACTIVE.value, before, limit],
        )

    def _values(self, c: Connection) -> dict[str, object]:
        return {
            "id": c.id,
            "provider": c.provider,
            "owner": c.owner,
            "subject_id": c.subject.external_id,
            "subject_name": c.subject.name,
            "subject_email": c.subject.email,
            "subject_avatar": c.subject.avatar_url,
            "token_kind": c.token.kind.value,
            "token_secret": _seal(self._cipher, c.token, self._context(c.id)),
            "token_expires_at": c.token.expires_at,
            "token_scopes": sorted(c.token.scopes),
            "status": c.status.value,
            "status_reason": c.status_reason,
            "version": c.version,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }

    @override
    async def add(self, connection: Connection) -> None:
        values = self._values(connection)
        columns = ", ".join(values)
        placeholders = ", ".join(f"%({k})s" for k in values)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO omnisocial_connections ({columns}) VALUES ({placeholders})",  # noqa: S608
                values,
            )

    @override
    async def save(self, connection: Connection, *, expected_version: int) -> bool:
        values = self._values(connection)
        assignments = ", ".join(f"{k} = %({k})s" for k in values if k not in {"id", "created_at"})
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE omnisocial_connections SET {assignments} "  # noqa: S608
                "WHERE id = %(id)s AND version = %(expected_version)s",
                {**values, "expected_version": expected_version},
            )
            return bool(cur.rowcount == 1)


class PostgresAssetRepository(AssetRepository):
    def __init__(self, pool: AsyncConnectionPool[Any], cipher: TokenCipher) -> None:
        self._pool = pool
        self._cipher = cipher

    @staticmethod
    def _context(asset_id: str) -> str:
        return f"omnisocial|asset|{asset_id}"

    def _row_to_asset(self, row: dict[str, Any]) -> Asset:
        token = _open(self._cipher, row, self._context(row["id"])) if row["token_secret"] else None
        return Asset(
            id=row["id"],
            connection_id=row["connection_id"],
            provider=ProviderId(row["provider"]),
            owner=row["owner"],
            kind=row["kind"],
            external_id=row["external_id"],
            name=row["name"],
            parent_external_id=row["parent_external_id"],
            token=token,
            capabilities=frozenset(Capability(c) for c in row["capabilities"] if c in Capability),
            metadata=dict(row["metadata"] or {}),
        )

    async def _fetch(self, sql: str, params: Sequence[object]) -> list[Asset]:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return [self._row_to_asset(row) for row in await cur.fetchall()]

    @override
    async def get(self, asset_id: str) -> Asset | None:
        rows = await self._fetch("SELECT * FROM omnisocial_assets WHERE id = %s", [asset_id])
        return rows[0] if rows else None

    @override
    async def list_by_owner(self, owner: str, *, provider: ProviderId | None = None) -> Sequence[Asset]:
        if provider is None:
            return await self._fetch("SELECT * FROM omnisocial_assets WHERE owner = %s ORDER BY id", [owner])
        return await self._fetch(
            "SELECT * FROM omnisocial_assets WHERE owner = %s AND provider = %s ORDER BY id",
            [owner, provider],
        )

    @override
    async def list_by_connection(self, connection_id: str) -> Sequence[Asset]:
        return await self._fetch(
            "SELECT * FROM omnisocial_assets WHERE connection_id = %s ORDER BY id", [connection_id]
        )

    @override
    async def find_by_external_id(self, provider: ProviderId, external_id: str) -> Sequence[Asset]:
        return await self._fetch(
            "SELECT * FROM omnisocial_assets WHERE provider = %s AND external_id = %s ORDER BY id",
            [provider, external_id],
        )

    @override
    async def replace_for_connection(self, connection_id: str, assets: Sequence[Asset]) -> None:
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT id, kind, external_id FROM omnisocial_assets WHERE connection_id = %s FOR UPDATE",
                [connection_id],
            )
            known = {(row["kind"], row["external_id"]): row["id"] for row in await cur.fetchall()}
            keep: list[str] = []
            for asset in assets:
                asset_id = known.get((asset.kind, asset.external_id), asset.id)
                keep.append(asset_id)
                token = asset.token
                await cur.execute(
                    """
                    INSERT INTO omnisocial_assets (
                        id, connection_id, provider, owner, kind, external_id, name, parent_external_id,
                        token_kind, token_secret, token_expires_at, capabilities, metadata
                    ) VALUES (
                        %(id)s, %(connection_id)s, %(provider)s, %(owner)s, %(kind)s, %(external_id)s,
                        %(name)s, %(parent)s, %(token_kind)s, %(token_secret)s, %(token_expires_at)s,
                        %(capabilities)s,
                        %(metadata)s
                    )
                    ON CONFLICT (connection_id, kind, external_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        owner = EXCLUDED.owner,
                        parent_external_id = EXCLUDED.parent_external_id,
                        token_kind = EXCLUDED.token_kind,
                        token_secret = EXCLUDED.token_secret,
                        token_expires_at = EXCLUDED.token_expires_at,
                        capabilities = EXCLUDED.capabilities,
                        metadata = EXCLUDED.metadata
                    """,
                    {
                        "id": asset_id,
                        "connection_id": connection_id,
                        "provider": asset.provider,
                        "owner": asset.owner,
                        "kind": asset.kind,
                        "external_id": asset.external_id,
                        "name": asset.name,
                        "parent": asset.parent_external_id,
                        "token_kind": token.kind.value if token else None,
                        "token_secret": _seal(self._cipher, token, self._context(asset_id))
                        if token
                        else None,
                        "token_expires_at": token.expires_at if token else None,
                        "capabilities": sorted(c.value for c in asset.capabilities),
                        "metadata": Jsonb(dict(asset.metadata)),
                    },
                )
            await cur.execute(
                "DELETE FROM omnisocial_assets WHERE connection_id = %s AND NOT (id = ANY(%s))",
                [connection_id, keep],
            )


def _request_to_json(request: AuthorizationRequest) -> str:
    return json.dumps(
        {
            "state": request.state,
            "provider": request.provider,
            "purpose": request.purpose.value,
            "redirect_uri": request.redirect_uri,
            "created_at": request.created_at.isoformat(),
            "expires_at": request.expires_at.isoformat(),
            "scopes": list(request.scopes),
            "owner": request.owner,
            "return_url": request.return_url,
            "code_verifier": request.code_verifier,
            "server": request.server,
        }
    )


def _request_from_json(raw: str) -> AuthorizationRequest:
    data = json.loads(raw)
    return AuthorizationRequest(
        state=data["state"],
        provider=ProviderId(data["provider"]),
        purpose=Purpose(data["purpose"]),
        redirect_uri=data["redirect_uri"],
        created_at=datetime.fromisoformat(data["created_at"]),
        expires_at=datetime.fromisoformat(data["expires_at"]),
        scopes=tuple(data["scopes"]),
        owner=data["owner"],
        return_url=data["return_url"],
        code_verifier=data["code_verifier"],
        server=data.get("server"),
    )


class PostgresAuthorizationStateStore(AuthorizationStateStore):
    """El pedido entero va cifrado: lleva el `code_verifier` de PKCE."""

    def __init__(self, pool: AsyncConnectionPool[Any], cipher: TokenCipher, clock: Clock) -> None:
        self._pool = pool
        self._cipher = cipher
        self._clock = clock

    @staticmethod
    def _context(state: str) -> str:
        return f"omnisocial|state|{state}"

    @override
    async def put(self, request: AuthorizationRequest) -> None:
        sealed = self._cipher.encrypt(_request_to_json(request), context=self._context(request.state))
        async with self._pool.connection() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM omnisocial_authorization_states WHERE expires_at < %s", [self._clock.now()]
            )
            await conn.execute(
                "INSERT INTO omnisocial_authorization_states (state, request, expires_at) "
                "VALUES (%s, %s, %s)",
                [request.state, sealed, request.expires_at],
            )

    @override
    async def take(self, state: str) -> AuthorizationRequest | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM omnisocial_authorization_states WHERE state = %s RETURNING request", [state]
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return _request_from_json(self._cipher.decrypt(row[0], context=self._context(state)))


class PostgresPublicationRepository(PublicationRepository):
    """Las publicaciones en curso y sus claves de idempotencia. No guarda tokens ni el contenido."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    @staticmethod
    def _row_to_publication(row: dict[str, Any]) -> Publication:
        return Publication(
            id=row["id"],
            asset_id=row["asset_id"],
            owner=row["owner"],
            provider=ProviderId(row["provider"]),
            status=PublicationStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            idempotency_key=row["idempotency_key"],
            post_id=row["post_id"],
            url=row["url"],
            error=row["error"],
            resume=dict(row["resume"]),
            version=row["version"],
        )

    @staticmethod
    def _values(p: Publication) -> dict[str, object]:
        return {
            "id": p.id,
            "asset_id": p.asset_id,
            "owner": p.owner,
            "provider": p.provider,
            "status": p.status.value,
            "idempotency_key": p.idempotency_key,
            "post_id": p.post_id,
            "url": p.url,
            "error": p.error,
            "resume": Jsonb(dict(p.resume)),
            "version": p.version,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }

    async def _one(self, sql: str, params: Sequence[object]) -> Publication | None:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
            return self._row_to_publication(row) if row else None

    @override
    async def get(self, publication_id: str) -> Publication | None:
        return await self._one("SELECT * FROM omnisocial_publications WHERE id = %s", [publication_id])

    @override
    async def find_by_key(self, asset_id: str, idempotency_key: str) -> Publication | None:
        return await self._one(
            "SELECT * FROM omnisocial_publications WHERE asset_id = %s AND idempotency_key = %s",
            [asset_id, idempotency_key],
        )

    @override
    async def add(self, publication: Publication) -> bool:
        values = self._values(publication)
        columns = ", ".join(values)
        placeholders = ", ".join(f"%({k})s" for k in values)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"INSERT INTO omnisocial_publications ({columns}) VALUES ({placeholders}) "  # noqa: S608
                "ON CONFLICT (asset_id, idempotency_key) DO NOTHING",
                values,
            )
            return bool(cur.rowcount == 1)

    @override
    async def save(self, publication: Publication, *, expected_version: int) -> bool:
        values = self._values(publication)
        assignments = ", ".join(f"{k} = %({k})s" for k in values if k not in {"id", "created_at"})
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE omnisocial_publications SET {assignments} "  # noqa: S608
                "WHERE id = %(id)s AND version = %(expected_version)s",
                {**values, "expected_version": expected_version},
            )
            return bool(cur.rowcount == 1)

    @override
    async def remove(self, publication_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM omnisocial_publications WHERE id = %s", [publication_id])


class PostgresQuotaLedger(QuotaLedger):
    """La cuota gastada, compartida entre procesos."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    @override
    async def spend(self, key: str, period: str, units: int, *, limit: int) -> bool:
        if units > limit:
            return False
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO omnisocial_quota (key, period, used) VALUES (%s, %s, %s) "
                "ON CONFLICT (key, period) DO UPDATE SET used = omnisocial_quota.used + EXCLUDED.used "
                "WHERE omnisocial_quota.used + EXCLUDED.used <= %s",
                [key, period, units, limit],
            )
            return bool(cur.rowcount == 1)

    @override
    async def spent(self, key: str, period: str) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT used FROM omnisocial_quota WHERE key = %s AND period = %s", [key, period]
            )
            row = await cur.fetchone()
            return int(row[0]) if row else 0


class PostgresServerAppStore(ServerAppStore):
    """Las apps registradas en cada servidor de una red federada. El secreto va cifrado."""

    def __init__(self, pool: AsyncConnectionPool[Any], cipher: TokenCipher) -> None:
        self._pool = pool
        self._cipher = cipher

    @staticmethod
    def _context(provider: str, server: str) -> str:
        return f"omnisocial|server_app|{provider}|{server}"

    def _values(self, app: ServerApp) -> list[object]:
        sealed = self._cipher.encrypt(app.client_secret, context=self._context(app.provider, app.server))
        return [app.provider, app.server, app.redirect_uri, app.client_id, sealed]

    @override
    async def get(self, provider: ProviderId, server: str) -> ServerApp | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT redirect_uri, client_id, client_secret FROM omnisocial_server_apps "
                "WHERE provider = %s AND server = %s",
                [provider, server],
            )
            row = await cur.fetchone()
        if row is None:
            return None
        secret = self._cipher.decrypt(row[2], context=self._context(provider, server))
        return ServerApp(provider, server, row[0], row[1], secret)

    @override
    async def add(self, app: ServerApp) -> ServerApp:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO omnisocial_server_apps "
                "(provider, server, redirect_uri, client_id, client_secret) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                self._values(app),
            )
        return await self.get(app.provider, app.server) or app

    @override
    async def replace(self, app: ServerApp) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO omnisocial_server_apps "
                "(provider, server, redirect_uri, client_id, client_secret) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (provider, server) DO UPDATE SET "
                "redirect_uri = EXCLUDED.redirect_uri, client_id = EXCLUDED.client_id, "
                "client_secret = EXCLUDED.client_secret",
                self._values(app),
            )
