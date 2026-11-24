"""Redes sociales con las mismas reglas: un núcleo común y un adaptador por red.

```python
from omnisocial import Omnisocial, Purpose, ReturnUrlPolicy
from omnisocial.meta import MetaConfig, meta_provider
```
"""

from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
    InMemoryPublicationRepository,
)
from omnisocial.adapters.system import SystemClock
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
from omnisocial.application.use_cases.webhooks import OnEvents, RoutedEvent, WebhookReceived
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.connection import Connection, ConnectionStatus
from omnisocial.domain.content import Comment, CommentAction, Post
from omnisocial.domain.errors import (
    CapabilityNotSupported,
    ErrorKind,
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
from omnisocial.domain.publishing import (
    Draft,
    DraftIssue,
    DraftProblem,
    Media,
    MediaKind,
    Publication,
    PublicationStatus,
    PublishLimits,
    PublishOptions,
)
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.domain.spec import NetworkSpec
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent
from omnisocial.domain.window import TimeWindow
from omnisocial.entrypoints.hub import Omnisocial

__all__ = [
    "Asset",
    "AssetAccess",
    "AuthorizationStarted",
    "CanonicalMetric",
    "Capability",
    "CapabilityNotSupported",
    "CatalogEntry",
    "Comment",
    "CommentAction",
    "Connected",
    "Connection",
    "ConnectionStatus",
    "Conversation",
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
    "InsightsRead",
    "LoggedIn",
    "Media",
    "MediaKind",
    "Message",
    "MetricCatalog",
    "MetricPoint",
    "MetricSeries",
    "Network",
    "NetworkSpec",
    "Omnisocial",
    "OmnisocialError",
    "OnEvents",
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
    "QuotaExhausted",
    "RateLimited",
    "Refusal",
    "Refused",
    "ReplyWindow",
    "ReturnUrlPolicy",
    "RoutedEvent",
    "SocialEvent",
    "SystemClock",
    "TimeWindow",
    "Token",
    "TokenKind",
    "TokenRejected",
    "UnknownProvider",
    "ValidToken",
    "WebhookReceived",
    "parse_handle",
]
