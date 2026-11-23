"""El contrato de los repositorios. Lo corren la implementación en memoria y la de PostgreSQL."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from omnisocial.application.ports import AssetRepository, AuthorizationStateStore, ConnectionRepository
from omnisocial.domain.asset import Asset
from omnisocial.domain.authorization import AuthorizationRequest, Purpose
from omnisocial.domain.connection import Connection, ConnectionStatus
from omnisocial.domain.identity import Identity
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.token import Token, TokenKind
from tests.fakes import NOW

P = ProviderId("red")


def connection(connection_id: str = "c1", owner: str = "dueño", subject: str = "u1") -> Connection:
    return Connection(
        id=connection_id,
        provider=P,
        owner=owner,
        subject=Identity(P, subject, name="Ana", email="ana@ejemplo.com", avatar_url="https://img"),
        token=Token(
            TokenKind.USER,
            "acceso",
            refresh_token="renovar",
            expires_at=NOW + timedelta(hours=1),
            scopes=frozenset({"a", "b"}),
        ),
        status=ConnectionStatus.ACTIVE,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def asset(asset_id: str, external_id: str, connection_id: str = "c1", *, token: bool = True) -> Asset:
    return Asset(
        id=asset_id,
        connection_id=connection_id,
        provider=P,
        owner="dueño",
        kind="pagina",
        external_id=external_id,
        name="Página",
        parent_external_id=None,
        token=Token(TokenKind.ASSET, "tok-" + external_id) if token else None,
        capabilities=frozenset({Capability.CONTENT, Capability.INSIGHTS}),
        metadata={"categoria": "bar"},
    )


async def connection_contract(repo: ConnectionRepository) -> None:
    original = connection()
    await repo.add(original)
    assert await repo.get("c1") == original
    assert await repo.get("nada") is None
    assert await repo.find(owner="dueño", provider=P, subject_id="u1") == original
    assert await repo.find(owner="otro", provider=P, subject_id="u1") is None

    updated = original.with_token(Token(TokenKind.USER, "nuevo"), NOW + timedelta(minutes=1))
    assert await repo.save(updated, expected_version=1)
    assert not await repo.save(updated.mark(ConnectionStatus.INVALID, "x", NOW), expected_version=1)
    stored = await repo.get("c1")
    assert stored == updated
    assert stored is not None
    assert stored.token.refresh_token is None

    await repo.add(connection("c2", subject="u2"))
    await repo.add(connection("c3", owner="otro"))
    assert [c.id for c in await repo.list_by_owner("dueño")] == ["c1", "c2"]


async def asset_contract(connections: ConnectionRepository, repo: AssetRepository) -> None:
    await connections.add(connection("c1"))
    await connections.add(connection("c2", owner="otro"))
    await repo.replace_for_connection("c1", [asset("a1", "p1"), asset("a2", "p2", token=False)])
    first = await repo.get("a1")
    assert first == asset("a1", "p1")
    assert (await repo.get("a2")) == asset("a2", "p2", token=False)
    assert await repo.get("nada") is None

    # Reemplazar conserva el id de lo que ya estaba y borra lo que no vino.
    renamed = replace(asset("nuevo-id", "p1"), name="Otro nombre")
    await repo.replace_for_connection("c1", [renamed, asset("a3", "p3")])
    assert [(a.id, a.name) for a in await repo.list_by_connection("c1")] == [
        ("a1", "Otro nombre"),
        ("a3", "Página"),
    ]
    assert await repo.get("a2") is None

    await repo.replace_for_connection("c2", [replace(asset("b1", "p1", connection_id="c2"), owner="otro")])
    assert {a.owner for a in await repo.find_by_external_id(P, "p1")} == {"dueño", "otro"}
    assert [a.id for a in await repo.list_by_owner("dueño")] == ["a1", "a3"]
    assert await repo.list_by_owner("dueño", provider=ProviderId("otra")) == []
    assert [a.id for a in await repo.list_by_owner("dueño", provider=P)] == ["a1", "a3"]

    await repo.replace_for_connection("c1", [])
    assert await repo.list_by_connection("c1") == []


def request(state: str, *, minutes: int = 10) -> AuthorizationRequest:
    return AuthorizationRequest(
        state=state,
        provider=P,
        purpose=Purpose.CONNECT,
        redirect_uri="https://api/cb",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=minutes),
        scopes=("a", "b"),
        owner="dueño",
        return_url="https://app/",
        code_verifier="verificador",
    )


async def state_contract(store: AuthorizationStateStore) -> None:
    await store.put(request("s1"))
    assert await store.take("s1") == request("s1")
    assert await store.take("s1") is None
    assert await store.take("nada") is None
