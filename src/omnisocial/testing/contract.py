"""El contrato común: lo que el núcleo espera de cualquier red.

Cada red lo corre contra respuestas grabadas. Para eso arma un `NetworkHarness` (cómo se construye el
proveedor, qué responde la red al conectar y cómo dice cada clase de error) y hereda de `ProviderContract`.
Las pruebas pasan por los casos de uso: lo que se comprueba es el comportamiento que ve la app, no los
detalles del adaptador.
"""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from urllib.parse import parse_qsl, urlsplit

from omniwebhook import AsyncMemoryIdempotencyStore, IncomingRequest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
)
from omnisocial.adapters.system import SystemClock
from omnisocial.application.ports import (
    AssetDirectory,
    CommentGateway,
    ContentReader,
    CredentialLogin,
    IdentityReader,
    InsightsReader,
    LookupReader,
    MessagingGateway,
    OAuthClient,
    ProfileLookup,
    ServerOAuth,
    WebhookParser,
)
from omnisocial.application.registry import Provider
from omnisocial.application.results import (
    AuthorizationStarted,
    Connected,
    Done,
    Refusal,
    Refused,
    ValidToken,
)
from omnisocial.domain.asset import Asset
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.messaging import Recipient
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import (
    BytesFile,
    Draft,
    DraftIssue,
    Media,
    MediaKind,
    PublishLimits,
    PublishOptions,
    check_draft,
)
from omnisocial.domain.redirect import ReturnUrlPolicy
from omnisocial.domain.spec import NetworkSpec
from omnisocial.domain.window import TimeWindow
from omnisocial.entrypoints.hub import Omnisocial
from omnisocial.testing.transport import FakeTransport

_ID = re.compile(r"[a-z][a-z0-9_]*")
_REDIRECT = "https://api.ejemplo.com/oauth/callback"
_APP = "https://app.ejemplo.com"

_REFUSAL: Mapping[ErrorKind, Refusal] = {
    ErrorKind.TOKEN_DEAD: Refusal.CONNECTION_INVALID,
    ErrorKind.MISSING_PERMISSION: Refusal.MISSING_PERMISSION,
    ErrorKind.RATE_LIMITED: Refusal.RATE_LIMITED,
    ErrorKind.QUOTA_EXHAUSTED: Refusal.QUOTA_EXHAUSTED,
}
"""Las clases de error que el núcleo traduce a una negativa. Las demás son excepciones."""


class NetworkHarness(ABC):
    """Lo que el contrato necesita saber de una red para probarla."""

    transport: FakeTransport

    @property
    @abstractmethod
    def spec(self) -> NetworkSpec: ...

    @abstractmethod
    def provider(self) -> Provider:
        """El proveedor con la configuración completa, armado sobre `self.transport`."""

    @abstractmethod
    def script_connection(self) -> None:
        """Deja en `self.transport` lo que la red responde cuando alguien conecta una cuenta: el canje del
        código, la identidad y los activos. Tiene que haber al menos un activo de cada tipo declarado."""

    @abstractmethod
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        """Cómo responde la red ante esa clase de error, o `None` si la red no tiene esa clase."""

    def server(self) -> str | None:
        """En una red federada, el servidor donde está la cuenta de prueba."""
        return None

    def credentials(self) -> Mapping[str, str]:
        """En una red que conecta con una credencial, la de la cuenta de prueba."""
        return {}

    def options(self, kind: str) -> PublishOptions | None:  # noqa: ARG002  # lo usa quien lo cambia
        """Las opciones de un borrador mínimo para ese tipo de activo, si no publica sin ellas."""
        return None

    def app_token_capabilities(self) -> frozenset[Capability]:
        """Las capacidades que la red atiende con una credencial de la app (el token de un bot) y no con
        el token de la conexión. Si esa credencial deja de valer, no es la conexión la que murió."""
        return frozenset()

    def script_lookups(self) -> None:  # noqa: B027  # opcional: la mayoría de las redes no tiene
        """Deja en `self.transport` lo que la red responde a cada consulta auxiliar que declara, con al
        menos una opción."""

    def unsigned_webhook(self) -> IncomingRequest:
        """Un aviso sin firma. Se cambia solo si la red necesita otra forma de pedido."""
        return IncomingRequest(headers=[], query=[], body=b"{}")


@dataclass(frozen=True, slots=True)
class _World:
    harness: NetworkHarness
    provider: Provider
    social: Omnisocial


Probe = Callable[[_World, Asset], Awaitable[object]]


def _world(harness: NetworkHarness) -> _World:
    provider = harness.provider()
    clock = SystemClock()
    social = Omnisocial.build(
        providers=[provider],
        connections=InMemoryConnectionRepository(),
        assets=InMemoryAssetRepository(),
        states=InMemoryAuthorizationStateStore(clock),
        webhook_events=AsyncMemoryIdempotencyStore(),
        redirect_uri_for=lambda _provider: _REDIRECT,
        return_urls=ReturnUrlPolicy.of(_APP),
        clock=clock,
    )
    return _World(harness, provider, social)


async def _connect(world: _World) -> Connected:
    """Conecta la cuenta de prueba como lo hace esa red: con una credencial, o autorizando (en su
    servidor, si es federada)."""
    world.harness.script_connection()
    connected: object
    if world.provider.credentials is not None:
        connected = await world.social.connect_with_credentials.execute(
            world.provider.id, owner="dueño", credentials=world.harness.credentials()
        )
    else:
        started = await world.social.start_authorization.execute(
            world.provider.id,
            purpose=Purpose.CONNECT,
            owner="dueño",
            return_url=_APP,
            server=world.harness.server(),
        )
        assert isinstance(started, AuthorizationStarted), f"No se pudo empezar a autorizar: {started}"
        connected = await world.social.complete_authorization.execute(state=started.state, code="codigo")
    assert isinstance(connected, Connected), f"No se pudo conectar: {connected}"
    return connected


async def _posts(world: _World, asset: Asset) -> object:
    return await world.social.list_posts.execute(asset.id, limit=1)


async def _comments(world: _World, asset: Asset) -> object:
    return await world.social.list_comments.execute(asset.id, object_id="objeto")


async def _conversations(world: _World, asset: Asset) -> object:
    messaging = world.provider.require_messaging()
    if messaging.limits_for(asset).history:
        return await world.social.list_conversations.execute(asset.id, limit=1)
    # La red no deja leer conversaciones: se prueba mandando un mensaje a alguien que acaba de escribir.
    to = Recipient("5491100000000", SystemClock().now())
    return await world.social.send_message.execute(asset.id, text="hola", to=to)


async def _insights(world: _World, asset: Asset) -> object:
    insights = world.provider.require_insights()
    known = next(
        (m for m in CanonicalMetric if insights.catalog.native_for(asset.kind, m, insights.api_version)),
        None,
    )
    assert known is not None, f"El catálogo no traduce ninguna métrica común para '{asset.kind}'."
    now = SystemClock().now()
    return await world.social.read_insights.execute(
        asset.id, metrics=[known], period=Period.DAY, window=TimeWindow(now - timedelta(days=2), now)
    )


def _sample(kind: MediaKind, limits: PublishLimits) -> Media:
    by_url = limits.media_by_url
    if kind is MediaKind.VIDEO and limits.video_by_url is not None:
        by_url = limits.video_by_url
    if by_url:
        extension = "mp4" if kind is MediaKind.VIDEO else "jpg"
        return Media(kind, f"https://cdn.ejemplo.com/medio.{extension}")
    content_type = "video/mp4" if kind is MediaKind.VIDEO else "image/jpeg"
    return Media(kind, file=BytesFile(b"contenido de prueba", content_type))


def _draft(world: _World, asset: Asset) -> Draft:
    """Un borrador que entra en ese tipo de activo, armado desde los límites que declara."""
    limits = world.harness.spec.publishing[asset.kind]
    options = world.harness.options(asset.kind)
    if limits.max_videos:
        return Draft("hola", media=(_sample(MediaKind.VIDEO, limits),), options=options)
    if limits.max_images:
        return Draft("hola", media=(_sample(MediaKind.IMAGE, limits),), options=options)
    return Draft("hola", options=options)


async def _publish(world: _World, asset: Asset) -> object:
    return await world.social.publish.execute(asset.id, _draft(world, asset))


_PROBES: Mapping[Capability, Probe] = {
    Capability.PUBLISHING: _publish,
    Capability.CONTENT: _posts,
    Capability.COMMENTS: _comments,
    Capability.MESSAGING: _conversations,
    Capability.INSIGHTS: _insights,
}
"""Una lectura por capacidad, para ver qué hace cada una cuando la red falla."""

_PORTS: Mapping[str, type] = {
    "oauth": OAuthClient,
    "server_oauth": ServerOAuth,
    "credentials": CredentialLogin,
    "identity": IdentityReader,
    "assets": AssetDirectory,
    "content": ContentReader,
    "comments": CommentGateway,
    "messaging": MessagingGateway,
    "insights": InsightsReader,
    "webhooks": WebhookParser,
    "profiles": ProfileLookup,
    "lookups": LookupReader,
}


def _run(check: Coroutine[object, object, None]) -> None:
    asyncio.run(check)


class ProviderContract:
    """Heredar en una clase `Test…` y devolver el `NetworkHarness` de la red."""

    def harness(self) -> NetworkHarness:
        raise NotImplementedError

    # ── La descripción ──────────────────────────────────────────────────────────────────────────

    def test_la_descripcion_dice_la_verdad(self) -> None:
        harness = self.harness()
        provider, spec = harness.provider(), harness.spec
        assert provider.spec is spec, "El proveedor no lleva la descripción de la red."
        assert provider.id == spec.id
        assert _ID.fullmatch(spec.id), f"El id '{spec.id}' se guarda en la base: minúsculas, números y _."
        assert provider.capabilities == spec.capabilities, (
            "Las capacidades declaradas no son las del proveedor: "
            f"{sorted(provider.capabilities ^ spec.capabilities)}"
        )
        assert spec.docs, "Falta la página de la red (`docs`)."
        if Capability.ASSETS in spec.capabilities:
            assert spec.assets, "La red descubre activos pero no declara ningún tipo."

    def test_cada_adaptador_hereda_de_su_puerto(self) -> None:
        provider = self.harness().provider()
        for name, port in _PORTS.items():
            component = getattr(provider, name)
            if component is not None:
                assert port in type(component).__mro__, (
                    f"`{type(component).__name__}` no hereda de `{port.__name__}`: "
                    "un cambio en el puerto no se detectaría."
                )

    # ── Autorizar ───────────────────────────────────────────────────────────────────────────────

    def test_la_url_de_autorizacion_lleva_lo_que_manda_el_nucleo(self) -> None:
        oauth = self.harness().provider().oauth
        if oauth is None:
            return
        scopes = oauth.default_scopes(Purpose.CONNECT)
        assert oauth.default_scopes(Purpose.LOGIN), "Hacen falta permisos para el login."
        url = oauth.authorization_url(
            state="estado-1", redirect_uri=_REDIRECT, scopes=scopes, code_challenge="desafio-1"
        )
        parts = urlsplit(url)
        values = [value for _, value in parse_qsl(parts.query)]
        assert parts.scheme == "https"
        assert "estado-1" in values, "La URL no lleva el `state`."
        assert _REDIRECT in values, "La URL no lleva la `redirect_uri`."
        granted = " ".join(values)
        assert all(scope in granted for scope in scopes), "La URL no lleva todos los permisos."
        assert ("desafio-1" in values) == oauth.supports_pkce, "PKCE: la URL no coincide con `supports_pkce`."

    def test_en_una_red_federada_se_autoriza_en_el_servidor_de_la_persona(self) -> None:
        _run(self._url_por_servidor())

    async def _url_por_servidor(self) -> None:
        harness = self.harness()
        oauth = harness.provider().server_oauth
        if oauth is None:
            return
        server = harness.server()
        assert server, "Una red federada necesita el servidor de la cuenta de prueba (`server`)."
        harness.script_connection()
        url = await oauth.authorization_url(
            server,
            state="estado-1",
            redirect_uri=_REDIRECT,
            scopes=oauth.default_scopes(Purpose.CONNECT),
            code_challenge="desafio-1",
        )
        parts = urlsplit(url)
        values = [value for _, value in parse_qsl(parts.query)]
        assert (parts.scheme, parts.hostname) == ("https", server), "La URL no es la del servidor elegido."
        assert "estado-1" in values, "La URL no lleva el `state`."
        assert _REDIRECT in values, "La URL no lleva la `redirect_uri`."
        assert ("desafio-1" in values) == oauth.supports_pkce, "PKCE: la URL no coincide con `supports_pkce`."

    # ── Conectar ────────────────────────────────────────────────────────────────────────────────

    def test_conectar_guarda_la_conexion_y_sus_activos(self) -> None:
        _run(self._conectar())

    async def _conectar(self) -> None:
        world = _world(self.harness())
        connected = await _connect(world)
        spec = world.harness.spec
        connection = connected.connection
        assert connection.subject.external_id, "La identidad no trae el id estable de la persona."
        for token in (connection.token, *(a.token for a in connected.assets if a.token is not None)):
            assert token.access_token not in repr(token), "El token aparece en `repr`."
        if Capability.ASSETS not in spec.capabilities:
            return
        found = {asset.kind: asset for asset in connected.assets}
        assert set(found) == set(spec.assets), (
            f"Activos descubiertos {sorted(found)}, declarados {sorted(spec.assets)}."
        )
        for kind, asset in found.items():
            assert asset.capabilities == spec.assets[kind], (
                f"'{kind}' habilita {sorted(asset.capabilities)} y declara {sorted(spec.assets[kind])}."
            )
            assert asset.external_id

    # ── Errores ─────────────────────────────────────────────────────────────────────────────────

    def test_los_errores_se_traducen_igual_en_toda_capacidad(self) -> None:
        _run(self._errores())

    async def _errores(self) -> None:
        harness = self.harness()
        assert harness.error(ErrorKind.TOKEN_DEAD) is not None, "Toda red sabe decir que un token murió."
        for kind, refusal in _REFUSAL.items():
            for capability, probe in _PROBES.items():
                await self._error(kind, refusal, capability, probe)

    async def _error(self, kind: ErrorKind, refusal: Refusal, capability: Capability, probe: Probe) -> None:
        # Un mundo nuevo cada vez: un token muerto deja la conexión inválida.
        world = _world(self.harness())
        response = world.harness.error(kind)
        if response is None:
            return
        if kind is ErrorKind.TOKEN_DEAD and capability in world.harness.app_token_capabilities():
            return
        connected = await _connect(world)
        for asset in connected.assets:
            if capability not in asset.capabilities:
                continue
            world.harness.transport.failing = response
            result = await probe(world, asset)
            world.harness.transport.failing = None
            where = f"{kind} en {capability} de '{asset.kind}'"
            assert isinstance(result, Refused), f"{where}: se esperaba una negativa y volvió {result!r}."
            assert result.reason is refusal, f"{where}: volvió {result.reason}, se esperaba {refusal}."
            token = await world.social.get_valid_token.execute(connected.connection.id)
            alive = isinstance(token, ValidToken)
            assert alive == (kind is not ErrorKind.TOKEN_DEAD), (
                f"{where}: la conexión quedó {'sana' if alive else 'inválida'}."
            )
            if not alive:
                return

    # ── Publicar ────────────────────────────────────────────────────────────────────────────────

    def test_un_borrador_que_no_entra_no_llega_a_la_red(self) -> None:
        _run(self._borrador_invalido())

    async def _borrador_invalido(self) -> None:
        world = _world(self.harness())
        if Capability.PUBLISHING not in world.harness.spec.capabilities:
            return
        connected = await _connect(world)
        publishers = [a for a in connected.assets if Capability.PUBLISHING in a.capabilities]
        assert publishers, "La red publica, pero ningún activo descubierto lo habilita."
        for asset in publishers:
            limits = world.harness.spec.publishing[asset.kind]
            assert not check_draft(_draft(world, asset), limits), (
                f"Los límites de '{asset.kind}' no dejan pasar ni un borrador mínimo."
            )
            before = len(world.harness.transport.calls)
            long = replace(_draft(world, asset), text="x" * (limits.max_text + 1))
            refused = await world.social.publish.execute(asset.id, long)
            assert isinstance(refused, Refused), f"'{asset.kind}': un texto demasiado largo no fue rechazado."
            assert refused.reason is Refusal.INVALID_DRAFT
            assert DraftIssue.TEXT_TOO_LONG in [problem.issue for problem in refused.problems]
            assert len(world.harness.transport.calls) == before, (
                f"'{asset.kind}': se llamó a la red con un borrador que no entraba."
            )

    def test_cada_consulta_auxiliar_declarada_responde(self) -> None:
        _run(self._consultas())

    async def _consultas(self) -> None:
        world = _world(self.harness())
        spec = world.harness.spec
        assert bool(spec.lookups) == (world.provider.lookups is not None), (
            "La red declara consultas auxiliares si y solo si trae quien las responde."
        )
        if not spec.lookups:
            return
        connected = await _connect(world)
        world.harness.script_lookups()
        for asset in connected.assets:
            for lookup in spec.lookups.get(asset.kind, ()):
                found = await world.social.list_choices.execute(
                    asset.id, lookup.name, parent="padre" if lookup.parent else None
                )
                where = f"'{lookup.name}' de '{asset.kind}'"
                assert isinstance(found, Done), f"{where}: volvió {found!r}."
                assert found.value, f"{where}: no devolvió ninguna opción."
                assert all(choice.id and choice.name for choice in found.value), f"{where}: opción vacía."

    # ── Webhooks ────────────────────────────────────────────────────────────────────────────────

    def test_un_aviso_sin_firma_no_se_traduce(self) -> None:
        _run(self._aviso_sin_firma())

    async def _aviso_sin_firma(self) -> None:
        world = _world(self.harness())
        parser = world.provider.webhooks
        if parser is None:
            return
        assert parser.handshake({}) is None, "Un saludo vacío no confirma la URL del webhook."
        seen: list[object] = []

        async def on_events(events: object) -> None:
            seen.append(events)

        received = await world.social.handle_webhook.execute(
            world.provider.id, request=world.harness.unsigned_webhook(), on_events=on_events
        )
        assert received.outcome not in {"ok", "duplicate"}, "Un aviso sin firma fue aceptado."
        assert not seen, "Un aviso sin firma llegó a `on_events`."
