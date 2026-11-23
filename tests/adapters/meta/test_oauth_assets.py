from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from omnisocial.adapters.providers.meta.assets import MetaAssetDirectory
from omnisocial.adapters.providers.meta.config import (
    CONNECT_SCOPES,
    FACEBOOK_PAGE,
    INSTAGRAM_ACCOUNT,
    LOGIN_SCOPES,
)
from omnisocial.adapters.providers.meta.graph import GraphClient
from omnisocial.adapters.providers.meta.oauth import MetaOAuth
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.provider import Capability
from omnisocial.domain.token import Token, TokenKind
from tests.adapters.meta.conftest import FakeGraph
from tests.fakes import NOW, FakeClock


@pytest.fixture
def oauth(graph: GraphClient, clock: FakeClock) -> MetaOAuth:
    return MetaOAuth(graph, clock)


def test_url_de_autorizacion(oauth: MetaOAuth) -> None:
    url = oauth.authorization_url(
        state="s1", redirect_uri="https://api/cb", scopes=["a", "b"], code_challenge=None
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://www.facebook.com/v24.0/dialog/oauth"
    assert parse_qs(parts.query) == {
        "client_id": ["app"],
        "redirect_uri": ["https://api/cb"],
        "state": ["s1"],
        "scope": ["a,b"],
        "response_type": ["code"],
    }
    assert oauth.default_scopes(Purpose.LOGIN) == LOGIN_SCOPES
    assert oauth.default_scopes(Purpose.CONNECT) == CONNECT_SCOPES
    assert not oauth.supports_pkce


async def test_canje_estira_el_token_y_guarda_los_permisos(fake: FakeGraph, oauth: MetaOAuth) -> None:
    fake.on(
        "GET",
        "oauth/access_token",
        {"access_token": "corto", "expires_in": 3600},
        {"access_token": "largo", "expires_in": 5184000},
    )
    fake.on(
        "GET",
        "me/permissions",
        {
            "data": [
                {"permission": "pages_show_list", "status": "granted"},
                {"permission": "email", "status": "declined"},
            ]
        },
    )
    token = await oauth.exchange_code(code="c", redirect_uri="https://api/cb", code_verifier=None)
    assert token.access_token == "largo"
    assert token.kind is TokenKind.USER
    assert token.expires_at == NOW + timedelta(days=60)
    assert token.scopes == {"pages_show_list"}
    first, second, _ = fake.calls
    assert first.params == {
        "client_id": "app",
        "client_secret": "secreto",
        "redirect_uri": "https://api/cb",
        "code": "c",
    }
    assert second.params["grant_type"] == "fb_exchange_token"
    assert second.params["fb_exchange_token"] == "corto"


async def test_si_no_hay_token_largo_usa_el_corto(fake: FakeGraph, oauth: MetaOAuth) -> None:
    fake.on("GET", "oauth/access_token", {"access_token": "corto", "expires_in": 3600}, {})
    fake.on("GET", "me/permissions", {"data": []})
    token = await oauth.exchange_code(code="c", redirect_uri="r", code_verifier=None)
    assert token.access_token == "corto"
    assert token.expires_at == NOW + timedelta(hours=1)


async def test_canje_sin_token_es_error(fake: FakeGraph, oauth: MetaOAuth) -> None:
    fake.on("GET", "oauth/access_token", {"token_type": "bearer"})
    with pytest.raises(ProviderError, match="no devolvió un token"):
        await oauth.exchange_code(code="c", redirect_uri="r", code_verifier=None)


async def test_identidad(fake: FakeGraph, oauth: MetaOAuth) -> None:
    fake.on(
        "GET",
        "me",
        {"id": "42", "name": "Ana", "email": "ana@ejemplo.com", "picture": {"data": {"url": "https://img"}}},
    )
    identity = await oauth.identity(Token(TokenKind.USER, "t"))
    assert (identity.external_id, identity.name, identity.email, identity.avatar_url) == (
        "42",
        "Ana",
        "ana@ejemplo.com",
        "https://img",
    )
    fake.on("GET", "me", {"name": "sin id"})
    fake.routes[("GET", "me")] = [fake.routes[("GET", "me")][-1]]
    with pytest.raises(ProviderError, match="id"):
        await oauth.identity(Token(TokenKind.USER, "t"))


async def test_meta_no_renueva_y_revoca_por_permisos(fake: FakeGraph, oauth: MetaOAuth) -> None:
    token = Token(TokenKind.USER, "t", expires_at=NOW)
    assert not oauth.can_refresh(token)
    with pytest.raises(ProviderError, match="renovar"):
        await oauth.refresh(token)
    fake.on("DELETE", "me/permissions", {"success": True})
    await oauth.revoke(token)
    assert fake.calls[-1].method == "DELETE"


async def test_debug_token(fake: FakeGraph, oauth: MetaOAuth) -> None:
    fake.on(
        "GET",
        "debug_token",
        {
            "data": {
                "is_valid": True,
                "type": "SYSTEM_USER",
                "app_id": "app",
                "user_id": "9",
                "expires_at": 0,
                "data_access_expires_at": 1795000000,
                "scopes": ["read_insights", 3],
            }
        },
    )
    info = await oauth.debug_token(Token(TokenKind.SYSTEM, "t"))
    assert info.is_valid
    assert info.type == "SYSTEM_USER"
    assert info.expires_at is None
    assert info.data_access_expires_at == datetime.fromtimestamp(1795000000, UTC)
    assert info.scopes == {"read_insights"}
    assert fake.calls[-1].params == {"input_token": "t", "access_token": "app|secreto"}


async def test_descubre_paginas_e_instagram(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on(
        "GET",
        "me/accounts",
        {
            "data": [
                {
                    "id": "p1",
                    "name": "Página 1",
                    "access_token": "tok-p1",
                    "category": "Restaurante",
                    "tasks": ["ANALYZE", "MODERATE"],
                    "instagram_business_account": {
                        "id": "ig1",
                        "username": "pagina1",
                        "profile_picture_url": "https://pic",
                    },
                },
                {"id": "p2", "name": "Página 2"},
                {"name": "sin id"},
            ],
            "paging": {"next": "next:2"},
        },
    )
    fake.on("GET", "next:2", {"data": [{"id": "p3", "access_token": "tok-p3"}]})
    assets = await MetaAssetDirectory(graph).discover(Token(TokenKind.USER, "u"))
    assert [(a.kind, a.external_id, a.parent_external_id) for a in assets] == [
        (FACEBOOK_PAGE, "p1", None),
        (INSTAGRAM_ACCOUNT, "ig1", "p1"),
        (FACEBOOK_PAGE, "p2", None),
        (FACEBOOK_PAGE, "p3", None),
    ]
    page, instagram, no_token, _ = assets
    assert page.token is not None
    assert page.token.access_token == "tok-p1"
    assert page.token.kind is TokenKind.ASSET
    assert page.metadata == {"category": "Restaurante", "tasks": "ANALYZE,MODERATE"}
    assert instagram.token == page.token
    assert instagram.name == "pagina1"
    assert instagram.metadata == {"username": "pagina1", "picture": "https://pic"}
    assert no_token.token is None
    assert Capability.MESSAGING in page.capabilities
