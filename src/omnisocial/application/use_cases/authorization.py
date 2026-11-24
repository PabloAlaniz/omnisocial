"""Autorizar: iniciar, completar el callback, registrar un usuario de sistema y desconectar."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta

from omnisocial.application.ports import (
    AssetRepository,
    AuthorizationStateStore,
    Clock,
    ConnectionRepository,
    IdGenerator,
    SecretGenerator,
)
from omnisocial.application.registry import Provider, ProviderRegistry
from omnisocial.application.results import (
    AuthorizationStarted,
    Connected,
    Done,
    LoggedIn,
    Refusal,
    Refused,
    refusal_for,
)
from omnisocial.application.use_cases.access import ConnectionWatch
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.authorization import DEFAULT_STATE_TTL, AuthorizationRequest, Purpose
from omnisocial.domain.connection import Connection, ConnectionStatus
from omnisocial.domain.errors import ProviderError, TokenRejected
from omnisocial.domain.provider import Capability
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.domain.server import normalize_server
from omnisocial.domain.token import Token

RedirectUriFor = Callable[[str], str]
"""Devuelve la URL de callback registrada en la red para ese proveedor."""


@dataclass(frozen=True, slots=True)
class AuthorizationSettings:
    """Cómo se autoriza: a dónde vuelve la red, a dónde se deja volver y cuánto dura el pedido."""

    return_urls: ReturnUrlPolicy
    redirect_uri_for: RedirectUriFor
    state_ttl: timedelta = DEFAULT_STATE_TTL


class StartAuthorization:
    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        states: AuthorizationStateStore,
        secrets: SecretGenerator,
        clock: Clock,
        settings: AuthorizationSettings,
    ) -> None:
        self._registry = registry
        self._states = states
        self._secrets = secrets
        self._clock = clock
        self._settings = settings

    async def execute(
        self,
        provider_id: str,
        *,
        purpose: Purpose,
        owner: str | None = None,
        return_url: str | None = None,
        scopes: Sequence[str] | None = None,
        server: str | None = None,
    ) -> AuthorizationStarted | Refused:
        """`server`: en una red federada, el servidor donde está la cuenta (`mastodon.social`)."""
        provider = self._registry.get(provider_id)
        oauth = provider.server_oauth or provider.require_oauth()
        if purpose is Purpose.CONNECT and not owner:
            return Refused(Refusal.OWNER_REQUIRED)
        if return_url is not None and not self._settings.return_urls.allows(return_url):
            return Refused(Refusal.RETURN_URL_NOT_ALLOWED)
        host = _server_for(provider, server)
        if isinstance(host, Refused):
            return host

        now = self._clock.now()
        request = AuthorizationRequest(
            state=self._secrets.token(32),
            provider=provider.id,
            purpose=purpose,
            redirect_uri=self._settings.redirect_uri_for(provider.id),
            created_at=now,
            expires_at=now + self._settings.state_ttl,
            scopes=tuple(scopes) if scopes is not None else oauth.default_scopes(purpose),
            owner=owner,
            return_url=return_url,
            code_verifier=self._secrets.token(48) if oauth.supports_pkce else None,
            server=host,
        )
        await self._states.put(request)
        return AuthorizationStarted(url=await self._url(provider, request), state=request.state)

    @staticmethod
    async def _url(provider: Provider, request: AuthorizationRequest) -> str:
        details = {
            "state": request.state,
            "redirect_uri": request.redirect_uri,
            "scopes": request.scopes,
            "code_challenge": request.code_challenge,
        }
        if provider.server_oauth is not None and request.server is not None:
            return await provider.server_oauth.authorization_url(request.server, **details)  # type: ignore[arg-type]
        return provider.require_oauth().authorization_url(**details)  # type: ignore[arg-type]


def _server_for(provider: Provider, server: str | None) -> str | Refused | None:
    """El servidor validado, `None` si la red no es federada, o la negativa que corresponde."""
    if provider.server_oauth is None:
        return None
    if not server:
        return Refused(Refusal.SERVER_REQUIRED)
    host = normalize_server(server)
    return host if host is not None else Refused(Refusal.INVALID_SERVER, detail=server)


class ConnectionStore:
    """Guarda una conexión nueva o reconecta una existente, y descubre sus activos.

    Lo comparten el callback de OAuth y el registro de un usuario de sistema.
    """

    def __init__(
        self,
        *,
        connections: ConnectionRepository,
        assets: AssetRepository,
        clock: Clock,
        ids: IdGenerator,
        watch: ConnectionWatch | None = None,
    ) -> None:
        self._connections = connections
        self._assets = assets
        self._clock = clock
        self._ids = ids
        self._watch = watch or ConnectionWatch()

    async def store(
        self,
        provider: Provider,
        *,
        owner: str,
        token: Token,
        discovered: Sequence[DiscoveredAsset] | None = None,
    ) -> Connected:
        """`discovered`: los activos ya descubiertos con este token, para no pedirlos dos veces."""
        subject = await provider.require_identity().identity(token)
        now = self._clock.now()
        existing = await self._connections.find(
            owner=owner, provider=provider.id, subject_id=subject.external_id
        )
        if existing is None:
            connection = Connection(
                id=self._ids.new_id(),
                provider=provider.id,
                owner=owner,
                subject=subject,
                token=token,
                status=ConnectionStatus.ACTIVE,
                version=1,
                created_at=now,
                updated_at=now,
            )
            await self._connections.add(connection)
        else:
            connection = existing.reconnect(subject, token, now)
            # Reconectar gana siempre: es una autorización nueva y explícita de la persona.
            while not await self._connections.save(connection, expected_version=existing.version):
                current = await self._connections.get(existing.id)
                if current is None:  # pragma: no cover - borrada en medio de la reconexión
                    await self._connections.add(connection)
                    break
                existing = current
                connection = existing.reconnect(subject, token, now)
            # Reconectar una conexión que no servía la recupera, con el mismo id y los mismos activos.
            await self._watch.changed(existing, connection)

        assets: Sequence[Asset] = ()
        if provider.assets is not None:
            assets = await AssetSync(assets=self._assets, ids=self._ids).sync(
                provider, connection, discovered=discovered
            )
        return Connected(connection=connection, assets=assets, reconnected=existing is not None)


class AssetSync:
    def __init__(self, *, assets: AssetRepository, ids: IdGenerator) -> None:
        self._assets = assets
        self._ids = ids

    async def sync(
        self,
        provider: Provider,
        connection: Connection,
        *,
        discovered: Sequence[DiscoveredAsset] | None = None,
    ) -> Sequence[Asset]:
        if discovered is None:
            discovered = await provider.require_assets().discover(connection.token)
        known = {(a.kind, a.external_id): a.id for a in await self._assets.list_by_connection(connection.id)}
        assets = [
            Asset.from_discovered(
                item,
                asset_id=known.get((item.kind, item.external_id)) or self._ids.new_id(),
                connection_id=connection.id,
                provider=provider.id,
                owner=connection.owner,
            )
            for item in discovered
        ]
        await self._assets.replace_for_connection(connection.id, assets)
        return assets


class CompleteAuthorization:
    """El callback: valida el `state`, cambia el código por un token y guarda o solo identifica."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        states: AuthorizationStateStore,
        clock: Clock,
        store: ConnectionStore,
    ) -> None:
        self._registry = registry
        self._states = states
        self._clock = clock
        self._store = store

    async def execute(
        self, *, state: str, code: str | None, error: str | None = None
    ) -> LoggedIn | Connected | Refused:
        checked = self._check(await self._states.take(state), code=code, error=error)
        if isinstance(checked, Refused):
            return checked
        request, valid_code = checked

        provider = self._registry.get(request.provider)
        token = await self._exchange(provider, request, valid_code)
        if request.purpose is Purpose.LOGIN:
            identity = await provider.require_identity().identity(token)
            return LoggedIn(identity=identity, token=token, return_url=request.return_url)
        if request.owner is None:  # pragma: no cover - StartAuthorization lo exige para CONNECT
            return Refused(Refusal.OWNER_REQUIRED, return_url=request.return_url)
        connected = await self._store.store(provider, owner=request.owner, token=token)
        return Connected(
            connection=connected.connection,
            assets=connected.assets,
            return_url=request.return_url,
            reconnected=connected.reconnected,
        )

    @staticmethod
    async def _exchange(provider: Provider, request: AuthorizationRequest, code: str) -> Token:
        if provider.server_oauth is not None and request.server is not None:
            return await provider.server_oauth.exchange_code(
                request.server,
                code=code,
                redirect_uri=request.redirect_uri,
                code_verifier=request.code_verifier,
            )
        return await provider.require_oauth().exchange_code(
            code=code, redirect_uri=request.redirect_uri, code_verifier=request.code_verifier
        )

    def _check(
        self, request: AuthorizationRequest | None, *, code: str | None, error: str | None
    ) -> tuple[AuthorizationRequest, str] | Refused:
        """El pedido existe, no venció y la persona autorizó."""
        if request is None:
            return Refused(Refusal.UNKNOWN_STATE)
        if request.is_expired(self._clock.now()):
            return Refused(Refusal.EXPIRED_STATE, return_url=request.return_url)
        if error is not None or not code:
            return Refused(Refusal.PROVIDER_DENIED, detail=error, return_url=request.return_url)
        return request, code


class RegisterSystemConnection:
    """Guarda un token que no pasó por el diálogo de autorización, como el de un usuario de sistema.

    Sirve cuando la organización administra los activos en su propio portfolio de la red y no hace falta
    que cada dueño autorice.
    """

    def __init__(self, *, registry: ProviderRegistry, store: ConnectionStore) -> None:
        self._registry = registry
        self._store = store

    async def execute(self, provider_id: str, *, owner: str, token: Token) -> Connected | Refused:
        """Antes de guardar, comprueba que el token sirve y que ve al menos un activo.

        Un token que la red rechaza, al que le faltan permisos o que no administra nada no se guarda.
        """
        provider = self._registry.get(provider_id)
        if provider.assets is None:
            return await self._store.store(provider, owner=owner, token=token)
        try:
            discovered = await provider.assets.discover(token)
        except TokenRejected as error:
            return Refused(Refusal.PROVIDER_DENIED, detail=str(error))
        except ProviderError as error:
            refused = refusal_for(error, Capability.ASSETS)
            if refused is None:
                raise
            return refused
        if not discovered:
            return Refused(Refusal.NO_ASSETS)
        return await self._store.store(provider, owner=owner, token=token, discovered=discovered)


class ConnectWithCredentials:
    """Conecta una cuenta con una credencial que la persona generó en la red (una contraseña de
    aplicación, por ejemplo), para las redes que no usan un diálogo de OAuth.

    La credencial se cambia por un token y se descarta: lo que se guarda es el token.
    """

    def __init__(self, *, registry: ProviderRegistry, store: ConnectionStore) -> None:
        self._registry = registry
        self._store = store

    async def execute(
        self, provider_id: str, *, owner: str, credentials: Mapping[str, str]
    ) -> Connected | Refused:
        provider = self._registry.get(provider_id)
        login = provider.require_credentials()
        if not owner:
            return Refused(Refusal.OWNER_REQUIRED)
        missing = [f.name for f in login.fields if f.required and not credentials.get(f.name)]
        if missing:
            return Refused(Refusal.CREDENTIALS_REQUIRED, detail=", ".join(missing))
        try:
            token = await login.login(credentials)
        except TokenRejected as error:
            return Refused(Refusal.PROVIDER_DENIED, detail=str(error))
        except ProviderError as error:
            refused = refusal_for(error, Capability.CREDENTIALS)
            if refused is None:
                raise
            return refused
        return await self._store.store(provider, owner=owner, token=token)


class Disconnect:
    """Revoca en la red (si se puede) y marca la conexión como revocada."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        connections: ConnectionRepository,
        assets: AssetRepository,
        clock: Clock,
        watch: ConnectionWatch | None = None,
    ) -> None:
        self._registry = registry
        self._connections = connections
        self._assets = assets
        self._clock = clock
        self._watch = watch or ConnectionWatch()

    async def execute(self, connection_id: str, *, revoke_remote: bool = True) -> Done[Connection] | Refused:
        connection = await self._connections.get(connection_id)
        if connection is None:
            return Refused(Refusal.NOT_FOUND)
        refresher = self._registry.get(connection.provider).refresher
        if revoke_remote and refresher is not None and connection.is_usable:
            with suppress(TokenRejected):  # si ya no servía, el resultado es el mismo
                await refresher.revoke(connection.token)
        revoked = connection.mark(ConnectionStatus.REVOKED, "desconectada", self._clock.now())
        while not await self._connections.save(revoked, expected_version=connection.version):
            current = await self._connections.get(connection_id)
            if current is None:  # pragma: no cover - borrada en medio
                return Refused(Refusal.NOT_FOUND)
            connection = current
            revoked = connection.mark(ConnectionStatus.REVOKED, "desconectada", self._clock.now())
        await self._assets.replace_for_connection(connection_id, ())
        await self._watch.changed(connection, revoked)
        return Done(revoked)
