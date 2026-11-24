"""Instagram con login propio: el contrato común, el login y que los adaptadores de Meta sirven igual."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.meta.config import INSTAGRAM, INSTAGRAM_ACCOUNT
from omnisocial.adapters.providers.meta.instagram_login import (
    InstagramConfig,
    InstagramLogin,
    InstagramLoginAssets,
    instagram_provider,
)
from omnisocial.adapters.providers.meta.spec import INSTAGRAM_SPEC
from omnisocial.application.registry import Provider
from omnisocial.domain.asset import Asset
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ErrorKind, PermissionMissing, ProviderError, TokenRejected
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import Draft, Media, MediaKind, PublicationStatus
from omnisocial.domain.spec import NetworkSpec
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.window import TimeWindow
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract
from tests.fakes import NOW, FakeClock

BASE = "https://graph.instagram.com/v24.0/"
SHORT_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
LONG_TOKEN_URL = "https://graph.instagram.com/access_token"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
TOKEN = Token(TokenKind.USER, "IGAA-largo")
ME = {
    "user_id": "17841405822304914",
    "username": "mimarca",
    "name": "Mi Marca",
    "profile_picture_url": "https://scontent/a.jpg",
}
ACCOUNT = Asset("a1", "c1", INSTAGRAM, "dueño", INSTAGRAM_ACCOUNT, "17841405822304914")
# Así responde el canje del código: envuelto en `data`.
SHORT = {
    "data": [
        {
            "access_token": "IGAA-corto",
            "user_id": "17841405822304914",
            "permissions": "instagram_business_basic,instagram_business_manage_comments",
        }
    ]
}
_CODES = {ErrorKind.TOKEN_DEAD: 190, ErrorKind.MISSING_PERMISSION: 10, ErrorKind.RATE_LIMITED: 4}


def config(**overrides: object) -> InstagramConfig:
    values: dict[str, object] = {"client_id": "app-ig", "client_secret": "secreto-ig", "api_version": "v24.0"}
    values.update(overrides)
    return InstagramConfig(**values)  # type: ignore[arg-type]


def failure(code: int, message: str = "no") -> HttpResponse:
    return HttpResponse(400, {"error": {"code": code, "message": message}}, "")


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


class InstagramHarness(NetworkHarness):
    def __init__(self) -> None:
        self.transport = FakeTransport(base=BASE)

    @property
    @override
    def spec(self) -> NetworkSpec:
        return INSTAGRAM_SPEC

    @override
    def provider(self) -> Provider:
        return instagram_provider(config(), self.transport)

    @override
    def script_connection(self) -> None:
        self.transport.on("POST", SHORT_TOKEN_URL, SHORT)
        self.transport.on("GET", LONG_TOKEN_URL, {"access_token": "IGAA-largo", "expires_in": 5184000})
        self.transport.on("GET", "me", ME)

    @override
    def error(self, kind: ErrorKind) -> HttpResponse | None:
        code = _CODES.get(kind)
        return failure(code) if code else None


class TestInstagramConLoginPropioCumpleElContrato(ProviderContract):
    @override
    def harness(self) -> NetworkHarness:
        return InstagramHarness()


# ── Login ───────────────────────────────────────────────────────────────────────────────────────


def test_es_otra_red_con_su_propia_app(transport: FakeTransport) -> None:
    provider = instagram_provider(config(), transport)
    assert provider.id == INSTAGRAM
    # Sin mensajes, webhooks ni perfiles ajenos con este login.
    assert provider.capabilities == frozenset(
        {
            Capability.LOGIN,
            Capability.ASSETS,
            Capability.CONTENT,
            Capability.COMMENTS,
            Capability.INSIGHTS,
            Capability.PUBLISHING,
        }
    )
    assert "secreto-ig" not in repr(config())


def test_la_url_de_autorizacion(transport: FakeTransport) -> None:
    oauth = InstagramLogin(config(), transport, FakeClock())
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://api/cb",
        scopes=oauth.default_scopes(Purpose.CONNECT),
        code_challenge="d",
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://www.instagram.com/oauth/authorize?")
    assert query["client_id"] == ["app-ig"]
    assert query["scope"] == [
        "instagram_business_basic,instagram_business_manage_comments,instagram_business_manage_insights"
    ]
    assert "code_challenge" not in query
    assert oauth.default_scopes(Purpose.LOGIN) == ("instagram_business_basic",)


async def test_el_codigo_se_canjea_por_un_token_corto_y_ese_por_uno_largo(transport: FakeTransport) -> None:
    transport.on("POST", SHORT_TOKEN_URL, SHORT)
    transport.on(
        "GET", LONG_TOKEN_URL, {"access_token": "IGAA-largo", "token_type": "bearer", "expires_in": 5184000}
    )
    oauth = InstagramLogin(config(), transport, FakeClock())
    token = await oauth.exchange_code(code="codigo#_", redirect_uri="https://api/cb", code_verifier=None)
    assert (token.access_token, token.expires_at) == ("IGAA-largo", NOW + timedelta(days=60))
    assert token.scopes == frozenset({"instagram_business_basic", "instagram_business_manage_comments"})
    short, long = transport.calls
    # Instagram le agrega `#_` al código en la URL de retorno: no es parte del código.
    assert short.form is not None
    assert (short.form["code"], short.form["client_id"], short.form["client_secret"]) == (
        "codigo",
        "app-ig",
        "secreto-ig",
    )
    assert long.params == {
        "grant_type": "ig_exchange_token",
        "client_secret": "secreto-ig",
        "access_token": "IGAA-corto",
    }


async def test_el_canje_tambien_puede_venir_sin_envolver(transport: FakeTransport) -> None:
    transport.on(
        "POST", SHORT_TOKEN_URL, {"access_token": "IGAA-corto", "permissions": ["instagram_business_basic"]}
    )
    transport.on("GET", LONG_TOKEN_URL, {"access_token": "IGAA-largo"})
    token = await InstagramLogin(config(), transport, FakeClock()).exchange_code(
        code="c", redirect_uri="r", code_verifier=None
    )
    assert token.scopes == frozenset({"instagram_business_basic"})
    # Sin `expires_in`, vale lo que dura un token largo.
    assert token.expires_at == NOW + timedelta(days=60)


@pytest.mark.parametrize(
    ("short", "long", "error", "match"),
    [
        ({"data": [{"user_id": "1"}]}, {}, ProviderError, "token"),
        (SHORT, {}, ProviderError, "token"),
        (
            HttpResponse(
                400, {"error_type": "OAuthException", "code": 400, "error_message": "código usado"}, ""
            ),
            {},
            ProviderError,
            "código usado",
        ),
        (SHORT, failure(190, "token inválido"), TokenRejected, "token inválido"),
    ],
)
async def test_canjes_que_fallan(
    transport: FakeTransport, short: object, long: object, error: type[Exception], match: str
) -> None:
    transport.on("POST", SHORT_TOKEN_URL, short)
    transport.on("GET", LONG_TOKEN_URL, long)
    with pytest.raises(error, match=match):
        await InstagramLogin(config(), transport, FakeClock()).exchange_code(
            code="c", redirect_uri="r", code_verifier=None
        )


async def test_se_renueva_el_mismo_token_y_solo_si_tiene_mas_de_un_dia(transport: FakeTransport) -> None:
    clock = FakeClock()
    oauth = InstagramLogin(config(), transport, clock)
    scopes = frozenset({"instagram_business_basic"})
    fresh = Token(TokenKind.USER, "IGAA-largo", expires_at=clock.now() + timedelta(days=60), scopes=scopes)
    assert not oauth.can_refresh(fresh)
    assert not oauth.can_refresh(Token(TokenKind.USER, "x"))
    clock.advance(timedelta(hours=25))
    assert oauth.can_refresh(fresh)
    transport.on("GET", REFRESH_URL, {"access_token": "IGAA-nuevo", "expires_in": 5184000})
    renewed = await oauth.refresh(fresh)
    # Los permisos se conservan: la renovación no los repite.
    assert (renewed.access_token, renewed.scopes) == ("IGAA-nuevo", scopes)
    assert transport.calls[0].params == {"grant_type": "ig_refresh_token", "access_token": "IGAA-largo"}
    clock.advance(timedelta(days=60))
    assert not oauth.can_refresh(fresh)
    await oauth.revoke(fresh)
    assert len(transport.calls) == 1


async def test_la_cuenta_se_identifica_con_user_id(transport: FakeTransport) -> None:
    # `id` es propio de la app; `user_id` es el de la cuenta, el que va en las rutas y llega en los avisos.
    transport.on("GET", "me", {"data": [{**ME, "id": "9999-de-la-app"}]}, {"id": "9999-de-la-app"})
    identity = await InstagramLogin(config(), transport, FakeClock()).identity(TOKEN)
    assert (identity.provider, identity.external_id, identity.name, identity.avatar_url) == (
        INSTAGRAM,
        "17841405822304914",
        "Mi Marca",
        "https://scontent/a.jpg",
    )
    assert transport.calls[0].params == {
        "fields": "user_id,username,name,profile_picture_url",
        "access_token": "IGAA-largo",
    }
    with pytest.raises(ProviderError, match="id de la cuenta"):
        await InstagramLoginAssets(config(), transport).discover(TOKEN)
    transport.routes.clear()
    transport.on("GET", "me", ME)
    [asset] = await InstagramLoginAssets(config(), transport).discover(TOKEN)
    assert (asset.kind, asset.external_id, asset.metadata, asset.token) == (
        INSTAGRAM_ACCOUNT,
        "17841405822304914",
        {"username": "mimarca"},
        None,
    )


# ── Los adaptadores de Meta, en el servidor de Instagram ────────────────────────────────────────


async def test_publicar_y_leer_usan_el_servidor_de_instagram_y_no_firman(transport: FakeTransport) -> None:
    provider = instagram_provider(config(), transport)
    transport.on("POST", "17841405822304914/media", {"id": "cont-1"})
    transport.on("GET", "cont-1", {"status_code": "FINISHED"})
    transport.on("POST", "17841405822304914/media_publish", {"id": "media-1"})
    transport.on("GET", "media-1", {"permalink": "https://www.instagram.com/p/abc/"})
    draft = Draft("hola", media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/a.jpg"),))
    outcome = await provider.require_publisher().publish(ACCOUNT, TOKEN, draft=draft)
    assert (outcome.status, outcome.post_id) == (PublicationStatus.PUBLISHED, "media-1")
    # Sin app de Meta no hay `appsecret_proof`: solo el token.
    assert all(set(call.params) == {"access_token"} for call in transport.calls if call.method == "POST")

    transport.on("GET", "17841405822304914/media", {"data": [{"id": "media-1", "caption": "hola"}]})
    posts = await provider.require_content().list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=10)
    assert [post.text for post in posts] == ["hola"]


async def test_los_errores_van_a_nombre_de_instagram(transport: FakeTransport) -> None:
    provider = instagram_provider(config(), transport)
    transport.on("GET", "media-1/comments", failure(10, "falta el permiso"))
    with pytest.raises(PermissionMissing) as raised:
        await provider.require_comments().list_comments(ACCOUNT, TOKEN, object_id="media-1")
    assert raised.value.provider == INSTAGRAM
