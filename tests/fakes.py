"""Una red falsa con todas las capacidades, y reloj, ids y secretos controlables."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from omniwebhook import IncomingRequest, Verifier, hmac_body_scheme

from omnisocial.application.registry import Provider
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.content import Comment, CommentAction, Post
from omnisocial.domain.errors import TokenRejected
from omnisocial.domain.handles import Handle, Network
from omnisocial.domain.identity import Identity
from omnisocial.domain.lookup import Choice, LookupSpec
from omnisocial.domain.messaging import Conversation, Message, ReplyWindow
from omnisocial.domain.metrics import (
    CanonicalMetric,
    CatalogEntry,
    MetricCatalog,
    MetricPoint,
    MetricSeries,
    Period,
)
from omnisocial.domain.profile import PublicProfile
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.publishing import Draft, Outcome, PublicationStatus, PublishLimits, PublishOptions
from omnisocial.domain.spec import NetworkSpec
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent
from omnisocial.domain.window import TimeWindow

FAKE = ProviderId("falsa")
NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


class SequentialIds:
    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"{self._prefix}{self._n}"


class FakeSecrets:
    def __init__(self) -> None:
        self._n = 0

    def token(self, nbytes: int) -> str:
        self._n += 1
        return f"secreto{self._n}-{nbytes}"


@dataclass
class FakeOAuth:
    supports_pkce: bool = True
    refreshable: bool = True
    reject_refresh: bool = False
    reject_revoke: bool = False
    token_ttl: timedelta | None = timedelta(hours=1)
    subject: Identity = field(default_factory=lambda: Identity(FAKE, "persona-1", name="Persona"))
    clock: FakeClock = field(default_factory=FakeClock)
    exchanged: list[tuple[str, str, str | None]] = field(default_factory=list)
    refreshed: int = 0
    revoked: list[str] = field(default_factory=list)

    def default_scopes(self, purpose: Purpose) -> tuple[str, ...]:
        return ("perfil",) if purpose is Purpose.LOGIN else ("perfil", "paginas")

    def authorization_url(
        self, *, state: str, redirect_uri: str, scopes: Sequence[str], code_challenge: str | None
    ) -> str:
        return f"https://falsa/auth?state={state}&scopes={','.join(scopes)}&challenge={code_challenge}"

    def _token(self, value: str) -> Token:
        expires = self.clock.now() + self.token_ttl if self.token_ttl else None
        return Token(TokenKind.USER, value, refresh_token="r-" + value, expires_at=expires)

    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str | None) -> Token:
        self.exchanged.append((code, redirect_uri, code_verifier))
        return self._token("tok-" + code)

    async def identity(self, token: Token) -> Identity:
        return self.subject

    def can_refresh(self, token: Token) -> bool:
        return self.refreshable and token.refresh_token is not None

    async def refresh(self, token: Token) -> Token:
        self.refreshed += 1
        if self.reject_refresh:
            raise TokenRejected(FAKE, "revocado por la persona", code="190")
        return self._token(f"renovado{self.refreshed}")

    async def revoke(self, token: Token) -> None:
        if self.reject_revoke:
            raise TokenRejected(FAKE, "ya no servía")
        self.revoked.append(token.access_token)


@dataclass
class FakeAssets:
    items: list[DiscoveredAsset] = field(
        default_factory=lambda: [
            DiscoveredAsset(
                "pagina",
                "pag-1",
                name="Página",
                token=Token(TokenKind.ASSET, "tok-pagina"),
                capabilities=frozenset(Capability),
            ),
            DiscoveredAsset("cuenta", "cta-1", parent_external_id="pag-1"),
        ]
    )

    fail_with: Exception | None = None

    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        if self.fail_with is not None:
            raise self.fail_with
        return list(self.items)


@dataclass
class FakeContent:
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        self.calls.append((asset.external_id, token.access_token))
        return [Post("post-1", asset.external_id, NOW, text="hola")]


@dataclass
class FakeComments:
    replies: list[tuple[str, str]] = field(default_factory=list)
    hidden: dict[str, bool] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    liked: list[str] = field(default_factory=list)
    not_offered: set[CommentAction] = field(default_factory=set)
    fail_with: Exception | None = None
    """Si está, `list_comments` la lanza: así se prueba qué hace el caso de uso con los errores de la red."""

    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]:
        if self.fail_with is not None:
            raise self.fail_with
        return [Comment("com-1", object_id, NOW, text="buenísimo")]

    def supports(self, asset: Asset, action: CommentAction) -> bool:
        return action not in self.not_offered

    async def delete(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        self.deleted.append(comment_id)

    async def like(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        self.liked.append(comment_id)

    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        self.replies.append((comment_id, text))
        return "com-nuevo"

    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None:
        self.hidden[comment_id] = hidden


@dataclass
class FakeMessaging:
    messages: list[Message] = field(default_factory=list)
    sent: list[tuple[str, str]] = field(default_factory=list)
    reply_window: ReplyWindow = field(default_factory=lambda: ReplyWindow(timedelta(hours=24)))

    async def list_conversations(
        self, asset: Asset, token: Token, *, limit: int | None
    ) -> Sequence[Conversation]:
        return [Conversation("conv-1", asset.external_id, NOW)]

    async def list_messages(
        self, asset: Asset, token: Token, *, conversation_id: str, limit: int | None
    ) -> Sequence[Message]:
        return list(self.messages)

    async def send(self, asset: Asset, token: Token, *, recipient_id: str, text: str) -> str:
        self.sent.append((recipient_id, text))
        return "msg-nuevo"


@dataclass
class FakeInsights:
    api_version: str = "v2.0"
    catalog: MetricCatalog = field(
        default_factory=lambda: MetricCatalog(
            (
                CatalogEntry("pagina", CanonicalMetric.REACH, "alcance_unico"),
                CatalogEntry("pagina", CanonicalMetric.FOLLOWERS, "seguidores"),
            )
        )
    )
    requested: list[tuple[str, ...]] = field(default_factory=list)

    async def read(
        self, asset: Asset, token: Token, *, metrics: Sequence[str], period: Period, window: TimeWindow
    ) -> Sequence[MetricSeries]:
        self.requested.append(tuple(metrics))
        return [MetricSeries(name, period, (MetricPoint(NOW, 10.0),)) for name in metrics]


WEBHOOK_SECRET = "secreto-webhooks"


def sign(body: bytes, secret: str = WEBHOOK_SECRET) -> dict[str, str]:
    """Las cabeceras con que la red falsa firma un aviso."""
    return {"x-firma": hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}


@dataclass
class FakeWebhooks:
    secrets: list[str] = field(default_factory=lambda: [WEBHOOK_SECRET])

    @property
    def verifier(self) -> Verifier:
        return hmac_body_scheme(secrets=self.secrets, header="x-firma", name="falsa")

    def handshake(self, query: Mapping[str, str]) -> str | None:
        return query.get("desafio") if query.get("clave") == "ok" else None

    def parse(self, body: bytes) -> Sequence[SocialEvent]:
        return [SocialEvent(FAKE, EventKind.COMMENT, EventAction.CREATED, body.decode(), "com-9", NOW)]


@dataclass
class FakeProfiles:
    """Instagram necesita una cuenta propia de mirador; X no."""

    known: dict[str, PublicProfile] = field(
        default_factory=lambda: {
            "marca": PublicProfile(Network.INSTAGRAM, "17841400", username="marca", followers=1200),
            "otra": PublicProfile(Network.X, "44196397", username="otra", followers=10),
        }
    )
    calls: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    fail_with: Exception | None = None

    @property
    def networks(self) -> frozenset[Network]:
        return frozenset({Network.INSTAGRAM, Network.X})

    def viewer_kinds(self, network: Network) -> frozenset[str]:
        return frozenset({"cuenta"}) if network is Network.INSTAGRAM else frozenset()

    async def lookup(
        self, handle: Handle, *, viewer: Asset | None, token: Token | None
    ) -> PublicProfile | None:
        self.calls.append(
            (handle.value, viewer.external_id if viewer else None, token.access_token if token else None)
        )
        if self.fail_with is not None:
            raise self.fail_with
        return self.known.get(handle.value)


@dataclass(frozen=True)
class FakeOptions(PublishOptions):
    audience: str = "todos"


FAKE_LIMITS = PublishLimits(
    max_text=50, max_images=2, max_videos=1, link=True, first_comment=True, delete=True, options=FakeOptions
)
FAKE_SPEC = NetworkSpec(
    id=FAKE,
    name="Falsa",
    capabilities=frozenset(Capability),
    assets={"pagina": frozenset(Capability)},
    publishing={"pagina": FAKE_LIMITS},
    lookups={
        "pagina": (
            LookupSpec("tableros", "Los tableros de la cuenta.", searchable=True),
            LookupSpec("secciones", "Las secciones de un tablero.", parent="tableros"),
        )
    },
)


@dataclass
class FakePublisher:
    """Publica en dos etapas si `pending` está puesto: primero queda pendiente y al retomar sale."""

    published: list[Draft] = field(default_factory=list)
    resumed: list[Mapping[str, str]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    pending: bool = False
    fail_with: Exception | None = None
    outcome: Outcome | None = None

    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        if self.fail_with is not None:
            raise self.fail_with
        self.published.append(draft)
        if self.outcome is not None:
            return self.outcome
        if self.pending:
            return Outcome(PublicationStatus.PENDING, resume={"paso": "1"})
        number = len(self.published)
        return Outcome(PublicationStatus.PUBLISHED, post_id=f"post-{number}", url=f"https://red/{number}")

    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        if self.fail_with is not None:
            raise self.fail_with
        self.resumed.append(resume)
        return self.outcome or Outcome(PublicationStatus.PUBLISHED, post_id="post-1")

    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.deleted.append(post_id)


@dataclass
class FakeLookups:
    found: Sequence[Choice] = (Choice("t1", "Recetas"),)
    calls: list[tuple[str, str | None, str | None]] = field(default_factory=list)

    async def choices(
        self, asset: Asset, token: Token, *, lookup: str, query: str | None, parent: str | None
    ) -> Sequence[Choice]:
        self.calls.append((lookup, query, parent))
        return self.found


@dataclass
class FakeNetwork:
    clock: FakeClock = field(default_factory=FakeClock)
    oauth: FakeOAuth = field(default_factory=FakeOAuth)
    assets: FakeAssets = field(default_factory=FakeAssets)
    content: FakeContent = field(default_factory=FakeContent)
    comments: FakeComments = field(default_factory=FakeComments)
    messaging: FakeMessaging = field(default_factory=FakeMessaging)
    insights: FakeInsights = field(default_factory=FakeInsights)
    webhooks: FakeWebhooks = field(default_factory=FakeWebhooks)
    profiles: FakeProfiles = field(default_factory=FakeProfiles)
    publisher: FakePublisher = field(default_factory=FakePublisher)
    lookups: FakeLookups | None = None

    def __post_init__(self) -> None:
        self.oauth.clock = self.clock

    def provider(
        self, *, only: frozenset[Capability] | None = None, identity: object | None = None
    ) -> Provider:
        def pick(capability: Capability, component: object) -> object:
            return component if only is None or capability in only else None

        return Provider(
            id=FAKE,
            oauth=pick(Capability.LOGIN, self.oauth),  # type: ignore[arg-type]
            assets=pick(Capability.ASSETS, self.assets),  # type: ignore[arg-type]
            content=pick(Capability.CONTENT, self.content),  # type: ignore[arg-type]
            comments=pick(Capability.COMMENTS, self.comments),  # type: ignore[arg-type]
            messaging=pick(Capability.MESSAGING, self.messaging),  # type: ignore[arg-type]
            insights=pick(Capability.INSIGHTS, self.insights),  # type: ignore[arg-type]
            webhooks=pick(Capability.WEBHOOKS, self.webhooks),  # type: ignore[arg-type]
            profiles=pick(Capability.PUBLIC_PROFILES, self.profiles),  # type: ignore[arg-type]
            publisher=pick(Capability.PUBLISHING, self.publisher),  # type: ignore[arg-type]
            identity=identity,  # type: ignore[arg-type]
            lookups=self.lookups,
            spec=FAKE_SPEC,
        )


def incoming(body: bytes, headers: Mapping[str, str]) -> IncomingRequest:
    return IncomingRequest(headers=list(headers.items()), query=[], body=body)
