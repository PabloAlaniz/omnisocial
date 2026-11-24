"""Redes federadas y conexión por credencial, con dobles."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta

import pytest
from omniwebhook import AsyncMemoryIdempotencyStore

from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
)
from omnisocial.application.registry import Provider
from omnisocial.application.results import (
    AuthorizationStarted,
    Connected,
    LoggedIn,
    Refusal,
    Refused,
    ValidToken,
)
from omnisocial.domain.authorization import CredentialField, Purpose
from omnisocial.domain.connection import ConnectionStatus
from omnisocial.domain.errors import CapabilityNotSupported, ProviderError, RateLimited, TokenRejected
from omnisocial.domain.identity import Identity
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.domain.token import Token, TokenKind
from omnisocial.entrypoints.hub import Omnisocial
from tests.fakes import FakeClock, FakeSecrets, SequentialIds

FEDI = ProviderId("fedi")
CIELO = ProviderId("cielo")


class Quien:
    async def identity(self, token: Token) -> Identity:
        # La misma persona en dos servidores son dos identidades.
        return Identity(token_provider(token), f"u1@{token.server}")


def token_provider(token: Token) -> ProviderId:
    return FEDI if token.access_token.startswith("fedi") else CIELO


@dataclass
class FakeServerOAuth:
    supports_pkce: bool = True
    seen: list[tuple[str, str]] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)

    def default_scopes(self, purpose: Purpose) -> tuple[str, ...]:
        return ("read",) if purpose is Purpose.LOGIN else ("read", "write")

    async def authorization_url(
        self, server: str, *, state: str, redirect_uri: str, scopes: Sequence[str], code_challenge: str | None
    ) -> str:
        self.seen.append(("authorize", server))
        return f"https://{server}/oauth/authorize?state={state}&scope={'+'.join(scopes)}&c={code_challenge}"

    async def exchange_code(
        self, server: str, *, code: str, redirect_uri: str, code_verifier: str | None
    ) -> Token:
        self.seen.append(("exchange", server))
        return Token(TokenKind.USER, f"fedi-{code}", server=server)

    def can_refresh(self, token: Token) -> bool:
        return False

    async def refresh(self, token: Token) -> Token:
        raise ProviderError(FEDI, "no se renueva")

    async def revoke(self, token: Token) -> None:
        self.revoked.append(f"{token.access_token}@{token.server}")


@dataclass
class FakeCredentials:
    clock: FakeClock
    fail_with: Exception | None = None
    logins: list[Mapping[str, str]] = field(default_factory=list)
    refreshed: int = 0
    revoked: list[str] = field(default_factory=list)

    @property
    def fields(self) -> Sequence[CredentialField]:
        return (
            CredentialField("identifier"),
            CredentialField("password", secret=True),
            CredentialField("server", required=False),
        )

    async def login(self, credentials: Mapping[str, str]) -> Token:
        if self.fail_with is not None:
            raise self.fail_with
        self.logins.append(credentials)
        return Token(
            TokenKind.USER,
            "cielo-1",
            refresh_token="renovar-1",
            expires_at=self.clock.now() + timedelta(hours=2),
            server=credentials.get("server") or "cielo.social",
        )

    def can_refresh(self, token: Token) -> bool:
        return token.refresh_token is not None

    async def refresh(self, token: Token) -> Token:
        self.refreshed += 1
        return Token(
            TokenKind.USER,
            f"cielo-{self.refreshed + 1}",
            refresh_token=f"renovar-{self.refreshed + 1}",
            expires_at=self.clock.now() + timedelta(hours=2),
            server=token.server,
        )

    async def revoke(self, token: Token) -> None:
        self.revoked.append(token.access_token)


@dataclass
class World:
    social: Omnisocial
    clock: FakeClock
    fedi: FakeServerOAuth
    cielo: FakeCredentials
    connections: InMemoryConnectionRepository


@pytest.fixture
def world() -> World:
    clock = FakeClock()
    fedi = FakeServerOAuth()
    cielo = FakeCredentials(clock)
    connections = InMemoryConnectionRepository()
    social = Omnisocial.build(
        providers=[
            Provider(id=FEDI, server_oauth=fedi, identity=Quien()),
            Provider(id=CIELO, credentials=cielo, identity=Quien()),
        ],
        connections=connections,
        assets=InMemoryAssetRepository(),
        states=InMemoryAuthorizationStateStore(clock),
        webhook_events=AsyncMemoryIdempotencyStore(),
        redirect_uri_for=lambda provider: f"https://api.ejemplo.com/oauth/{provider}/callback",
        return_urls=ReturnUrlPolicy.of("https://app.ejemplo.com"),
        clock=clock,
        ids=SequentialIds(),
        secrets=FakeSecrets(),
    )
    return World(social, clock, fedi, cielo, connections)


# ── OAuth por servidor ──────────────────────────────────────────────────────────────────────────


async def test_la_persona_elige_el_servidor_y_el_token_lo_recuerda(world: World) -> None:
    assert world.social.registry.get("fedi").capabilities == frozenset({Capability.LOGIN})
    started = await world.social.start_authorization.execute(
        "fedi", purpose=Purpose.CONNECT, owner="c", server="https://Mastodon.Social/"
    )
    assert isinstance(started, AuthorizationStarted)
    assert started.url.startswith("https://mastodon.social/oauth/authorize?")
    assert "scope=read+write" in started.url
    connected = await world.social.complete_authorization.execute(state=started.state, code="abc")
    assert isinstance(connected, Connected)
    assert connected.connection.token.server == "mastodon.social"
    assert connected.connection.subject.external_id == "u1@mastodon.social"
    assert world.fedi.seen == [("authorize", "mastodon.social"), ("exchange", "mastodon.social")]

    # La misma persona en otro servidor es otra conexión.
    other = await world.social.start_authorization.execute(
        "fedi", purpose=Purpose.CONNECT, owner="c", server="hachyderm.io"
    )
    assert isinstance(other, AuthorizationStarted)
    second = await world.social.complete_authorization.execute(state=other.state, code="xyz")
    assert isinstance(second, Connected)
    assert second.connection.id != connected.connection.id

    await world.social.disconnect.execute(connected.connection.id)
    assert world.fedi.revoked == ["fedi-abc@mastodon.social"]


async def test_login_en_una_red_federada(world: World) -> None:
    started = await world.social.start_authorization.execute(
        "fedi", purpose=Purpose.LOGIN, server="mastodon.social"
    )
    assert isinstance(started, AuthorizationStarted)
    logged = await world.social.complete_authorization.execute(state=started.state, code="abc")
    assert isinstance(logged, LoggedIn)
    assert logged.identity.external_id == "u1@mastodon.social"


@pytest.mark.parametrize(
    ("server", "reason"),
    [
        (None, Refusal.SERVER_REQUIRED),
        ("", Refusal.SERVER_REQUIRED),
        ("localhost", Refusal.INVALID_SERVER),
        ("169.254.169.254", Refusal.INVALID_SERVER),
        ("http://mastodon.social", Refusal.INVALID_SERVER),
    ],
)
async def test_sin_un_servidor_publico_no_se_empieza(
    world: World, server: str | None, reason: Refusal
) -> None:
    refused = await world.social.start_authorization.execute(
        "fedi", purpose=Purpose.CONNECT, owner="c", server=server
    )
    assert isinstance(refused, Refused)
    assert refused.reason is reason
    # No se le hizo ningún pedido al servidor.
    assert world.fedi.seen == []


# ── Conexión por credencial ─────────────────────────────────────────────────────────────────────


async def test_conectar_con_una_credencial_guarda_el_token_y_no_la_credencial(world: World) -> None:
    assert world.social.registry.get("cielo").capabilities == frozenset({Capability.CREDENTIALS})
    credentials = {"identifier": "ana.cielo.social", "password": "abcd-efgh-ijkl-mnop"}
    connected = await world.social.connect_with_credentials.execute(
        "cielo", owner="c", credentials=credentials
    )
    assert isinstance(connected, Connected)
    token = connected.connection.token
    assert (token.access_token, token.refresh_token, token.server) == ("cielo-1", "renovar-1", "cielo.social")
    assert "abcd-efgh" not in repr(connected)
    # Volver a conectar la misma cuenta es reconectar.
    again = await world.social.connect_with_credentials.execute("cielo", owner="c", credentials=credentials)
    assert isinstance(again, Connected)
    assert (again.reconnected, again.connection.id) == (True, connected.connection.id)


async def test_el_token_de_una_credencial_se_renueva_y_se_revoca(world: World) -> None:
    credentials = {"identifier": "ana", "password": "x", "server": "otro.social"}
    connected = await world.social.connect_with_credentials.execute(
        "cielo", owner="c", credentials=credentials
    )
    assert isinstance(connected, Connected)
    world.clock.advance(timedelta(hours=1, minutes=58))
    valid = await world.social.get_valid_token.execute(connected.connection.id)
    assert isinstance(valid, ValidToken)
    # El servidor se conserva al renovar.
    assert (valid.token.access_token, valid.token.server) == ("cielo-2", "otro.social")
    report = await world.social.refresh_expiring.execute(within=timedelta(hours=3))
    assert report.refreshed == (connected.connection.id,)
    await world.social.disconnect.execute(connected.connection.id)
    assert world.cielo.revoked == ["cielo-3"]
    stored = await world.connections.get(connected.connection.id)
    assert stored is not None
    assert stored.status is ConnectionStatus.REVOKED


@pytest.mark.parametrize(
    ("credentials", "owner", "reason", "detail"),
    [
        ({"identifier": "ana"}, "c", Refusal.CREDENTIALS_REQUIRED, "password"),
        ({}, "c", Refusal.CREDENTIALS_REQUIRED, "identifier, password"),
        ({"identifier": "ana", "password": "x"}, "", Refusal.OWNER_REQUIRED, None),
    ],
)
async def test_lo_que_falta_para_conectar_con_una_credencial(
    world: World, credentials: dict[str, str], owner: str, reason: Refusal, detail: str | None
) -> None:
    refused = await world.social.connect_with_credentials.execute(
        "cielo", owner=owner, credentials=credentials
    )
    assert refused == Refused(reason, detail=detail)
    assert world.cielo.logins == []


async def test_una_credencial_que_la_red_no_acepta(world: World) -> None:
    credentials = {"identifier": "ana", "password": "mala"}
    world.cielo.fail_with = TokenRejected(CIELO, "identificador o contraseña inválidos")
    denied = await world.social.connect_with_credentials.execute("cielo", owner="c", credentials=credentials)
    assert denied == Refused(Refusal.PROVIDER_DENIED, detail="identificador o contraseña inválidos")
    world.cielo.fail_with = RateLimited(CIELO, "demasiados intentos", retry_after=300.0)
    limited = await world.social.connect_with_credentials.execute("cielo", owner="c", credentials=credentials)
    assert isinstance(limited, Refused)
    assert (limited.reason, limited.retry_after) == (Refusal.RATE_LIMITED, 300.0)
    world.cielo.fail_with = ProviderError(CIELO, "se cayó", status=500)
    with pytest.raises(ProviderError):
        await world.social.connect_with_credentials.execute("cielo", owner="c", credentials=credentials)


async def test_cada_red_conecta_a_su_manera(world: World) -> None:
    with pytest.raises(CapabilityNotSupported):
        await world.social.connect_with_credentials.execute("fedi", owner="c", credentials={})
    with pytest.raises(CapabilityNotSupported):
        await world.social.start_authorization.execute("cielo", purpose=Purpose.CONNECT, owner="c")
