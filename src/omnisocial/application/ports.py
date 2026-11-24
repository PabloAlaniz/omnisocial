"""Puertos.

Hay dos familias:

- **Capacidades de una red.** Cada adaptador implementa solo las que la red soporta. Un proveedor sin
  mensajes privados simplemente no trae `MessagingGateway`.
- **Infraestructura común.** Repositorios, estado de la autorización, reloj e identificadores. Son los
  mismos para todas las redes: una conexión de Meta y una de TikTok se guardan igual.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from omniwebhook import Verifier

from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.authorization import AuthorizationRequest, CredentialField, Purpose, ServerApp
from omnisocial.domain.connection import Connection, ConnectionChange
from omnisocial.domain.content import Comment, CommentAction, Post
from omnisocial.domain.handles import Handle, Network
from omnisocial.domain.identity import Identity
from omnisocial.domain.messaging import Conversation, Message, ReplyWindow
from omnisocial.domain.metrics import MetricCatalog, MetricSeries, Period
from omnisocial.domain.profile import PublicProfile
from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import Draft, Outcome, Publication
from omnisocial.domain.token import Token
from omnisocial.domain.webhooks import SocialEvent
from omnisocial.domain.window import TimeWindow

# ── Capacidades de una red ──────────────────────────────────────────────────────────────────────


class IdentityReader(Protocol):
    """Quién es el dueño de un token. Lo usa el OAuth y también un token cargado a mano."""

    async def identity(self, token: Token) -> Identity: ...


class OAuthClient(Protocol):
    @property
    def supports_pkce(self) -> bool: ...

    def default_scopes(self, purpose: Purpose) -> tuple[str, ...]: ...

    def authorization_url(
        self, *, state: str, redirect_uri: str, scopes: Sequence[str], code_challenge: str | None
    ) -> str: ...

    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str | None) -> Token:
        """Cambia el código por el mejor token que la red permita (el de mayor duración)."""
        ...

    async def identity(self, token: Token) -> Identity: ...

    def can_refresh(self, token: Token) -> bool: ...

    async def refresh(self, token: Token) -> Token:
        """Renueva el token. Lanza `TokenRejected` si la red ya no lo acepta."""
        ...

    async def revoke(self, token: Token) -> None: ...


class ServerOAuth(Protocol):
    """OAuth en una red federada: la persona elige el servidor, y cada servidor es una app distinta.

    Reemplaza a `OAuthClient` en esas redes. La identidad la lee un `IdentityReader` aparte, con el
    servidor que el token lleva anotado.
    """

    @property
    def supports_pkce(self) -> bool: ...

    def default_scopes(self, purpose: Purpose) -> tuple[str, ...]: ...

    async def authorization_url(
        self, server: str, *, state: str, redirect_uri: str, scopes: Sequence[str], code_challenge: str | None
    ) -> str:
        """Puede llamar al servidor: en algunas redes la app se registra ahí la primera vez."""
        ...

    async def exchange_code(
        self, server: str, *, code: str, redirect_uri: str, code_verifier: str | None
    ) -> Token:
        """El token vuelve con `server` anotado."""
        ...

    def can_refresh(self, token: Token) -> bool: ...

    async def refresh(self, token: Token) -> Token: ...

    async def revoke(self, token: Token) -> None: ...


class CredentialLogin(Protocol):
    """Conectar con una credencial que la persona genera en la red, sin pasar por un diálogo de OAuth."""

    @property
    def fields(self) -> Sequence[CredentialField]:
        """Lo que hay que pedirle a la persona."""
        ...

    async def login(self, credentials: Mapping[str, str]) -> Token:
        """Cambia la credencial por un token. Lanza `TokenRejected` si la red no la acepta.

        La credencial no se guarda: se guarda el token.
        """
        ...

    def can_refresh(self, token: Token) -> bool: ...

    async def refresh(self, token: Token) -> Token: ...

    async def revoke(self, token: Token) -> None: ...


class TokenRefresher(Protocol):
    """Lo que tienen en común las tres formas de conectar: renovar y revocar."""

    def can_refresh(self, token: Token) -> bool: ...

    async def refresh(self, token: Token) -> Token: ...

    async def revoke(self, token: Token) -> None: ...


class AssetDirectory(Protocol):
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]: ...


class ContentReader(Protocol):
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]: ...


class CommentGateway(Protocol):
    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]: ...

    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        """Devuelve el id del comentario nuevo."""
        ...

    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None: ...

    async def delete(self, asset: Asset, token: Token, *, comment_id: str) -> None: ...

    async def like(self, asset: Asset, token: Token, *, comment_id: str) -> None: ...

    def supports(self, asset: Asset, action: CommentAction) -> bool:
        """Si la red ofrece esa acción para ese tipo de activo. No consulta nada: lo define la API."""
        ...


class MessagingGateway(Protocol):
    @property
    def reply_window(self) -> ReplyWindow: ...

    async def list_conversations(
        self, asset: Asset, token: Token, *, limit: int | None
    ) -> Sequence[Conversation]: ...

    async def list_messages(
        self, asset: Asset, token: Token, *, conversation_id: str, limit: int | None
    ) -> Sequence[Message]: ...

    async def send(self, asset: Asset, token: Token, *, recipient_id: str, text: str) -> str:
        """Le escribe a la persona. Devuelve el id del mensaje."""
        ...


class InsightsReader(Protocol):
    @property
    def catalog(self) -> MetricCatalog: ...

    @property
    def api_version(self) -> str: ...

    async def read(
        self, asset: Asset, token: Token, *, metrics: Sequence[str], period: Period, window: TimeWindow
    ) -> Sequence[MetricSeries]: ...


class Publisher(Protocol):
    """Publicar en un activo. Los límites de cada tipo de activo van en la descripción de la red."""

    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        """Publica un borrador que ya pasó la validación.

        Si la red publica en etapas, devuelve `PENDING` con lo necesario para retomarla en `resume`. Si
        salió pero un paso posterior falló, `PUBLISHED_WITH_ERROR`: nunca una excepción, porque repetir el
        pedido duplicaría la publicación.
        """
        ...

    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        """Retoma una publicación pendiente. Llamarla dos veces no publica dos veces."""
        ...

    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None: ...


class ProfileLookup(Protocol):
    """Perfiles públicos de cuentas ajenas, por su nombre."""

    @property
    def networks(self) -> frozenset[Network]:
        """Las redes cuyos perfiles sabe leer."""
        ...

    def viewer_kinds(self, network: Network) -> frozenset[str]:
        """Los tipos de activo propio que sirven de mirador para esa red. Vacío si no hace falta ninguno.

        Algunas redes solo muestran cuentas ajenas a través de una cuenta propia (Instagram, por ejemplo).
        """
        ...

    async def lookup(
        self, handle: Handle, *, viewer: Asset | None, token: Token | None
    ) -> PublicProfile | None:
        """El perfil, o `None` si la cuenta no existe o la red no la deja ver."""
        ...


class WebhookParser(Protocol):
    def handshake(self, query: Mapping[str, str]) -> str | None:
        """La respuesta al pedido con que la red confirma la URL del webhook, o `None` si no es válido."""
        ...

    @property
    def verifier(self) -> Verifier:
        """El esquema de firma de la red, armado con omniwebhook. Sin secreto, rechaza todo."""
        ...

    def parse(self, body: bytes) -> Sequence[SocialEvent]: ...


# ── Infraestructura común ───────────────────────────────────────────────────────────────────────


class ConnectionRepository(Protocol):
    async def get(self, connection_id: str) -> Connection | None: ...

    async def find(self, *, owner: str, provider: ProviderId, subject_id: str) -> Connection | None: ...

    async def list_by_owner(self, owner: str) -> Sequence[Connection]: ...

    async def list_expiring(self, before: datetime, *, limit: int) -> Sequence[Connection]:
        """Las conexiones activas cuyo token vence antes de ese momento, de la que vence primero a la que
        vence última. Las que no vencen nunca no entran."""
        ...

    async def add(self, connection: Connection) -> None: ...

    async def save(self, connection: Connection, *, expected_version: int) -> bool:
        """Guarda solo si la versión guardada sigue siendo `expected_version`. Devuelve si guardó."""
        ...


ConnectionObserver = Callable[[ConnectionChange], Awaitable[None]]
"""Se llama cuando una conexión deja de servir o vuelve a servir, después de guardar el cambio."""


class AssetRepository(Protocol):
    async def get(self, asset_id: str) -> Asset | None: ...

    async def list_by_owner(self, owner: str, *, provider: ProviderId | None = None) -> Sequence[Asset]: ...

    async def list_by_connection(self, connection_id: str) -> Sequence[Asset]: ...

    async def find_by_external_id(self, provider: ProviderId, external_id: str) -> Sequence[Asset]:
        """Todos los activos con ese id en la red, de cualquier dueño. Sirve para enrutar webhooks."""
        ...

    async def replace_for_connection(self, connection_id: str, assets: Sequence[Asset]) -> None:
        """Deja exactamente esos activos para la conexión. Conserva el `id` de los que ya existían."""
        ...


class PublicationRepository(Protocol):
    async def get(self, publication_id: str) -> Publication | None: ...

    async def find_by_key(self, asset_id: str, idempotency_key: str) -> Publication | None: ...

    async def add(self, publication: Publication) -> bool:
        """Guarda una publicación nueva. Devuelve `False`, sin guardar, si ese activo ya tiene una con la
        misma clave de idempotencia."""
        ...

    async def save(self, publication: Publication, *, expected_version: int) -> bool:
        """Guarda solo si la versión guardada sigue siendo `expected_version`. Devuelve si guardó."""
        ...

    async def remove(self, publication_id: str) -> None:
        """Libera la reserva de una publicación que con certeza no salió, para poder reintentarla."""
        ...


class QuotaLedger(Protocol):
    """Lleva la cuenta de lo gastado por clave y por período (un día, en general)."""

    async def spend(self, key: str, period: str, units: int, *, limit: int) -> bool:
        """Suma `units` a lo gastado si el total no pasa de `limit`. Devuelve si entró.

        Es atómico: dos procesos que gastan a la vez no pasan juntos el límite.
        """
        ...

    async def spent(self, key: str, period: str) -> int: ...


class ServerAppStore(Protocol):
    """Las apps registradas en cada servidor de una red federada."""

    async def get(self, provider: ProviderId, server: str) -> ServerApp | None: ...

    async def add(self, app: ServerApp) -> ServerApp:
        """Guarda la app si ese servidor no tenía una. Devuelve la que quedó guardada: si dos procesos
        registran a la vez, los dos usan la misma."""
        ...

    async def replace(self, app: ServerApp) -> None:
        """Cambia la app de ese servidor. Hace falta cuando cambió la URL de retorno: la app anterior
        quedó atada a la vieja."""
        ...


class AuthorizationStateStore(Protocol):
    async def put(self, request: AuthorizationRequest) -> None: ...

    async def take(self, state: str) -> AuthorizationRequest | None:
        """Devuelve el pedido y lo borra: un `state` sirve una sola vez."""
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class SecretGenerator(Protocol):
    def token(self, nbytes: int) -> str:
        """Un valor aleatorio seguro y apto para URL."""
        ...


class TokenCipher(Protocol):
    """Cifra los tokens antes de guardarlos.

    `context` va como dato autenticado: un token cifrado para una conexión no se puede pegar en otra fila
    y descifrar ahí.
    """

    def encrypt(self, plaintext: str, *, context: str) -> str: ...

    def decrypt(self, ciphertext: str, *, context: str) -> str: ...
