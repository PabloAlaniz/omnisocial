"""Redes sociales con las mismas reglas: un núcleo común y un adaptador por red.

```python
from omnisocial import Omnisocial, Purpose, ReturnUrlPolicy
from omnisocial.meta import MetaConfig, meta_provider
```
"""

from omnisocial.adapters.files import PathFile
from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
    InMemoryPublicationRepository,
    InMemoryQuotaLedger,
    InMemoryRateLimitStore,
    InMemoryServerAppStore,
)
from omnisocial.adapters.system import SystemClock
from omnisocial.application.observing import Observation, Observer
from omnisocial.application.quota import QuotaBudget
from omnisocial.application.registry import Provider, ProviderRegistry
from omnisocial.application.results import (
    AssetAccess,
    AuthorizationStarted,
    Connected,
    Done,
    InsightsRead,
    LoggedIn,
    Refusal,
    Refused,
    ValidToken,
)
from omnisocial.application.use_cases.inbox import Inbox
from omnisocial.application.use_cases.refreshing import RefreshReport
from omnisocial.application.use_cases.webhooks import OnEvents, RoutedEvent, WebhookReceived
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.authorization import CredentialField, Purpose, ServerApp
from omnisocial.domain.connection import Connection, ConnectionChange, ConnectionStatus
from omnisocial.domain.content import Comment, CommentAction, Post
from omnisocial.domain.errors import (
    CapabilityNotSupported,
    ErrorKind,
    NotPublished,
    OmnisocialError,
    PermissionMissing,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    TokenRejected,
    UnknownProvider,
)
from omnisocial.domain.handles import Handle, HandleKind, Network, parse_handle
from omnisocial.domain.identity import Identity
from omnisocial.domain.inbox import InboxItem, InboxKind
from omnisocial.domain.inbox import from_event as inbox_item_from_event
from omnisocial.domain.lookup import Choice, LookupSpec
from omnisocial.domain.messaging import (
    Attachment,
    AttachmentKind,
    Conversation,
    DeliveryStatus,
    Message,
    MessagingLimits,
    OutboundMessage,
    Recipient,
    ReplyWindow,
    TemplateRef,
)
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
from omnisocial.domain.publishing import (
    BytesFile,
    Draft,
    DraftIssue,
    DraftProblem,
    Media,
    MediaFile,
    MediaKind,
    Publication,
    PublicationStatus,
    PublishLimits,
    PublishOptions,
)
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.domain.server import normalize_server
from omnisocial.domain.spec import NetworkSpec, Pace
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent
from omnisocial.domain.window import TimeWindow
from omnisocial.entrypoints.hub import Omnisocial

__all__ = [
    "Asset",
    "AssetAccess",
    "Attachment",
    "AttachmentKind",
    "AuthorizationStarted",
    "BytesFile",
    "CanonicalMetric",
    "Capability",
    "CapabilityNotSupported",
    "CatalogEntry",
    "Choice",
    "Comment",
    "CommentAction",
    "Connected",
    "Connection",
    "ConnectionChange",
    "ConnectionStatus",
    "Conversation",
    "CredentialField",
    "DeliveryStatus",
    "DiscoveredAsset",
    "Done",
    "Draft",
    "DraftIssue",
    "DraftProblem",
    "ErrorKind",
    "EventAction",
    "EventKind",
    "Handle",
    "HandleKind",
    "Identity",
    "InMemoryAssetRepository",
    "InMemoryAuthorizationStateStore",
    "InMemoryConnectionRepository",
    "InMemoryPublicationRepository",
    "InMemoryQuotaLedger",
    "InMemoryRateLimitStore",
    "InMemoryServerAppStore",
    "Inbox",
    "InboxItem",
    "InboxKind",
    "InsightsRead",
    "LoggedIn",
    "LookupSpec",
    "Media",
    "MediaFile",
    "MediaKind",
    "Message",
    "MessagingLimits",
    "MetricCatalog",
    "MetricPoint",
    "MetricSeries",
    "Network",
    "NetworkSpec",
    "NotPublished",
    "Observation",
    "Observer",
    "Omnisocial",
    "OmnisocialError",
    "OnEvents",
    "OutboundMessage",
    "Pace",
    "PathFile",
    "Period",
    "PermissionMissing",
    "Post",
    "Provider",
    "ProviderError",
    "ProviderId",
    "ProviderRegistry",
    "PublicProfile",
    "Publication",
    "PublicationStatus",
    "PublishLimits",
    "PublishOptions",
    "Purpose",
    "QuotaBudget",
    "QuotaExhausted",
    "RateLimited",
    "Recipient",
    "RefreshReport",
    "Refusal",
    "Refused",
    "ReplyWindow",
    "ReturnUrlPolicy",
    "RoutedEvent",
    "ServerApp",
    "SocialEvent",
    "SystemClock",
    "TemplateRef",
    "TimeWindow",
    "Token",
    "TokenKind",
    "TokenRejected",
    "UnknownProvider",
    "ValidToken",
    "WebhookReceived",
    "inbox_item_from_event",
    "normalize_server",
    "parse_handle",
]
