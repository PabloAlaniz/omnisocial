"""El OAuth estándar, armado desde la descripción de una red."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.application.ports import IdentityReader
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ErrorKind, ProviderError, QuotaExhausted, RateLimited, TokenRejected
from omnisocial.domain.identity import Identity
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.spec import ErrorTable, NetworkSpec, OAuthSpec
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport
from tests.fakes import NOW, FakeClock

RED = ProviderId("red")
TOKEN_URL = "https://red.ejemplo/token"
REVOKE_URL = "https://red.ejemplo/revoke"


class Quien(IdentityReader):
    @override
    async def identity(self, token: Token) -> Identity:
        return Identity(RED, "u1", name=token.access_token)


def network(**oauth: object) -> NetworkSpec:
    values: dict[str, object] = {"authorize_url": "https://red.ejemplo/authorize", "token_url": TOKEN_URL}
    values.update(oauth)
    return NetworkSpec(
        id=RED,
        name="Red",
        capabilities=frozenset({Capability.LOGIN}),
        errors=ErrorTable(codes={"sin_credito": ErrorKind.QUOTA_EXHAUSTED}),
        oauth=OAuthSpec(**values),  # type: ignore[arg-type]
    )


def client(transport: FakeTransport, **oauth: object) -> StandardOAuth:
    app = OAuthApp("app", "secreto", scopes={Purpose.LOGIN: ("perfil",), Purpose.CONNECT: ("perfil", "leer")})
    return StandardOAuth(network(**oauth), app, transport=transport, clock=FakeClock(), identity=Quien())


def test_la_url_con_pkce_y_parametros_fijos() -> None:
    oauth = client(FakeTransport(), authorize_params={"access_type": "offline"})
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://api/cb",
        scopes=oauth.default_scopes(Purpose.CONNECT),
        code_challenge="d",
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://red.ejemplo/authorize?")
    assert query == {
        "client_id": ["app"],
        "scope": ["perfil leer"],
        "response_type": ["code"],
        "redirect_uri": ["https://api/cb"],
        "state": ["s"],
        "access_type": ["offline"],
        "code_challenge": ["d"],
        "code_challenge_method": ["S256"],
    }
    assert oauth.supports_pkce
    assert oauth.default_scopes(Purpose.LOGIN) == ("perfil",)


def test_sin_pkce_no_manda_el_desafio() -> None:
    oauth = client(FakeTransport(), pkce=False, client_id_param="client_key", scope_separator=",")
    url = oauth.authorization_url(state="s", redirect_uri="r", scopes=("a", "b"), code_challenge="d")
    query = parse_qs(urlsplit(url).query)
    assert "code_challenge" not in query
    assert (query["client_key"], query["scope"]) == (["app"], ["a,b"])


def test_no_se_arma_sin_la_descripcion_del_oauth() -> None:
    bare = NetworkSpec(id=RED, name="Red", capabilities=frozenset({Capability.LOGIN}))
    with pytest.raises(ValueError, match="OAuth"):
        StandardOAuth(
            bare, OAuthApp("a", "s"), transport=FakeTransport(), clock=FakeClock(), identity=Quien()
        )


async def test_canjear_el_codigo_con_su_verificador() -> None:
    transport = FakeTransport()
    transport.on(
        "POST",
        TOKEN_URL,
        {"access_token": "a1", "refresh_token": "r1", "expires_in": "3600", "scope": "perfil leer"},
    )
    oauth = client(transport)
    token = await oauth.exchange_code(code="c", redirect_uri="https://api/cb", code_verifier="v")
    assert (token.kind, token.access_token, token.refresh_token) == (TokenKind.USER, "a1", "r1")
    assert token.expires_at == NOW + timedelta(hours=1)
    assert token.scopes == frozenset({"perfil", "leer"})
    call = transport.calls[0]
    assert call.form == {
        "client_id": "app",
        "client_secret": "secreto",
        "grant_type": "authorization_code",
        "code": "c",
        "redirect_uri": "https://api/cb",
        "code_verifier": "v",
    }
    assert call.retry_safe
    assert (await oauth.identity(token)).name == "a1"


async def test_un_token_sin_vencimiento_ni_permisos() -> None:
    transport = FakeTransport()
    transport.on("POST", TOKEN_URL, {"access_token": "a1", "expires_in": True})
    token = await client(transport).exchange_code(code="c", redirect_uri="r", code_verifier=None)
    assert (token.expires_at, token.scopes, token.refresh_token) == (None, frozenset(), None)
    assert "code_verifier" not in (transport.calls[0].form or {})


async def test_renovar_conserva_lo_que_la_red_no_repite() -> None:
    """Hay redes que no vuelven a mandar el token de renovación ni los permisos."""
    transport = FakeTransport()
    transport.on("POST", TOKEN_URL, {"access_token": "a2", "expires_in": 60})
    oauth = client(transport)
    old = Token(TokenKind.USER, "a1", refresh_token="r1", scopes=frozenset({"perfil"}))
    assert oauth.can_refresh(old)
    fresh = await oauth.refresh(old)
    assert (fresh.access_token, fresh.refresh_token, fresh.scopes) == ("a2", "r1", frozenset({"perfil"}))
    assert transport.calls[0].form == {
        "client_id": "app",
        "client_secret": "secreto",
        "grant_type": "refresh_token",
        "refresh_token": "r1",
    }


async def test_renovar_con_rotacion_guarda_el_nuevo() -> None:
    transport = FakeTransport()
    transport.on("POST", TOKEN_URL, {"access_token": "a2", "refresh_token": "r2"})
    fresh = await client(transport).refresh(Token(TokenKind.USER, "a1", refresh_token="r1"))
    assert fresh.refresh_token == "r2"


async def test_sin_token_de_renovacion_no_se_renueva() -> None:
    oauth = client(FakeTransport())
    bare = Token(TokenKind.USER, "a1")
    assert not oauth.can_refresh(bare)
    with pytest.raises(ProviderError, match="refresh"):
        await oauth.refresh(bare)


async def test_revocar_solo_si_la_red_lo_ofrece() -> None:
    transport = FakeTransport()
    await client(transport).revoke(Token(TokenKind.USER, "a1"))
    assert transport.calls == []
    transport.on("POST", REVOKE_URL, {})
    await client(transport, revoke_url=REVOKE_URL).revoke(Token(TokenKind.USER, "a1"))
    assert transport.calls[0].form == {"client_id": "app", "client_secret": "secreto", "token": "a1"}


@pytest.mark.parametrize(
    ("response", "error", "match"),
    [
        (
            HttpResponse(400, {"error": "invalid_grant", "error_description": "vencido"}, ""),
            TokenRejected,
            "vencido",
        ),
        (HttpResponse(400, {"error": "sin_credito"}, ""), QuotaExhausted, "sin_credito"),
        (HttpResponse(400, {"error": "invalid_request"}, ""), ProviderError, "invalid_request"),
        (HttpResponse(429, None, "despacio", {"Retry-After": "12"}), RateLimited, "despacio"),
        (HttpResponse(500, None, ""), ProviderError, "HTTP 500"),
        (HttpResponse(200, None, "<html>"), ProviderError, "html"),
        (HttpResponse(200, {"otra": "cosa"}, ""), ProviderError, "no devolvió un token"),
    ],
)
async def test_errores(response: HttpResponse, error: type[Exception], match: str) -> None:
    transport = FakeTransport()
    transport.on("POST", TOKEN_URL, response)
    with pytest.raises(error, match=match) as raised:
        await client(transport).exchange_code(code="c", redirect_uri="r", code_verifier=None)
    if isinstance(raised.value, RateLimited):
        assert raised.value.retry_after == 12.0


async def test_la_app_se_puede_identificar_por_cabecera() -> None:
    transport = FakeTransport()
    transport.on("POST", TOKEN_URL, {"access_token": "a1"})
    transport.on("POST", REVOKE_URL, {})
    oauth = client(transport, client_auth_basic=True, revoke_url=REVOKE_URL)
    await oauth.exchange_code(code="c", redirect_uri="r", code_verifier="v")
    call = transport.calls[0]
    # app:secreto en Base64. El secreto no va en el cuerpo.
    assert call.headers == {"Authorization": "Basic YXBwOnNlY3JldG8="}
    assert call.form == {
        "client_id": "app",
        "grant_type": "authorization_code",
        "code": "c",
        "redirect_uri": "r",
        "code_verifier": "v",
    }
    await oauth.revoke(Token(TokenKind.USER, "a1"))
    assert transport.calls[1].headers == {"Authorization": "Basic YXBwOnNlY3JldG8="}
    assert transport.calls[1].form == {"client_id": "app", "token": "a1"}
