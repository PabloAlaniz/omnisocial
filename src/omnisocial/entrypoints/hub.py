"""La fachada: arma los casos de uso con las redes y la infraestructura elegidas."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from omniwebhook import AsyncIdempotencyStore

from omnisocial.adapters.system import SystemClock, SystemSecrets, UuidGenerator
from omnisocial.application.ports import (
    AssetRepository,
    AuthorizationStateStore,
    Clock,
    ConnectionRepository,
    IdGenerator,
    SecretGenerator,
)
from omnisocial.application.registry import Provider, ProviderRegistry
from omnisocial.application.use_cases.access import GetValidToken, ResolveAssetAccess
from omnisocial.application.use_cases.assets import ListAssets, SyncAssets
from omnisocial.application.use_cases.authorization import (
    CompleteAuthorization,
    ConnectionStore,
    Disconnect,
    RedirectUriFor,
    RegisterSystemConnection,
    StartAuthorization,
)
from omnisocial.application.use_cases.operations import (
    ListComments,
    ListConversations,
    ListMessages,
    ListPosts,
    ReadInsights,
    ReplyToComment,
    SendMessage,
    SetCommentHidden,
)
from omnisocial.application.use_cases.webhooks import HandleWebhook
from omnisocial.domain.redirect import ReturnUrlPolicy


@dataclass(frozen=True)
class Omnisocial:
    """Todos los casos de uso listos para usar.

    ```python
    social = Omnisocial.build(
        providers=[meta_provider(MetaConfig(...))],
        connections=..., assets=..., states=..., webhook_events=...,
        redirect_uri_for=lambda provider: f"https://api.ejemplo.com/oauth/{provider}/callback",
        return_urls=ReturnUrlPolicy.of("https://app.ejemplo.com"),
    )
    started = await social.start_authorization.execute("meta", purpose=Purpose.CONNECT, owner="cliente-1")
    ```
    """

    registry: ProviderRegistry
    start_authorization: StartAuthorization
    complete_authorization: CompleteAuthorization
    register_system_connection: RegisterSystemConnection
    disconnect: Disconnect
    get_valid_token: GetValidToken
    resolve_asset_access: ResolveAssetAccess
    sync_assets: SyncAssets
    list_assets: ListAssets
    list_posts: ListPosts
    list_comments: ListComments
    reply_to_comment: ReplyToComment
    set_comment_hidden: SetCommentHidden
    list_conversations: ListConversations
    list_messages: ListMessages
    send_message: SendMessage
    read_insights: ReadInsights
    handle_webhook: HandleWebhook

    @classmethod
    def build(
        cls,
        *,
        providers: Iterable[Provider],
        connections: ConnectionRepository,
        assets: AssetRepository,
        states: AuthorizationStateStore,
        webhook_events: AsyncIdempotencyStore,
        redirect_uri_for: RedirectUriFor,
        return_urls: ReturnUrlPolicy,
        clock: Clock | None = None,
        ids: IdGenerator | None = None,
        secrets: SecretGenerator | None = None,
    ) -> Omnisocial:
        registry = ProviderRegistry(providers)
        clock = clock or SystemClock()
        ids = ids or UuidGenerator()
        secrets = secrets or SystemSecrets()
        store = ConnectionStore(connections=connections, assets=assets, clock=clock, ids=ids)
        tokens = GetValidToken(registry=registry, connections=connections, clock=clock)
        access = ResolveAssetAccess(assets=assets, tokens=tokens, clock=clock)
        return cls(
            registry=registry,
            start_authorization=StartAuthorization(
                registry=registry,
                states=states,
                secrets=secrets,
                clock=clock,
                return_urls=return_urls,
                redirect_uri_for=redirect_uri_for,
            ),
            complete_authorization=CompleteAuthorization(
                registry=registry, states=states, clock=clock, store=store
            ),
            register_system_connection=RegisterSystemConnection(registry=registry, store=store),
            disconnect=Disconnect(registry=registry, connections=connections, assets=assets, clock=clock),
            get_valid_token=tokens,
            resolve_asset_access=access,
            sync_assets=SyncAssets(registry=registry, tokens=tokens, assets=assets, ids=ids),
            list_assets=ListAssets(assets=assets),
            list_posts=ListPosts(registry=registry, access=access),
            list_comments=ListComments(registry=registry, access=access),
            reply_to_comment=ReplyToComment(registry=registry, access=access),
            set_comment_hidden=SetCommentHidden(registry=registry, access=access),
            list_conversations=ListConversations(registry=registry, access=access),
            list_messages=ListMessages(registry=registry, access=access),
            send_message=SendMessage(registry=registry, access=access, clock=clock),
            read_insights=ReadInsights(registry=registry, access=access),
            handle_webhook=HandleWebhook(registry=registry, assets=assets, store=webhook_events),
        )
