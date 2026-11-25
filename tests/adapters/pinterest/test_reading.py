"""Login, cuenta, pines, tableros y métricas, con una API falsa."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from omnisocial.adapters.providers.pinterest.client import PinterestClient
from omnisocial.adapters.providers.pinterest.config import SANDBOX_BASE, PinterestOptions
from omnisocial.adapters.providers.pinterest.oauth import pinterest_oauth
from omnisocial.adapters.providers.pinterest.reading import (
    PinterestAssetDirectory,
    PinterestContentReader,
    PinterestInsightsReader,
    PinterestLookups,
)
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import PermissionMissing, ProviderError, RateLimited, TokenRejected
from omnisocial.domain.lookup import Choice
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.window import TimeWindow
from omnisocial.testing import FakeTransport
from tests.adapters.pinterest.conftest import (
    ACCOUNT,
    BOARDS,
    SECTIONS,
    TOKEN,
    TOKEN_URL,
    USER,
    config,
    failure,
)
from tests.fakes import NOW, FakeClock


def pin(number: int, created: str, **extra: object) -> dict[str, object]:
    return {"id": f"p{number}", "created_at": created, "description": f"Pin {number}", **extra}


# ── Login ───────────────────────────────────────────────────────────────────────────────────────


async def test_el_login_identifica_a_la_app_por_cabecera_y_rota_la_renovacion(
    transport: FakeTransport, client: PinterestClient
) -> None:
    oauth = pinterest_oauth(client, FakeClock())
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://app.ejemplo.com/cb",
        scopes=("boards:read", "pins:read"),
        code_challenge=None,
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://www.pinterest.com/oauth/?")
    # Los permisos van separados por comas.
    assert (query["scope"], oauth.supports_pkce) == (["boards:read,pins:read"], False)
    assert oauth.default_scopes(Purpose.CONNECT) == ("user_accounts:read", "boards:read", "pins:read")

    transport.on(
        "POST",
        TOKEN_URL,
        {"access_token": "pina-1", "refresh_token": "pinr-1", "expires_in": 2592000, "scope": "boards:read"},
        {"access_token": "pina-2", "refresh_token": "pinr-2", "expires_in": 2592000},
    )
    token = await oauth.exchange_code(
        code="abc", redirect_uri="https://app.ejemplo.com/cb", code_verifier=None
    )
    call = transport.calls[0]
    assert call.headers is not None
    assert call.headers["Authorization"].startswith("Basic ")
    assert call.form is not None
    assert "client_secret" not in call.form
    assert (token.access_token, token.refresh_token) == ("pina-1", "pinr-1")
    assert token.expires_at == NOW + timedelta(days=30)
    renewed = await oauth.refresh(token)
    assert (renewed.access_token, renewed.refresh_token) == ("pina-2", "pinr-2")

    transport.on("GET", "user_account", USER)
    identity = await oauth.identity(token)
    assert (identity.external_id, identity.name) == ("9001", "Mi Tienda")


def test_el_ambiente_de_prueba_tiene_su_propio_canje() -> None:
    assert config(api_base=SANDBOX_BASE).token_url == "https://api-sandbox.pinterest.com/v5/oauth/token"
    assert "secreto" not in repr(config())
    with pytest.raises(ValueError, match="tablero"):
        PinterestOptions(board_id="")


# ── Cuenta y pines ──────────────────────────────────────────────────────────────────────────────


async def test_la_cuenta_es_el_activo(transport: FakeTransport, client: PinterestClient) -> None:
    transport.on("GET", "user_account", USER, {"username": "sin-id"})
    [asset] = await PinterestAssetDirectory(client).discover(TOKEN)
    assert (asset.kind, asset.external_id, asset.name) == ("pinterest_account", "9001", "Mi Tienda")
    assert asset.metadata == {"username": "mitienda", "account_type": "BUSINESS"}
    with pytest.raises(ProviderError, match="id de la cuenta"):
        await PinterestAssetDirectory(client).discover(TOKEN)
    with pytest.raises(ProviderError, match="id de la cuenta"):
        await pinterest_oauth(client, FakeClock()).identity(TOKEN)


async def test_los_pines_se_recorren_por_marca(transport: FakeTransport, client: PinterestClient) -> None:
    first = pin(
        1,
        "2026-11-20T10:00:00Z",
        media={"media_type": "image", "images": {"600x": {"url": "https://i.pinimg.com/600x/p1.jpg"}}},
        pin_metrics={"lifetime_metrics": {"impression": 900, "reaction": 12, "comment": 3}},
    )
    video = pin(2, "2026-10-01T10:00:00", media={"media_type": "video", "cover_image_url": "https://i/c.jpg"})
    old = {"id": "p3", "created_at": "2025-01-01T00:00:00Z", "title": "Viejo"}
    # Una página vacía que igual trae marca: se sigue.
    transport.on(
        "GET",
        "pins",
        {"items": [first, {"sin": "id"}], "bookmark": "m1"},
        {"items": [], "bookmark": "m2"},
        {"items": [video, old], "bookmark": None},
    )
    reader = PinterestContentReader(client)
    posts = await reader.list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=None)
    assert [p.external_id for p in posts] == ["p1", "p2", "p3"]
    assert [call.params.get("bookmark") for call in transport.calls] == [None, "m1", "m2"]
    assert transport.calls[0].params == {"pin_metrics": "true", "page_size": 100}
    one = posts[0]
    assert (one.permalink, one.text, one.media_type, one.media_url) == (
        "https://www.pinterest.com/pin/p1/",
        "Pin 1",
        "image",
        "https://i.pinimg.com/600x/p1.jpg",
    )
    assert (one.like_count, one.comment_count, one.view_count) == (12, 3, 900)
    assert one.created_at == datetime(2026, 11, 20, 10, tzinfo=UTC)
    assert (posts[1].media_url, posts[1].like_count, posts[2].text) == ("https://i/c.jpg", None, "Viejo")
    # Una fecha sin zona es UTC.
    assert posts[1].created_at == datetime(2026, 10, 1, 10, tzinfo=UTC)


async def test_la_ventana_filtra_y_el_limite_corta(transport: FakeTransport, client: PinterestClient) -> None:
    pins = [pin(1, "2026-11-20T10:00:00Z"), pin(2, "2026-06-01T10:00:00Z"), pin(3, "2026-11-10T10:00:00Z")]
    transport.on("GET", "pins", {"items": pins, "bookmark": "sigue"})
    reader = PinterestContentReader(client)
    window = TimeWindow(datetime(2026, 11, 1, tzinfo=UTC), None)
    posts = await reader.list_posts(ACCOUNT, TOKEN, window=window, limit=2)
    # No se corta en el pin viejo: Pinterest no documenta el orden.
    assert [p.external_id for p in posts] == ["p1", "p3"]
    assert len(transport.calls) == 1

    capped = PinterestContentReader(PinterestClient(config(max_pages=2, page_size=10), transport))
    transport.calls.clear()
    await capped.list_posts(
        ACCOUNT, TOKEN, window=TimeWindow(datetime(2027, 1, 1, tzinfo=UTC), None), limit=None
    )
    assert len(transport.calls) == 2


# ── Consultas auxiliares ────────────────────────────────────────────────────────────────────────


async def test_los_tableros_y_sus_secciones(transport: FakeTransport, client: PinterestClient) -> None:
    transport.on("GET", "boards", BOARDS)
    transport.on("GET", "boards/b1/sections", SECTIONS)
    lookups = PinterestLookups(client)
    boards = await lookups.choices(ACCOUNT, TOKEN, lookup="boards", query=None, parent=None)
    assert boards == [
        Choice("b1", "Recetas", detail="Para el finde", data={"privacy": "PUBLIC"}),
        Choice("b2", "Ideas", data={"privacy": "SECRET"}),
    ]
    sections = await lookups.choices(ACCOUNT, TOKEN, lookup="board_sections", query=None, parent="b1")
    assert sections == [Choice("s1", "Postres")]


# ── Métricas ────────────────────────────────────────────────────────────────────────────────────


async def test_metricas_por_dia_y_en_total(transport: FakeTransport, client: PinterestClient) -> None:
    transport.on("GET", "user_account", USER)
    transport.on(
        "GET",
        "user_account/analytics",
        {
            "all": {
                "daily_metrics": [
                    {"date": "2026-11-22", "data_status": "READY", "metrics": {"IMPRESSION": 120, "SAVE": 4}},
                    {"date": "2026-11-23", "data_status": "READY", "metrics": {"IMPRESSION": 80.0}},
                ],
                "summary_metrics": {"IMPRESSION": 200, "SAVE": 4},
            }
        },
    )
    reader = PinterestInsightsReader(client, FakeClock())
    assert reader.api_version == "v5"
    assert reader.catalog.native_for("pinterest_account", CanonicalMetric.IMPRESSIONS, "v5") == "IMPRESSION"
    window = TimeWindow(NOW - timedelta(days=2), NOW)
    wanted = ["follower_count", "IMPRESSION", "SAVE", "no_existe"]
    daily = await reader.read(ACCOUNT, TOKEN, metrics=wanted, period=Period.DAY, window=window)
    assert [(s.name, s.period, [p.value for p in s.points]) for s in daily] == [
        ("follower_count", Period.LIFETIME, [1500.0]),
        ("IMPRESSION", Period.DAY, [120.0, 80.0]),
        ("SAVE", Period.DAY, [4.0]),
    ]
    assert daily[1].points[0].end_time == datetime(2026, 11, 22, tzinfo=UTC)
    params = transport.calls[-1].params
    assert (params["start_date"], params["end_date"], params["metric_types"]) == (
        (NOW - timedelta(days=2)).date().isoformat(),
        NOW.date().isoformat(),
        "IMPRESSION,SAVE",
    )

    total = await reader.read(
        ACCOUNT, TOKEN, metrics=["IMPRESSION"], period=Period.LIFETIME, window=TimeWindow()
    )
    assert [(s.name, s.period, s.points[0].value) for s in total] == [("IMPRESSION", Period.LIFETIME, 200.0)]
    # Sin ventana, los últimos 30 días; y nunca más de los 90 que guarda Pinterest.
    assert transport.calls[-1].params["start_date"] == (NOW - timedelta(days=30)).date().isoformat()
    await reader.read(
        ACCOUNT,
        TOKEN,
        metrics=["IMPRESSION"],
        period=Period.DAY,
        window=TimeWindow(NOW - timedelta(days=400), NOW),
    )
    assert transport.calls[-1].params["start_date"] == (NOW - timedelta(days=89)).date().isoformat()


async def test_sin_datos_no_hay_series(transport: FakeTransport, client: PinterestClient) -> None:
    transport.on("GET", "user_account", {"id": "9001"})
    transport.on("GET", "user_account/analytics", {})
    reader = PinterestInsightsReader(client, FakeClock())
    for period in (Period.DAY, Period.LIFETIME):
        found = await reader.read(
            ACCOUNT, TOKEN, metrics=["follower_count", "IMPRESSION"], period=period, window=TimeWindow()
        )
        assert found == []


# ── Errores ─────────────────────────────────────────────────────────────────────────────────────


async def test_los_errores_se_clasifican(transport: FakeTransport, client: PinterestClient) -> None:
    transport.on(
        "GET",
        "user_account",
        failure(401, 2, "Authentication failed."),
        failure(403, 29, "Not authorized"),
        failure(429, 8, "Rate limit", **{"x-ratelimit-reset": "42"}),
        failure(429, 8, "Rate limit", **{"x-ratelimit-reset": "pronto", "Retry-After": "7"}),
        failure(500, 0, ""),
    )
    with pytest.raises(TokenRejected):
        await client.get("user_account", "t")
    with pytest.raises(PermissionMissing):
        await client.get("user_account", "t")
    with pytest.raises(RateLimited) as limited:
        await client.get("user_account", "t")
    assert limited.value.retry_after == 42.0
    with pytest.raises(RateLimited) as fallback:
        await client.get("user_account", "t")
    assert fallback.value.retry_after == 7.0
    with pytest.raises(ProviderError, match="HTTP 500"):
        await client.get("user_account", "t")
