"""La fachada: arma los casos de uso con las redes y la infraestructura elegidas."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from omniwebhook import AsyncIdempotencyStore

from omnisocial.adapters.stores.memory import InMemoryPublicationRepository
from omnisocial.adapters.system import SystemClock, SystemSecrets, UuidGenerator
from omnisocial.application.ports import (
    AssetRepository,
    AuthorizationStateStore,
    Clock,
    ConnectionObserver,
    ConnectionRepository,
    IdGenerator,
    PublicationRepository,
    SecretGenerator,
)
from omnisocial.application.registry import Provider, ProviderRegistry
from omnisocial.application.use_cases.access import ConnectionWatch, GetValidToken, ResolveAssetAccess
from omnisocial.application.use_cases.assets import ListAssets, SyncAssets
from omnisocial.application.use_cases.authorization import (
    AuthorizationSettings,
    CompleteAuthorization,
    ConnectionStore,
    ConnectWithCredentials,
    Disconnect,
    RedirectUriFor,
    RegisterSystemConnection,
    StartAuthorization,
)
from omnisocial.application.use_cases.operations import (
    DeleteComment,
    LikeComment,
    ListComments,
    ListConversations,
    ListMessages,
    ListPosts,
    ReadInsights,
    ReplyToComment,
    SendMessage,
    SetCommentHidden,
)
from omnisocial.application.use_cases.profiles import LookupProfile
from omnisocial.application.use_cases.publishing import CheckPublication, DeletePost, Publish, ValidateDraft
from omnisocial.application.use_cases.refreshing import RefreshExpiring
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
    connect_with_credentials: ConnectWithCredentials
    disconnect: Disconnect
    get_valid_token: GetValidToken
    resolve_asset_access: ResolveAssetAccess
    sync_assets: SyncAssets
    list_assets: ListAssets
    list_posts: ListPosts
    list_comments: ListComments
    reply_to_comment: ReplyToComment
    set_comment_hidden: SetCommentHidden
    delete_comment: DeleteComment
    like_comment: LikeComment
    lookup_profile: LookupProfile
    list_conversations: ListConversations
    list_messages: ListMessages
    send_message: SendMessage
    read_insights: ReadInsights
    handle_webhook: HandleWebhook
    validate_draft: ValidateDraft
    publish: Publish
    check_publication: CheckPublication
    delete_post: DeletePost
    refresh_expiring: RefreshExpiring

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
        publications: PublicationRepository | None = None,
        on_connection_change: ConnectionObserver | None = None,
    ) -> Omnisocial:
        """`publications` guarda las publicaciones en curso y las claves de idempotencia. Si falta, quedan en
        memoria: alcanza para probar, pero no sobreviven a un reinicio ni se comparten entre procesos.

        `on_connection_change` se llama cuando una conexión deja de servir (venció, la red rechazó el
        token, se desconectó) o vuelve a servir (alguien reconectó), con el cambio ya guardado."""
        registry = ProviderRegistry(providers)
        clock = clock or SystemClock()
        ids = ids or UuidGenerator()
        secrets = secrets or SystemSecrets()
        publications = publications or InMemoryPublicationRepository()
        watch = ConnectionWatch(on_connection_change)
        store = ConnectionStore(connections=connections, assets=assets, clock=clock, ids=ids, watch=watch)
        tokens = GetValidToken(registry=registry, connections=connections, clock=clock, watch=watch)
        access = ResolveAssetAccess(assets=assets, tokens=tokens, clock=clock)
        return cls(
            registry=registry,
            start_authorization=StartAuthorization(
                registry=registry,
                states=states,
                secrets=secrets,
                clock=clock,
                settings=AuthorizationSettings(return_urls=return_urls, redirect_uri_for=redirect_uri_for),
            ),
            complete_authorization=CompleteAuthorization(
                registry=registry, states=states, clock=clock, store=store
            ),
            register_system_connection=RegisterSystemConnection(registry=registry, store=store),
            connect_with_credentials=ConnectWithCredentials(registry=registry, store=store),
            disconnect=Disconnect(
                registry=registry, connections=connections, assets=assets, clock=clock, watch=watch
            ),
            get_valid_token=tokens,
            resolve_asset_access=access,
            sync_assets=SyncAssets(registry=registry, tokens=tokens, assets=assets, ids=ids),
            list_assets=ListAssets(assets=assets),
            list_posts=ListPosts(registry=registry, access=access),
            list_comments=ListComments(registry=registry, access=access),
            reply_to_comment=ReplyToComment(registry=registry, access=access),
            set_comment_hidden=SetCommentHidden(registry=registry, access=access),
            delete_comment=DeleteComment(registry=registry, access=access),
            like_comment=LikeComment(registry=registry, access=access),
            lookup_profile=LookupProfile(registry=registry, access=access),
            list_conversations=ListConversations(registry=registry, access=access),
            list_messages=ListMessages(registry=registry, access=access),
            send_message=SendMessage(registry=registry, access=access, clock=clock),
            read_insights=ReadInsights(registry=registry, access=access),
            handle_webhook=HandleWebhook(
                registry=registry, assets=assets, store=webhook_events, tokens=tokens
            ),
            validate_draft=ValidateDraft(registry=registry, access=access),
            publish=Publish(
                registry=registry, access=access, publications=publications, clock=clock, ids=ids
            ),
            check_publication=CheckPublication(
                registry=registry, access=access, publications=publications, clock=clock
            ),
            delete_post=DeletePost(registry=registry, access=access),
            refresh_expiring=RefreshExpiring(
                registry=registry, connections=connections, tokens=tokens, clock=clock
            ),
        )
