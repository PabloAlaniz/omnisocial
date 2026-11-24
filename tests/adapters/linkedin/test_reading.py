"""Login, activos, publicaciones, comentarios y métricas, con una API falsa."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.linkedin.assets import LinkedInAssetDirectory
from omnisocial.adapters.providers.linkedin.client import LinkedInClient
from omnisocial.adapters.providers.linkedin.comments import LinkedInCommentGateway
from omnisocial.adapters.providers.linkedin.config import (
    LINKEDIN_MEMBER,
    LINKEDIN_ORGANIZATION,
    ORGANIZATION_SCOPES,
    PUBLISH_SCOPES,
)
from omnisocial.adapters.providers.linkedin.content import LinkedInContentReader
from omnisocial.adapters.providers.linkedin.insights import LinkedInInsightsReader
from omnisocial.adapters.providers.linkedin.oauth import linkedin_oauth
from omnisocial.adapters.providers.linkedin.text import escape, plain
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.content import CommentAction
from omnisocial.domain.errors import (
    ErrorKind,
    PermissionMissing,
    ProviderError,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.window import TimeWindow
from omnisocial.testing import FakeTransport
from tests.adapters.linkedin.conftest import (
    ACLS,
    ORGANIZATION,
    ORGANIZATIONS,
    PERSON,
    TOKEN,
    TOKEN_URL,
    USERINFO,
    config,
    failure,
)
from tests.fakes import NOW, FakeClock

ORG = "urn%3Ali%3Aorganization%3A5515715"
POST = "urn:li:share:7001"
COMMENT = "urn:li:comment:(urn:li:activity:9001,6636)"


# ── Configuración, cliente y texto ──────────────────────────────────────────────────────────────


def test_la_version_es_obligatoria_y_con_su_forma() -> None:
    with pytest.raises(ValueError, match="AAAAMM"):
        config(api_version="v2")
    assert "secreto" not in repr(config())


async def test_cada_llamada_lleva_la_version_y_el_protocolo(
    transport: FakeTransport, client: LinkedInClient
) -> None:
    transport.on("GET", "organizations/1", {"localizedName": "X"})
    await client.get("organizations/1", "tok")
    assert transport.calls[0].headers == {
        "Authorization": "Bearer tok",
        "LinkedIn-Version": "202611",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    # La URL va armada a mano: nada en `params` que un cliente HTTP pueda codificar de más.
    assert transport.calls[0].params == {}


@pytest.mark.parametrize(
    ("response", "error", "kind"),
    [
        (failure(401, message="The token used in the request has expired"), TokenRejected, None),
        (failure(403, "ACCESS_DENIED"), PermissionMissing, ErrorKind.MISSING_PERMISSION),
        # Las respuestas viejas no traen `code`: queda el número.
        (
            HttpResponse(403, {"status": 403, "serviceErrorCode": 100, "message": "no"}, ""),
            PermissionMissing,
            ErrorKind.MISSING_PERMISSION,
        ),
        (failure(429, "TOO_MANY_REQUESTS"), RateLimited, ErrorKind.RATE_LIMITED),
        (failure(422, "UNPROCESSABLE_ENTITY"), ProviderError, ErrorKind.INVALID_REQUEST),
        (failure(400, "VERSION_MISSING"), ProviderError, ErrorKind.INVALID_REQUEST),
        # Un 403 sin código conocido no invalida la conexión.
        (failure(403), ProviderError, ErrorKind.UNKNOWN),
        # La versión fijada fue retirada: es un problema de configuración, no del token.
        (
            failure(426, "NONEXISTENT_VERSION", "Requested version 202401 is not active"),
            ProviderError,
            ErrorKind.UNKNOWN,
        ),
        (HttpResponse(503, None, "ups"), ProviderError, ErrorKind.TRANSIENT),
    ],
)
async def test_errores(
    transport: FakeTransport,
    client: LinkedInClient,
    response: HttpResponse,
    error: type[Exception],
    kind: ErrorKind | None,
) -> None:
    transport.on("GET", "organizations/1", response)
    with pytest.raises(error) as raised:
        await client.get("organizations/1", "tok")
    assert type(raised.value) is error
    assert getattr(raised.value, "kind", None) is kind


def test_el_texto_se_escapa_y_los_hashtags_siguen_siendo_hashtags() -> None:
    assert escape("Hola (mundo) *ya* a_b #novedad @marca [x] {y} <z> a|b ~c \\d") == (
        r"Hola \(mundo\) \*ya\* a\_b #novedad \@marca \[x\] \{y\} \<z\> a\|b \~c \\d"
    )
    assert plain(escape("Hola (mundo) a_b ~c \\d")) == "Hola (mundo) a_b ~c \\d"
    # Como lo devuelve LinkedIn al leer.
    assert plain(r"Lanzamos {hashtag|\#|novedad} con @[Mi Empresa](urn:li:organization:1) \(hoy\)") == (
        "Lanzamos #novedad con @Mi Empresa (hoy)"
    )


# ── Login y activos ─────────────────────────────────────────────────────────────────────────────


def test_la_url_de_autorizacion(client: LinkedInClient) -> None:
    oauth = linkedin_oauth(client, FakeClock())
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://api/cb",
        scopes=oauth.default_scopes(Purpose.CONNECT),
        code_challenge="d",
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert query["scope"] == ["openid profile email"]
    # Para apps web LinkedIn no usa PKCE.
    assert "code_challenge" not in query
    assert not oauth.supports_pkce
    assert PUBLISH_SCOPES == ("w_member_social",)
    assert "w_organization_social_feed" in ORGANIZATION_SCOPES


async def test_el_token_dura_60_dias_y_puede_no_tener_renovacion(
    transport: FakeTransport, client: LinkedInClient
) -> None:
    transport.on("POST", TOKEN_URL, {"access_token": "AQV-acceso", "expires_in": 5184000})
    oauth = linkedin_oauth(client, FakeClock())
    token = await oauth.exchange_code(code="c", redirect_uri="https://api/cb", code_verifier=None)
    assert token.expires_at == datetime(2027, 1, 22, 12, tzinfo=UTC)
    # Sin token de renovación (solo lo reciben las apps aprobadas), la conexión vence sola.
    assert not oauth.can_refresh(token)
    await oauth.revoke(token)
    assert len(transport.calls) == 1


async def test_la_identidad_sale_de_openid(transport: FakeTransport, client: LinkedInClient) -> None:
    transport.on("GET", USERINFO, PERSON, {"name": "Sin id"})
    oauth = linkedin_oauth(client, FakeClock())
    identity = await oauth.identity(TOKEN)
    assert (identity.external_id, identity.name, identity.email, identity.avatar_url) == (
        "abc123",
        "Ana Pérez",
        "ana@ejemplo.com",
        "https://media/ana",
    )
    # No es parte de la API con versión.
    assert transport.calls[0].headers == {"Authorization": "Bearer AQV-acceso"}
    with pytest.raises(ProviderError, match="id de la persona"):
        await oauth.identity(TOKEN)


async def test_el_perfil_y_las_paginas_que_administra(
    transport: FakeTransport, client: LinkedInClient
) -> None:
    transport.on("GET", USERINFO, PERSON)
    second = {"elements": [{"organizationTarget": "urn:li:organization:42"}, {"organization": "otra-cosa"}]}
    first = {**ACLS, "paging": {"links": [{"rel": "next", "href": "/rest/organizationAcls?start=50"}]}}
    transport.on("GET", "organizationAcls", first, second)
    transport.on("GET", "organizations", ORGANIZATIONS)
    member, company, unnamed = await LinkedInAssetDirectory(client).discover(TOKEN)
    assert (member.kind, member.external_id, member.name) == (LINKEDIN_MEMBER, "abc123", "Ana Pérez")
    assert (company.kind, company.external_id, company.name, company.metadata) == (
        LINKEDIN_ORGANIZATION,
        "5515715",
        "Mi Empresa",
        {"vanity_name": "mi-empresa"},
    )
    assert (unnamed.external_id, unnamed.name) == ("42", None)
    paths = [call.path for call in transport.calls]
    assert paths[1] == "organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED&count=50&start=0"
    assert paths[2].endswith("&count=50&start=50")
    # `List(...)` va sin codificar: codificado, LinkedIn no lo entiende.
    assert paths[3] == "organizations?ids=List(5515715,42)"
    assert transport.calls[1].headers is not None
    assert transport.calls[1].headers["X-RestLi-Method"] == "FINDER"


async def test_sin_la_api_de_paginas_queda_el_perfil(
    transport: FakeTransport, client: LinkedInClient
) -> None:
    transport.on("GET", USERINFO, PERSON)
    transport.on("GET", "organizationAcls", failure(403, "ACCESS_DENIED"))
    assets = await LinkedInAssetDirectory(client).discover(TOKEN)
    assert [asset.kind for asset in assets] == [LINKEDIN_MEMBER]
    transport.routes.clear()
    transport.on("GET", USERINFO, PERSON)
    transport.on("GET", "organizationAcls", {"elements": []})
    assert len(await LinkedInAssetDirectory(client).discover(TOKEN)) == 1


# ── Publicaciones ───────────────────────────────────────────────────────────────────────────────


def _post(number: int, day: int, **extra: object) -> dict[str, object]:
    created = int(datetime(2026, 11, day, 10, tzinfo=UTC).timestamp() * 1000)
    return {"id": f"urn:li:share:{number}", "commentary": f"Post {number}", "createdAt": created, **extra}


async def test_las_publicaciones_se_piden_por_fecha_de_creacion(
    transport: FakeTransport, client: LinkedInClient
) -> None:
    page = {
        "elements": [
            _post(3, 22),
            _post(2, 20, commentary=r"Lanzamos {hashtag|\#|novedad} \(hoy\)", content={"multiImage": {}}),
            _post(1, 10),
            _post(0, 1),
        ]
    }
    transport.on("GET", "posts", page)
    window = TimeWindow(datetime(2026, 11, 15, tzinfo=UTC), datetime(2026, 11, 21, tzinfo=UTC))
    posts = await LinkedInContentReader(client).list_posts(ORGANIZATION, TOKEN, window=window, limit=None)
    assert transport.calls[0].path == f"posts?author={ORG}&q=author&sortBy=CREATED&count=50&start=0"
    [post] = posts
    assert (post.external_id, post.text, post.media_type) == (
        "urn:li:share:2",
        "Lanzamos #novedad (hoy)",
        "multiImage",
    )
    assert post.permalink == "https://www.linkedin.com/feed/update/urn:li:share:2/"
    assert post.created_at == datetime(2026, 11, 20, 10, tzinfo=UTC)
    # Los contadores están en otra API: acá no vienen, y eso no es cero.
    assert (post.like_count, post.comment_count) == (None, None)


async def test_el_tope_de_publicaciones(transport: FakeTransport, client: LinkedInClient) -> None:
    transport.on("GET", "posts", {"elements": [_post(3, 22), _post(2, 20)]})
    posts = await LinkedInContentReader(client).list_posts(ORGANIZATION, TOKEN, window=TimeWindow(), limit=1)
    assert [post.external_id for post in posts] == ["urn:li:share:3"]


# ── Comentarios ─────────────────────────────────────────────────────────────────────────────────


async def test_leer_comentarios(transport: FakeTransport, client: LinkedInClient) -> None:
    node = {
        "commentUrn": COMMENT,
        "actor": "urn:li:person:xyz",
        "message": {"text": "¡Felicitaciones!"},
        "created": {"time": 1795000000000},
        "likesSummary": {"totalLikes": 4},
        "commentsSummary": {"aggregatedTotalComments": 2},
    }
    transport.on(
        "GET", "socialActions/urn%3Ali%3Ashare%3A7001/comments", {"elements": [node, {"id": "sin-urn"}]}
    )
    [comment] = await LinkedInCommentGateway(client).list_comments(ORGANIZATION, TOKEN, object_id=POST)
    assert (comment.external_id, comment.object_external_id, comment.text) == (
        COMMENT,
        POST,
        "¡Felicitaciones!",
    )
    assert (comment.author_id, comment.like_count, comment.reply_count) == ("urn:li:person:xyz", 4, 2)
    assert comment.created_at is not None


async def test_responder_borrar_y_reaccionar(transport: FakeTransport, client: LinkedInClient) -> None:
    gateway = LinkedInCommentGateway(client)
    path = "socialActions/urn%3Ali%3Aactivity%3A9001/comments"
    reply_urn = "urn:li:comment:(urn:li:activity:9001,7000)"
    transport.on(
        "POST", path, HttpResponse(201, {}, "", {"x-restli-id": reply_urn}), HttpResponse(201, {}, "")
    )
    assert await gateway.reply(ORGANIZATION, TOKEN, comment_id=COMMENT, text="¡Gracias!") == reply_urn
    # Se responde como la página, sobre la publicación que el comentario lleva en su URN.
    assert transport.calls[0].json == {
        "actor": "urn:li:organization:5515715",
        "object": "urn:li:activity:9001",
        "message": {"text": "¡Gracias!"},
        "parentComment": COMMENT,
    }
    with pytest.raises(ProviderError, match="id de la respuesta"):
        await gateway.reply(ORGANIZATION, TOKEN, comment_id=COMMENT, text="otra")

    transport.on("DELETE", f"{path}/6636", HttpResponse(204, None, ""))
    await gateway.delete(ORGANIZATION, TOKEN, comment_id=COMMENT)
    assert transport.calls[2].path == f"{path}/6636?actor={ORG}"

    transport.on("POST", "reactions", HttpResponse(201, {}, ""))
    await gateway.like(ORGANIZATION, TOKEN, comment_id=COMMENT)
    assert transport.calls[3].path == f"reactions?actor={ORG}"
    assert transport.calls[3].json == {"root": COMMENT, "reactionType": "LIKE"}


async def test_lo_que_linkedin_no_ofrece_en_comentarios(client: LinkedInClient) -> None:
    gateway = LinkedInCommentGateway(client)
    assert not gateway.supports(ORGANIZATION, CommentAction.HIDE)
    assert all(
        gateway.supports(ORGANIZATION, a)
        for a in (CommentAction.REPLY, CommentAction.DELETE, CommentAction.LIKE)
    )
    with pytest.raises(ProviderError, match="ocultar"):
        await gateway.set_hidden(ORGANIZATION, TOKEN, comment_id=COMMENT, hidden=True)
    with pytest.raises(ProviderError, match="no es el URN"):
        await gateway.delete(ORGANIZATION, TOKEN, comment_id="6636")


# ── Métricas ────────────────────────────────────────────────────────────────────────────────────


async def test_seguidores_y_totales_de_las_publicaciones(
    transport: FakeTransport, client: LinkedInClient
) -> None:
    reader = LinkedInInsightsReader(client, FakeClock())
    transport.on("GET", f"networkSizes/{ORG}", {"firstDegreeSize": 1540})
    totals = {"impressionCount": 9000, "uniqueImpressionsCount": 4000, "engagement": 0.031, "likeCount": None}
    transport.on(
        "GET", "organizationalEntityShareStatistics", {"elements": [{"totalShareStatistics": totals}]}
    )
    series = await reader.read(
        ORGANIZATION,
        TOKEN,
        metrics=["firstDegreeSize", "impressionCount", "engagement", "likeCount", "inventada"],
        period=Period.LIFETIME,
        window=TimeWindow(),
    )
    assert [(s.name, s.period, s.points[0].value) for s in series] == [
        ("firstDegreeSize", Period.LIFETIME, 1540.0),
        ("impressionCount", Period.LIFETIME, 9000.0),
        ("engagement", Period.LIFETIME, 0.031),
    ]
    assert series[0].points[0].end_time == NOW
    assert transport.calls[0].path == f"networkSizes/{ORG}?edgeType=COMPANY_FOLLOWED_BY_MEMBER"
    assert transport.calls[1].path == (
        f"organizationalEntityShareStatistics?q=organizationalEntity&organizationalEntity={ORG}"
    )
    catalog = reader.catalog
    assert (
        catalog.native_for(LINKEDIN_ORGANIZATION, CanonicalMetric.FOLLOWERS, reader.api_version)
        == "firstDegreeSize"
    )
    assert (
        catalog.native_for(LINKEDIN_ORGANIZATION, CanonicalMetric.REACH, reader.api_version)
        == "uniqueImpressionsCount"
    )


async def test_serie_diaria_con_ventana(transport: FakeTransport, client: LinkedInClient) -> None:
    reader = LinkedInInsightsReader(client, FakeClock())
    since, until = datetime(2026, 11, 20, tzinfo=UTC), datetime(2026, 11, 22, tzinfo=UTC)
    start, end = int(since.timestamp() * 1000), int(until.timestamp() * 1000)
    day = 86_400_000
    elements = [
        {"timeRange": {"start": start, "end": start + day}, "totalShareStatistics": {"impressionCount": 10}},
        {"timeRange": {"start": start + day, "end": end}, "totalShareStatistics": {"impressionCount": 30}},
    ]
    transport.on("GET", "organizationalEntityShareStatistics", {"elements": elements})
    [series] = await reader.read(
        ORGANIZATION, TOKEN, metrics=["impressionCount"], period=Period.DAY, window=TimeWindow(since, until)
    )
    assert (series.period, [p.value for p in series.points]) == (Period.DAY, [10.0, 30.0])
    assert series.points[1].end_time == until
    assert transport.calls[0].path.endswith(
        f"&timeIntervals=(timeRange:(start:{start},end:{end}),timeGranularityType:DAY)"
    )
    # Sin los dos extremos no hay serie diaria: se piden los totales.
    transport.calls.clear()
    await reader.read(
        ORGANIZATION, TOKEN, metrics=["impressionCount"], period=Period.DAY, window=TimeWindow()
    )
    assert "timeIntervals" not in transport.calls[0].path
    # Una página sin seguidores informados, y nada que pedir.
    transport.on("GET", f"networkSizes/{ORG}", {})
    assert (
        await reader.read(
            ORGANIZATION, TOKEN, metrics=["firstDegreeSize"], period=Period.DAY, window=TimeWindow()
        )
        == []
    )
    assert (
        await reader.read(ORGANIZATION, TOKEN, metrics=["inventada"], period=Period.DAY, window=TimeWindow())
        == []
    )
