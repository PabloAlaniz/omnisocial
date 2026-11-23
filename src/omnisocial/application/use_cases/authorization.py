"""Autorizar: iniciar, completar el callback, registrar un usuario de sistema y desconectar."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
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
)
from omnisocial.domain.asset import Asset
from omnisocial.domain.authorization import DEFAULT_STATE_TTL, AuthorizationRequest, Purpose
from omnisocial.domain.connection import Connection, ConnectionStatus
from omnisocial.domain.errors import TokenRejected
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.domain.token import Token

RedirectUriFor = Callable[[str], str]
"""Devuelve la URL de callback registrada en la red para ese proveedor."""


class StartAuthorization:
    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        states: AuthorizationStateStore,
        secrets: SecretGenerator,
        clock: Clock,
        return_urls: ReturnUrlPolicy,
        redirect_uri_for: RedirectUriFor,
        state_ttl: timedelta = DEFAULT_STATE_TTL,
    ) -> None:
        self._registry = registry
        self._states = states
        self._secrets = secrets
        self._clock = clock
        self._return_urls = return_urls
        self._redirect_uri_for = redirect_uri_for
        self._state_ttl = state_ttl

    async def execute(
        self,
        provider_id: str,
        *,
        purpose: Purpose,
        owner: str | None = None,
        return_url: str | None = None,
        scopes: Sequence[str] | None = None,
    ) -> AuthorizationStarted | Refused:
        provider = self._registry.get(provider_id)
        oauth = provider.require_oauth()
        if purpose is Purpose.CONNECT and not owner:
            return Refused(Refusal.OWNER_REQUIRED)
        if return_url is not None and not self._return_urls.allows(return_url):
            return Refused(Refusal.RETURN_URL_NOT_ALLOWED)

        now = self._clock.now()
        request = AuthorizationRequest(
            state=self._secrets.token(32),
            provider=provider.id,
            purpose=purpose,
            redirect_uri=self._redirect_uri_for(provider.id),
            created_at=now,
            expires_at=now + self._state_ttl,
            scopes=tuple(scopes) if scopes is not None else oauth.default_scopes(purpose),
            owner=owner,
            return_url=return_url,
            code_verifier=self._secrets.token(48) if oauth.supports_pkce else None,
        )
        await self._states.put(request)
        url = oauth.authorization_url(
            state=request.state,
            redirect_uri=request.redirect_uri,
            scopes=request.scopes,
            code_challenge=request.code_challenge,
        )
        return AuthorizationStarted(url=url, state=request.state)


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
    ) -> None:
        self._connections = connections
        self._assets = assets
        self._clock = clock
        self._ids = ids

    async def store(self, provider: Provider, *, owner: str, token: Token) -> Connected:
        oauth = provider.require_oauth()
        subject = await oauth.identity(token)
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

        assets: Sequence[Asset] = ()
        if provider.assets is not None:
            assets = await AssetSync(assets=self._assets, ids=self._ids).sync(provider, connection)
        return Connected(connection=connection, assets=assets, reconnected=existing is not None)


class AssetSync:
    def __init__(self, *, assets: AssetRepository, ids: IdGenerator) -> None:
        self._assets = assets
        self._ids = ids

    async def sync(self, provider: Provider, connection: Connection) -> Sequence[Asset]:
        discovered = await provider.require_assets().discover(connection.token)
        known = {(a.kind, a.external_id): a.id for a in await self._assets.list_by_connection(connection.id)}
        assets = [
            Asset.from_discovered(
                item,
                id=known.get((item.kind, item.external_id)) or self._ids.new_id(),
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
        request = await self._states.take(state)
        if request is None:
            return Refused(Refusal.UNKNOWN_STATE)
        if request.is_expired(self._clock.now()):
            return Refused(Refusal.EXPIRED_STATE, return_url=request.return_url)
        if error is not None or not code:
            return Refused(Refusal.PROVIDER_DENIED, detail=error, return_url=request.return_url)

        provider = self._registry.get(request.provider)
        oauth = provider.require_oauth()
        token = await oauth.exchange_code(
            code=code, redirect_uri=request.redirect_uri, code_verifier=request.code_verifier
        )
        if request.purpose is Purpose.LOGIN:
            identity = await oauth.identity(token)
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


class RegisterSystemConnection:
    """Guarda un token que no pasó por el diálogo de autorización, como el de un usuario de sistema.

    Sirve cuando la organización administra los activos en su propio portfolio de la red y no hace falta
    que cada dueño autorice.
    """

    def __init__(self, *, registry: ProviderRegistry, store: ConnectionStore) -> None:
        self._registry = registry
        self._store = store

    async def execute(self, provider_id: str, *, owner: str, token: Token) -> Connected:
        return await self._store.store(self._registry.get(provider_id), owner=owner, token=token)


class Disconnect:
    """Revoca en la red (si se puede) y marca la conexión como revocada."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        connections: ConnectionRepository,
        assets: AssetRepository,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._connections = connections
        self._assets = assets
        self._clock = clock

    async def execute(self, connection_id: str, *, revoke_remote: bool = True) -> Done[Connection] | Refused:
        connection = await self._connections.get(connection_id)
        if connection is None:
            return Refused(Refusal.NOT_FOUND)
        oauth = self._registry.get(connection.provider).oauth
        if revoke_remote and oauth is not None and connection.is_usable:
            with suppress(TokenRejected):  # si ya no servía, el resultado es el mismo
                await oauth.revoke(connection.token)
        revoked = connection.mark(ConnectionStatus.REVOKED, "desconectada", self._clock.now())
        while not await self._connections.save(revoked, expected_version=connection.version):
            current = await self._connections.get(connection_id)
            if current is None:  # pragma: no cover - borrada en medio
                return Refused(Refusal.NOT_FOUND)
            connection = current
            revoked = connection.mark(ConnectionStatus.REVOKED, "desconectada", self._clock.now())
        await self._assets.replace_for_connection(connection_id, ())
        return Done(revoked)
