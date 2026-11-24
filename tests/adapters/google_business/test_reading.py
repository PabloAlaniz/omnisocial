"""Login, sedes, novedades, reseñas y métricas, con una API falsa."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, parse_qsl, urlsplit

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.google_business.client import GoogleBusinessClient
from omnisocial.adapters.providers.google_business.oauth import google_business_oauth
from omnisocial.adapters.providers.google_business.reading import (
    GoogleBusinessAssetDirectory,
    GoogleBusinessContentReader,
    GoogleBusinessInsightsReader,
    GoogleBusinessReviews,
)
from omnisocial.domain.content import CommentAction
from omnisocial.domain.errors import PermissionMissing, ProviderError, RateLimited, TokenRejected
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.window import TimeWindow
from omnisocial.testing import FakeTransport
from tests.adapters.google_business.conftest import (
    ACCOUNT_LIST,
    ACCOUNTS,
    LOCATION,
    LOCATION_LIST,
    LOCATION_NAME,
    LOCATIONS,
    METRICS,
    PERSON,
    POSTS,
    REVIEWS,
    TOKEN,
    TOKEN_URL,
    USERINFO_URL,
    config,
    failure,
)
from tests.fakes import NOW, FakeClock

REVIEW = f"{LOCATION_NAME}/reviews/r1"


def local_post(number: int, created: str, **extra: object) -> dict[str, object]:
    return {
        "name": f"{LOCATION_NAME}/localPosts/{number}",
        "summary": f"Novedad {number}",
        "createTime": created,
        "topicType": "STANDARD",
        "searchUrl": f"https://local.google.com/place?id=1&lpsid={number}",
        **extra,
    }


def series(name: str, *values: tuple[int, str | None]) -> dict[str, object]:
    dated = [
        {"date": {"year": 2026, "month": 11, "day": day}, **({"value": value} if value is not None else {})}
        for day, value in values
    ]
    return {"dailyMetric": name, "timeSeries": {"datedValues": dated}}


# ── Login y sedes ───────────────────────────────────────────────────────────────────────────────


async def test_el_login_pide_un_token_que_se_renueva(
    transport: FakeTransport, client: GoogleBusinessClient
) -> None:
    oauth = google_business_oauth(client, FakeClock())
    url = oauth.authorization_url(
        state="s", redirect_uri="https://app.ejemplo.com/cb", scopes=("openid",), code_challenge="reto"
    )
    query = parse_qs(urlsplit(url).query)
    assert (query["access_type"], query["prompt"], query["code_challenge"]) == (
        ["offline"],
        ["consent"],
        ["reto"],
    )
    transport.on("POST", TOKEN_URL, {"access_token": "ya29-1", "refresh_token": "1//r", "expires_in": 3599})
    transport.on("GET", USERINFO_URL, PERSON, {"name": "sin id"})
    token = await oauth.exchange_code(
        code="abc", redirect_uri="https://app.ejemplo.com/cb", code_verifier="v"
    )
    assert (token.refresh_token, token.expires_at) == ("1//r", NOW + timedelta(seconds=3599))
    identity = await oauth.identity(token)
    assert (identity.external_id, identity.name, identity.email) == ("1099", "Ana Pérez", "ana@ejemplo.com")
    with pytest.raises(ProviderError, match="id de la persona"):
        await oauth.identity(token)
    assert "secreto" not in repr(config())


async def test_las_sedes_de_todas_las_cuentas(transport: FakeTransport, client: GoogleBusinessClient) -> None:
    group = {"name": "accounts/222", "type": "LOCATION_GROUP"}
    transport.on("GET", ACCOUNTS, {"accounts": [*ACCOUNT_LIST["accounts"], group], "nextPageToken": "p2"}, {})
    transport.on("GET", LOCATIONS, {**LOCATION_LIST, "nextPageToken": "l2"}, {"locations": []})
    # La misma sede se ve desde las dos cuentas: queda una vez.
    transport.on(
        "GET",
        LOCATIONS.replace("111", "222"),
        {"locations": [{"name": "locations/789", "title": "Sucursal"}]},
    )
    assets = await GoogleBusinessAssetDirectory(client).discover(TOKEN)
    assert [(a.external_id, a.name, a.parent_external_id) for a in assets] == [
        ("accounts/111/locations/456", "Café Central", "accounts/111"),
        ("accounts/222/locations/789", "Sucursal", "accounts/222"),
    ]
    assert assets[0].metadata == {
        "maps_uri": "https://maps.google.com/?cid=1",
        "place_id": "ChIJ1",
        "website": "https://cafecentral.ejemplo.com",
    }
    locations = [call for call in transport.calls if call.path == LOCATIONS]
    assert locations[0].params == {
        "readMask": "name,title,storefrontAddress,websiteUri,metadata",
        "pageSize": 100,
    }
    assert locations[1].params["pageToken"] == "l2"
    assert transport.calls[0].headers == {"Authorization": "Bearer ya29-acceso"}


# ── Novedades ───────────────────────────────────────────────────────────────────────────────────


async def test_las_novedades_de_la_sede(transport: FakeTransport, client: GoogleBusinessClient) -> None:
    photo = local_post(
        1, "2026-11-20T10:00:00Z", media=[{"mediaFormat": "PHOTO", "googleUrl": "https://lh3/f1"}]
    )
    transport.on(
        "GET",
        POSTS,
        {"localPosts": [photo, {"summary": "sin nombre"}], "nextPageToken": "p2"},
        {"localPosts": [local_post(2, "2026-06-01T10:00:00Z"), local_post(3, "2026-11-10T10:00:00.5Z")]},
    )
    reader = GoogleBusinessContentReader(client)
    window = TimeWindow(datetime(2026, 11, 1, tzinfo=UTC), None)
    posts = await reader.list_posts(LOCATION, TOKEN, window=window, limit=None)
    # No se corta en la novedad vieja: Google no documenta el orden.
    assert [p.external_id.rsplit("/", 1)[-1] for p in posts] == ["1", "3"]
    first = posts[0]
    assert (first.text, first.media_type, first.media_url, first.created_at) == (
        "Novedad 1",
        "STANDARD",
        "https://lh3/f1",
        datetime(2026, 11, 20, 10, tzinfo=UTC),
    )
    assert first.permalink == "https://local.google.com/place?id=1&lpsid=1"
    assert [call.params.get("pageToken") for call in transport.calls] == [None, "p2"]
    transport.calls.clear()
    assert len(await reader.list_posts(LOCATION, TOKEN, window=TimeWindow(), limit=1)) == 1
    assert len(transport.calls) == 1


# ── Reseñas ─────────────────────────────────────────────────────────────────────────────────────


async def test_las_resenas_con_sus_estrellas_y_su_respuesta(
    transport: FakeTransport, client: GoogleBusinessClient
) -> None:
    answered = {
        "name": REVIEW,
        "reviewId": "r1",
        "reviewer": {"displayName": "Beto"},
        "starRating": "FOUR",
        "comment": "Muy rico el café",
        "createTime": "2026-11-18T12:00:00Z",
        "reviewReply": {"comment": "¡Gracias, Beto!", "updateTime": "2026-11-19T09:00:00Z"},
    }
    anonymous = {
        "name": f"{LOCATION_NAME}/reviews/r2",
        "reviewer": {"displayName": "Un usuario", "isAnonymous": True},
        "starRating": "STAR_RATING_UNSPECIFIED",
    }
    transport.on(
        "GET",
        REVIEWS,
        {"reviews": [answered, {"comment": "sin nombre"}], "nextPageToken": "p2"},
        {"reviews": [anonymous]},
    )
    gateway = GoogleBusinessReviews(client)
    first, second = await gateway.list_comments(LOCATION, TOKEN, object_id="no se usa")
    assert (first.external_id, first.object_external_id, first.rating, first.author_name) == (
        REVIEW,
        LOCATION_NAME,
        4,
        "Beto",
    )
    [reply] = first.replies
    assert (reply.external_id, reply.object_external_id, reply.text, reply.author_name) == (
        f"{REVIEW}/reply",
        REVIEW,
        "¡Gracias, Beto!",
        "Café Central",
    )
    assert (second.rating, second.author_name, second.text, second.replies) == (None, None, None, ())
    assert transport.calls[0].params == {"pageSize": 50}


async def test_responder_una_resena_y_borrar_la_respuesta(
    transport: FakeTransport, client: GoogleBusinessClient
) -> None:
    reply_url = f"https://mybusiness.googleapis.com/v4/{REVIEW}/reply"
    transport.on("PUT", reply_url, {"comment": "¡Gracias!"})
    transport.on("DELETE", reply_url, {})
    gateway = GoogleBusinessReviews(client)
    assert await gateway.reply(LOCATION, TOKEN, comment_id=REVIEW, text="¡Gracias!") == f"{REVIEW}/reply"
    assert (transport.calls[0].method, transport.calls[0].json) == ("PUT", {"comment": "¡Gracias!"})
    # Se puede borrar con el id de la reseña o con el de la respuesta.
    await gateway.delete(LOCATION, TOKEN, comment_id=REVIEW)
    await gateway.delete(LOCATION, TOKEN, comment_id=f"{REVIEW}/reply")
    assert [call.path for call in transport.calls[1:]] == [reply_url, reply_url]
    with pytest.raises(ProviderError, match="4096 bytes") as long:
        await gateway.reply(LOCATION, TOKEN, comment_id=REVIEW, text="ñ" * 2049)
    assert long.value.kind.value == "invalid_request"
    assert {action for action in CommentAction if gateway.supports(LOCATION, action)} == {
        CommentAction.REPLY,
        CommentAction.DELETE,
    }
    with pytest.raises(ProviderError, match="ocultar"):
        await gateway.set_hidden(LOCATION, TOKEN, comment_id=REVIEW, hidden=True)
    with pytest.raises(ProviderError, match="like"):
        await gateway.like(LOCATION, TOKEN, comment_id=REVIEW)


# ── Métricas ────────────────────────────────────────────────────────────────────────────────────


async def test_las_impresiones_se_suman_y_un_cero_no_viene(
    transport: FakeTransport, client: GoogleBusinessClient
) -> None:
    transport.on(
        "GET",
        METRICS,
        {
            "multiDailyMetricTimeSeries": [
                {
                    "dailyMetricTimeSeries": [
                        series("BUSINESS_IMPRESSIONS_DESKTOP_MAPS", (22, "10"), (23, None)),
                        series("BUSINESS_IMPRESSIONS_MOBILE_SEARCH", (22, "5"), (23, "7")),
                        series("CALL_CLICKS", (22, "3"), (23, "raro")),
                        {"timeSeries": {"datedValues": []}},
                        series("WEBSITE_CLICKS", (22, "1")) | {"timeSeries": {"datedValues": [{"date": {}}]}},
                    ]
                }
            ]
        },
    )
    reader = GoogleBusinessInsightsReader(client, FakeClock())
    assert reader.api_version == "v1"
    native = reader.catalog.native_for("google_business_location", CanonicalMetric.IMPRESSIONS, "v1")
    assert native == "BUSINESS_IMPRESSIONS"
    window = TimeWindow(datetime(2026, 11, 22, tzinfo=UTC), datetime(2026, 11, 23, tzinfo=UTC))
    wanted = ["BUSINESS_IMPRESSIONS", "CALL_CLICKS", "WEBSITE_CLICKS", "no_existe"]
    daily = await reader.read(LOCATION, TOKEN, metrics=wanted, period=Period.DAY, window=window)
    assert [(s.name, [p.value for p in s.points]) for s in daily] == [
        ("BUSINESS_IMPRESSIONS", [15.0, 7.0]),
        ("CALL_CLICKS", [3.0, 0.0]),
    ]
    assert daily[0].points[0].end_time == datetime(2026, 11, 22, tzinfo=UTC)
    query = parse_qsl(urlsplit(transport.calls[0].path).query)
    assert [value for key, value in query if key == "dailyMetrics"] == [
        "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
        "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
        "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
        "CALL_CLICKS",
        "WEBSITE_CLICKS",
    ]
    assert dict(query)["dailyRange.start_date.day"] == "22"
    assert (dict(query)["dailyRange.end_date.year"], dict(query)["dailyRange.end_date.day"]) == ("2026", "23")

    total = await reader.read(
        LOCATION, TOKEN, metrics=["CALL_CLICKS"], period=Period.LIFETIME, window=TimeWindow()
    )
    assert [(s.name, s.period, s.points[0].value) for s in total] == [("CALL_CLICKS", Period.LIFETIME, 3.0)]
    # Sin ventana, los últimos 30 días.
    since = NOW - timedelta(days=30)
    assert dict(parse_qsl(urlsplit(transport.calls[-1].path).query))["dailyRange.start_date.day"] == str(
        since.day
    )
    assert await reader.read(LOCATION, TOKEN, metrics=["no_existe"], period=Period.DAY, window=window) == []


# ── Errores ─────────────────────────────────────────────────────────────────────────────────────


async def test_los_errores_se_clasifican_por_el_motivo(
    transport: FakeTransport, client: GoogleBusinessClient
) -> None:
    transport.on(
        "GET",
        ACCOUNTS,
        failure(401, "UNAUTHENTICATED"),
        failure(403, "PERMISSION_DENIED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"),
        failure(403, "PERMISSION_DENIED", "OTRO_MOTIVO"),
        failure(429, "RESOURCE_EXHAUSTED"),
        HttpResponse(500, None, ""),
    )
    with pytest.raises(TokenRejected):
        await client.get(ACCOUNTS, "t")
    with pytest.raises(PermissionMissing):
        await client.get(ACCOUNTS, "t")
    # La cuenta no administra esa sede: no es un permiso faltante.
    with pytest.raises(ProviderError) as denied:
        await client.get(ACCOUNTS, "t")
    assert (denied.value.kind.value, denied.value.code) == ("unknown", "PERMISSION_DENIED")
    with pytest.raises(RateLimited):
        await client.get(ACCOUNTS, "t")
    with pytest.raises(ProviderError, match="HTTP 500"):
        await client.get(ACCOUNTS, "t")
