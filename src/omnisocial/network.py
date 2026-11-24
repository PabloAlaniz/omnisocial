"""Lo que hace falta para escribir una red, en un solo lugar.

Un adaptador (de este paquete o de uno aparte) importa de acá: los puertos que implementa, la descripción
que declara, el transporte por el que habla y los errores que lanza. No carga ningún paquete opcional.
"""

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.http.transport import HttpResponse, HttpTransport, Params, TransportError
from omnisocial.application.ports import (
    AssetDirectory,
    Clock,
    CommentGateway,
    ContentReader,
    IdentityReader,
    InsightsReader,
    MessagingGateway,
    OAuthClient,
    ProfileLookup,
    WebhookParser,
)
from omnisocial.application.registry import ENTRY_POINT_GROUP, Provider, load_entry_point
from omnisocial.domain.errors import (
    ErrorKind,
    PermissionMissing,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.spec import ErrorTable, NetworkSpec, OAuthSpec

__all__ = [
    "ENTRY_POINT_GROUP",
    "AssetDirectory",
    "Capability",
    "Clock",
    "CommentGateway",
    "ContentReader",
    "ErrorKind",
    "ErrorTable",
    "HttpResponse",
    "HttpTransport",
    "IdentityReader",
    "InsightsReader",
    "MessagingGateway",
    "NetworkSpec",
    "OAuthApp",
    "OAuthClient",
    "OAuthSpec",
    "Params",
    "PermissionMissing",
    "ProfileLookup",
    "Provider",
    "ProviderError",
    "ProviderId",
    "QuotaExhausted",
    "RateLimited",
    "StandardOAuth",
    "TokenRejected",
    "TransportError",
    "WebhookParser",
    "load_entry_point",
]
