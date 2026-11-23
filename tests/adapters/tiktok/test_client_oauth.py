from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.tiktok.assets import TikTokAssetDirectory
from omnisocial.adapters.providers.tiktok.client import TikTokClient
from omnisocial.adapters.providers.tiktok.oauth import TikTokOAuth
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import PermissionMissing, ProviderError, TokenRejected
from omnisocial.domain.provider import Capability
from omnisocial.domain.token import Token, TokenKind
from tests.adapters.tiktok.conftest import FakeTikTok, failure, ok
from tests.fakes import NOW, FakeClock

TOKENS = {
    "access_token": "act.1",
    "expires_in": 7200,
    "refresh_token": "rft.1",
    "refresh_expires_in": 15552000,
    "open_id": "oid-1",
    "scope": "user.info.basic,video.list",
    "token_type": "Bearer",
}


async def test_el_sobre_de_datos(fake: FakeTikTok, client: TikTokClient) -> None:
    fake.on("GET", "user/info/", ok({"user": {"open_id": "o"}}))
    assert await client.get("user/info", "tok", fields=("open_id",)) == {"user": {"open_id": "o"}}
    call = fake.calls[0]
    assert call.params == {"fields": "open_id"}
    assert call.headers == {"Authorization": "Bearer tok"}


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("access_token_invalid", TokenRejected),
        ("scope_not_authorized", PermissionMissing),
        ("scope_permission_missed", PermissionMissing),
        ("rate_limit_exceeded", ProviderError),
    ],
)
async def test_errores_de_datos(
    fake: FakeTikTok, client: TikTokClient, code: str, error: type[Exception]
) -> None:
    fake.on("POST", "video/list/", failure(code, "no"), status=401)
    with pytest.raises(error, match="no") as raised:
        await client.query("video/list", "tok", fields=("id",), body={})
    assert getattr(raised.value, "code", None) == code


async def test_una_respuesta_sin_sobre(fake: FakeTikTok, client: TikTokClient) -> None:
    fake.on("GET", "user/info/", HttpResponse(502, None, "<html>bad gateway"))
    with pytest.raises(ProviderError, match="bad gateway"):
        await client.get("user/info", "tok", fields=("open_id",))


async def test_errores_de_oauth(fake: FakeTikTok, client: TikTokClient) -> None:
    fake.on("POST", "oauth/token/", {"error": "invalid_grant", "error_description": "vencido"}, status=400)
    with pytest.raises(TokenRejected, match="vencido"):
        await client.oauth("oauth/token", {})
    fake.routes.clear()
    fake.on("POST", "oauth/token/", {"error": "invalid_request"}, status=400)
    with pytest.raises(ProviderError, match="invalid_request"):
        await client.oauth("oauth/token", {})
    fake.routes.clear()
    fake.on("POST", "oauth/token/", HttpResponse(500, None, ""))
    with pytest.raises(ProviderError, match="HTTP 500"):
        await client.oauth("oauth/token", {})


def test_url_de_autorizacion(client: TikTokClient, clock: FakeClock) -> None:
    oauth = TikTokOAuth(client, clock)
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://api/cb",
        scopes=oauth.default_scopes(Purpose.CONNECT),
        code_challenge=None,
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://www.tiktok.com/v2/auth/authorize/"
    query = parse_qs(parts.query)
    assert query["client_key"] == ["clave"]
    assert query["scope"] == ["user.info.basic,user.info.profile,user.info.stats,video.list"]
    assert query["response_type"] == ["code"]
    assert oauth.default_scopes(Purpose.LOGIN) == ("user.info.basic",)
    assert oauth.supports_pkce is False


async def test_canjear_el_codigo(fake: FakeTikTok, client: TikTokClient, clock: FakeClock) -> None:
    fake.on("POST", "oauth/token/", TOKENS)
    token = await TikTokOAuth(client, clock).exchange_code(
        code="c", redirect_uri="https://api/cb", code_verifier=None
    )
    assert (token.access_token, token.refresh_token) == ("act.1", "rft.1")
    assert token.expires_at == NOW + timedelta(hours=2)
    assert token.scopes == frozenset({"user.info.basic", "video.list"})
    call = fake.calls[0]
    assert call.form == {
        "client_key": "clave",
        "client_secret": "secreto",
        "code": "c",
        "grant_type": "authorization_code",
        "redirect_uri": "https://api/cb",
    }
    assert call.retry_safe


async def test_canje_sin_token(fake: FakeTikTok, client: TikTokClient, clock: FakeClock) -> None:
    fake.on("POST", "oauth/token/", {"open_id": "x"})
    with pytest.raises(ProviderError, match="token"):
        await TikTokOAuth(client, clock).exchange_code(code="c", redirect_uri="r", code_verifier=None)


async def test_renovar_rota_el_refresh_token(
    fake: FakeTikTok, client: TikTokClient, clock: FakeClock
) -> None:
    oauth = TikTokOAuth(client, clock)
    old = Token(TokenKind.USER, "act.1", refresh_token="rft.1")
    fake.on(
        "POST", "oauth/token/", {**TOKENS, "access_token": "act.2", "refresh_token": "rft.2", "scope": ""}
    )
    assert oauth.can_refresh(old)
    fresh = await oauth.refresh(old)
    assert (fresh.access_token, fresh.refresh_token) == ("act.2", "rft.2")
    assert fake.calls[0].form == {
        "client_key": "clave",
        "client_secret": "secreto",
        "grant_type": "refresh_token",
        "refresh_token": "rft.1",
    }
    without = Token(TokenKind.USER, "act")
    assert not oauth.can_refresh(without)
    with pytest.raises(ProviderError, match="refresh"):
        await oauth.refresh(without)


async def test_identidad_y_revocacion(fake: FakeTikTok, client: TikTokClient, clock: FakeClock) -> None:
    oauth = TikTokOAuth(client, clock)
    fake.on(
        "GET", "user/info/", ok({"user": {"open_id": "oid-1", "display_name": "Marca", "avatar_url": "a"}})
    )
    fake.on("POST", "oauth/revoke/", {})
    identity = await oauth.identity(Token(TokenKind.USER, "act"))
    assert (identity.external_id, identity.name, identity.avatar_url) == ("oid-1", "Marca", "a")
    await oauth.revoke(Token(TokenKind.USER, "act"))
    assert fake.calls[1].form == {"client_key": "clave", "client_secret": "secreto", "token": "act"}
    fake.routes.clear()
    fake.on("GET", "user/info/", ok({"user": {}}))
    with pytest.raises(ProviderError, match="open_id"):
        await oauth.identity(Token(TokenKind.USER, "act"))


async def test_la_cuenta_es_el_activo(fake: FakeTikTok, client: TikTokClient) -> None:
    fake.on("GET", "user/info/", ok({"user": {"open_id": "oid-1", "display_name": "Marca"}}))
    [asset] = await TikTokAssetDirectory(client).discover(Token(TokenKind.USER, "act"))
    assert (asset.kind, asset.external_id, asset.name, asset.token) == (
        "tiktok_account",
        "oid-1",
        "Marca",
        None,
    )
    assert asset.capabilities == frozenset({Capability.CONTENT, Capability.INSIGHTS})
    fake.routes.clear()
    fake.on("GET", "user/info/", ok({}))
    with pytest.raises(ProviderError, match="open_id"):
        await TikTokAssetDirectory(client).discover(Token(TokenKind.USER, "act"))
