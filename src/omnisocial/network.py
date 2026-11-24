"""Lo que hace falta para escribir una red, en un solo lugar.

Un adaptador (de este paquete o de uno aparte) importa de acá: los puertos que implementa, la descripción
que declara, el transporte por el que habla y los errores que lanza. No carga ningún paquete opcional.
"""

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.http.pacing import PacedTransport, paced
from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params, TransportError
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import (
    AssetDirectory,
    Clock,
    CommentGateway,
    ContentReader,
    CredentialLogin,
    IdentityReader,
    InsightsReader,
    LookupReader,
    MessagingGateway,
    OAuthClient,
    ProfileLookup,
    Publisher,
    ServerAppStore,
    ServerOAuth,
    WebhookParser,
)
from omnisocial.application.quota import QuotaBudget
from omnisocial.application.registry import ENTRY_POINT_GROUP, Provider, load_entry_point
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.authorization import CredentialField, Purpose, ServerApp
from omnisocial.domain.errors import (
    ErrorKind,
    NotPublished,
    PermissionMissing,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.identity import Identity
from omnisocial.domain.lookup import Choice, LookupSpec
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.publishing import (
    Draft,
    Media,
    MediaKind,
    Outcome,
    PublicationStatus,
    PublishLimits,
    PublishOptions,
    TextCount,
)
from omnisocial.domain.spec import ErrorTable, NetworkSpec, OAuthSpec, Pace
from omnisocial.domain.token import Token, TokenKind

__all__ = [
    "ENTRY_POINT_GROUP",
    "Asset",
    "AssetDirectory",
    "Capability",
    "Choice",
    "Clock",
    "CommentGateway",
    "ContentReader",
    "CredentialField",
    "CredentialLogin",
    "DiscoveredAsset",
    "Draft",
    "ErrorKind",
    "ErrorTable",
    "HttpResponse",
    "HttpTransport",
    "Identity",
    "IdentityReader",
    "InsightsReader",
    "LookupReader",
    "LookupSpec",
    "Media",
    "MediaKind",
    "MessagingGateway",
    "NetworkSpec",
    "NotPublished",
    "OAuthApp",
    "OAuthClient",
    "OAuthSpec",
    "Outcome",
    "Pace",
    "PacedTransport",
    "Params",
    "PermissionMissing",
    "ProfileLookup",
    "Provider",
    "ProviderError",
    "ProviderId",
    "PublicationStatus",
    "PublishLimits",
    "PublishOptions",
    "Publisher",
    "Purpose",
    "QuotaBudget",
    "QuotaExhausted",
    "RateLimited",
    "ServerApp",
    "ServerAppStore",
    "ServerOAuth",
    "StandardOAuth",
    "SystemClock",
    "TextCount",
    "Token",
    "TokenKind",
    "TokenRejected",
    "TransportError",
    "WebhookParser",
    "load_entry_point",
    "paced",
]
