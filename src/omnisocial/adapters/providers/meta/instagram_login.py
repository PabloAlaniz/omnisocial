"""Instagram con login propio ("Instagram API with Instagram Login").

La persona autoriza con su cuenta profesional de Instagram, sin página de Facebook de por medio. Para la
librería es otra red (`instagram`): tiene su propia app (con su id y su secreto, distintos de los de la app
de Meta), sus tokens y su servidor. Lo que sí comparte con Meta es la forma de la API, así que publicar,
leer, comentar y medir usan los mismos adaptadores.

El token dura 60 días y se renueva él mismo, mientras esté vigente y tenga más de un día: un token que
venció no se recupera. Conviene correr la renovación anticipada (`social.refresh_expiring`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlencode

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport
from omnisocial.adapters.providers.meta.catalog import DEFAULT_CATALOG
from omnisocial.adapters.providers.meta.comments import MetaCommentGateway
from omnisocial.adapters.providers.meta.config import INSTAGRAM, INSTAGRAM_ACCOUNT, MetaConfig
from omnisocial.adapters.providers.meta.content import MetaContentReader
from omnisocial.adapters.providers.meta.graph import GraphClient, as_dict, as_int, as_list, as_str
from omnisocial.adapters.providers.meta.insights import MetaInsightsReader
from omnisocial.adapters.providers.meta.publishing import MetaPublisher
from omnisocial.adapters.providers.meta.spec import ERRORS, INSTAGRAM_LOGIN_CAPABILITIES, INSTAGRAM_SPEC
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import AssetDirectory, Clock, OAuthClient
from omnisocial.application.registry import Provider
from omnisocial.domain.asset import DiscoveredAsset
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.metrics import MetricCatalog
from omnisocial.domain.token import Token, TokenKind

LOGIN_SCOPES: tuple[str, ...] = ("instagram_business_basic",)

CONNECT_SCOPES: tuple[str, ...] = (
    "instagram_business_basic",
    "instagram_business_manage_comments",
    "instagram_business_manage_insights",
)
"""Leer la cuenta y sus publicaciones, los comentarios y las métricas."""

PUBLISH_SCOPES: tuple[str, ...] = ("instagram_business_content_publish",)

PROFILE_FIELDS = "user_id,username,name,profile_picture_url"
LIFETIME = timedelta(days=60)
MIN_AGE = timedelta(hours=24)
_CLIENT_ERROR = 400


@dataclass(frozen=True, slots=True, kw_only=True)
class InstagramConfig:
    """La app de Instagram: su id y su secreto están en el panel de la app, en la configuración del login
    de Instagram, y no son los de la app de Meta."""

    client_id: str
    client_secret: str = field(repr=False)
    api_version: str
    """Por ejemplo `v24.0`. Se fija a propósito, igual que en Meta."""
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    authorize_url: str = "https://www.instagram.com/oauth/authorize"
    token_url: str = "https://api.instagram.com/oauth/access_token"  # noqa: S105  # es una URL
    graph_url: str = "https://graph.instagram.com"
    page_size: int = 50

    def graph_config(self) -> MetaConfig:
        """La misma API, en otro servidor y sin app de Meta: las llamadas no se firman."""
        return MetaConfig(api_version=self.api_version, graph_url=self.graph_url, page_size=self.page_size)


def _unwrapped(response: HttpResponse) -> dict[str, object]:
    """El cuerpo de una respuesta de tokens o de perfil. Puede venir suelto o dentro de `data`."""
    body = as_dict(response.data)
    if response.status >= _CLIENT_ERROR or "error" in body or "error_type" in body:
        error = as_dict(body.get("error"))
        message = (
            as_str(error.get("message"))
            or as_str(body.get("error_message"))
            or response.text[:300]
            or "error"
        )
        code = as_int(error.get("code"))
        raise ERRORS.error(
            INSTAGRAM, message, status=response.status, code=str(code) if code is not None else None
        )
    wrapped = as_list(body.get("data"))
    return wrapped[0] if wrapped else body


def _scopes(value: object) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset(s for s in value.split(",") if s)
    return frozenset(s for s in value if isinstance(s, str)) if isinstance(value, list) else frozenset()


class InstagramLogin(OAuthClient):
    supports_pkce = False

    def __init__(self, config: InstagramConfig, transport: HttpTransport, clock: Clock) -> None:
        self._config = config
        self._transport = transport
        self._clock = clock

    @override
    def default_scopes(self, purpose: Purpose) -> tuple[str, ...]:
        return self._config.login_scopes if purpose is Purpose.LOGIN else self._config.connect_scopes

    @override
    def authorization_url(
        self, *, state: str, redirect_uri: str, scopes: Sequence[str], code_challenge: str | None
    ) -> str:
        query = urlencode(
            {
                "client_id": self._config.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": ",".join(scopes),
                "state": state,
            }
        )
        return f"{self._config.authorize_url}?{query}"

    async def _graph(self, path: str, **params: str) -> dict[str, object]:
        url = f"{self._config.graph_url.rstrip('/')}/{path}"
        return _unwrapped(await self._transport.request("GET", url, params=params))

    def _long_lived(self, body: dict[str, object], scopes: frozenset[str]) -> Token:
        access = as_str(body.get("access_token"))
        if not access:
            raise ProviderError(INSTAGRAM, "Instagram no devolvió un token.")
        expires_in = as_int(body.get("expires_in")) or int(LIFETIME.total_seconds())
        return Token(
            TokenKind.USER,
            access,
            expires_at=self._clock.now() + timedelta(seconds=expires_in),
            scopes=scopes,
        )

    @override
    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str | None) -> Token:
        form = {
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            # Instagram le agrega `#_` al código en la URL de retorno: no es parte del código.
            "code": code.removesuffix("#_"),
        }
        response = await self._transport.request(
            "POST", self._config.token_url, form=form, retry_safe="no publica nada en la cuenta"
        )
        short = _unwrapped(response)
        short_token = as_str(short.get("access_token"))
        if not short_token:
            raise ProviderError(INSTAGRAM, "Instagram no devolvió un token.")
        long = await self._graph(
            "access_token",
            grant_type="ig_exchange_token",
            client_secret=self._config.client_secret,
            access_token=short_token,
        )
        return self._long_lived(long, _scopes(short.get("permissions")))

    @override
    async def identity(self, token: Token) -> Identity:
        profile = await own_profile(self._config, self._transport, token)
        return Identity(
            provider=INSTAGRAM,
            external_id=str(profile["user_id"]),
            name=as_str(profile.get("name")) or as_str(profile.get("username")),
            avatar_url=as_str(profile.get("profile_picture_url")),
        )

    @override
    def can_refresh(self, token: Token) -> bool:
        """Mientras esté vigente y tenga más de un día. La edad sale del vencimiento: dura 60 días."""
        if token.expires_at is None:
            return False
        now = self._clock.now()
        return now < token.expires_at and now - (token.expires_at - LIFETIME) >= MIN_AGE

    @override
    async def refresh(self, token: Token) -> Token:
        body = await self._graph(
            "refresh_access_token", grant_type="ig_refresh_token", access_token=token.access_token
        )
        return self._long_lived(body, token.scopes)

    @override
    async def revoke(self, token: Token) -> None:
        """No hay cómo revocar un token por API: la persona quita el acceso desde su cuenta."""


async def own_profile(config: InstagramConfig, transport: HttpTransport, token: Token) -> dict[str, object]:
    """La cuenta profesional que autorizó. `user_id` es su id: el que va en las rutas y llega en los
    avisos. El otro (`id`) es propio de la app y no sirve para eso."""
    url = f"{config.graph_url.rstrip('/')}/{config.api_version}/me"
    response = await transport.request(
        "GET", url, params={"fields": PROFILE_FIELDS, "access_token": token.access_token}
    )
    profile = _unwrapped(response)
    if not as_str(profile.get("user_id")):
        raise ProviderError(INSTAGRAM, "Instagram no devolvió el id de la cuenta.")
    return profile


class InstagramLoginAssets(AssetDirectory):
    def __init__(self, config: InstagramConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = transport

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        profile = await own_profile(self._config, self._transport, token)
        username = as_str(profile.get("username"))
        # Sin token propio: se usa el de la conexión, que es el de la cuenta.
        return [
            DiscoveredAsset(
                INSTAGRAM_ACCOUNT,
                str(profile["user_id"]),
                name=as_str(profile.get("name")) or username,
                capabilities=INSTAGRAM_LOGIN_CAPABILITIES,
                metadata={"username": username} if username else {},
            )
        ]


def instagram_provider(
    config: InstagramConfig,
    transport: HttpTransport,
    *,
    clock: Clock | None = None,
    catalog: MetricCatalog = DEFAULT_CATALOG,
) -> Provider:
    """Login, la cuenta como activo, publicaciones, comentarios, métricas y publicar."""
    clock = clock or SystemClock()
    graph = GraphClient(config.graph_config(), transport, provider=INSTAGRAM)
    return Provider(
        id=INSTAGRAM,
        oauth=InstagramLogin(config, transport, clock),
        assets=InstagramLoginAssets(config, transport),
        content=MetaContentReader(graph),
        comments=MetaCommentGateway(graph),
        insights=MetaInsightsReader(graph, clock, catalog),
        publisher=MetaPublisher(graph),
        spec=INSTAGRAM_SPEC,
    )
