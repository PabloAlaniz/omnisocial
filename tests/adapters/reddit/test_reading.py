"""Login, cuenta, publicaciones, comentarios y consultas auxiliares, con una API falsa."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.reddit.client import RedditClient
from omnisocial.adapters.providers.reddit.config import RedditOptions, community
from omnisocial.adapters.providers.reddit.oauth import reddit_oauth
from omnisocial.adapters.providers.reddit.provider import reddit_provider
from omnisocial.adapters.providers.reddit.reading import (
    RedditAssetDirectory,
    RedditCommentGateway,
    RedditContentReader,
    RedditLookups,
)
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import CommentAction
from omnisocial.domain.errors import PermissionMissing, ProviderError, RateLimited, TokenRejected
from omnisocial.domain.lookup import Choice
from omnisocial.domain.spec import Pace
from omnisocial.domain.window import TimeWindow
from omnisocial.testing import FakeTransport
from tests.adapters.reddit.conftest import (
    ACCOUNT,
    AGENT,
    COMMUNITIES,
    FLAIRS,
    ME,
    REVOKE_URL,
    TOKEN,
    TOKEN_URL,
    config,
    failure,
    listing,
    refused,
)
from tests.fakes import FakeClock

DAY = 86400
T0 = 1_795_000_000


def post(number: int, created: int, **extra: object) -> dict[str, object]:
    return {
        "name": f"t3_p{number}",
        "title": f"Título {number}",
        "created_utc": float(created),
        "permalink": f"/r/argentina/comments/p{number}/titulo/",
        "score": number * 10,
        "num_comments": number,
        "is_self": True,
        **extra,
    }


def comment(name: str, parent: str, *replies: dict[str, object], more: bool = False) -> dict[str, object]:
    children = [{"kind": "t1", "data": reply} for reply in replies]
    if more:
        children.append({"kind": "more", "data": {"children": ["x1", "x2"]}})
    return {
        "name": name,
        "parent_id": parent,
        "body": f"Texto de {name}",
        "author": "beto",
        "author_fullname": "t2_beto",
        "score": 5,
        "created_utc": float(T0),
        "replies": {"kind": "Listing", "data": {"children": children}} if children else "",
    }


# ── Login y configuración ───────────────────────────────────────────────────────────────────────


def test_la_configuracion_exige_un_user_agent_y_las_opciones_un_destino() -> None:
    with pytest.raises(ValueError, match="User-Agent"):
        config(user_agent="  ")
    assert "secreto" not in repr(config())
    assert [community(name) for name in ("r/argentina", "/r/argentina/", " argentina ")] == ["argentina"] * 3
    with pytest.raises(ValueError, match="comunidad"):
        RedditOptions(subreddit="r/", title="Hola")
    for title in ("  ", "x" * 301):
        with pytest.raises(ValueError, match="título"):
            RedditOptions(subreddit="argentina", title=title)


async def test_el_login_pide_un_token_que_se_renueva_y_todo_lleva_el_user_agent(
    transport: FakeTransport, client: RedditClient
) -> None:
    oauth = reddit_oauth(client, FakeClock())
    url = oauth.authorization_url(
        state="s",
        redirect_uri="https://app.ejemplo.com/cb",
        scopes=("identity", "submit"),
        code_challenge=None,
    )
    query = parse_qs(urlsplit(url).query)
    # Sin `duration=permanent` Reddit no da token de renovación, y el de acceso dura una hora.
    assert (query["duration"], query["scope"], oauth.supports_pkce) == (
        ["permanent"],
        ["identity submit"],
        False,
    )

    transport.on(
        "POST",
        TOKEN_URL,
        {"access_token": "a1", "refresh_token": "r1", "expires_in": 3600},
        {"access_token": "a2", "expires_in": 3600},
    )
    transport.on("POST", REVOKE_URL, HttpResponse(204, None, ""))
    transport.on("GET", "api/v1/me", ME, {"id": "abc12"})
    token = await oauth.exchange_code(
        code="abc", redirect_uri="https://app.ejemplo.com/cb", code_verifier=None
    )
    renewed = await oauth.refresh(token)
    # Reddit no rota el token de renovación: se conserva.
    assert (renewed.access_token, renewed.refresh_token) == ("a2", "r1")
    await oauth.revoke(renewed)
    identity = await oauth.identity(token)
    assert (identity.external_id, identity.name, identity.avatar_url) == ("abc12", "ana", ME["icon_img"])
    assert all(call.headers is not None and call.headers["User-Agent"] == AGENT for call in transport.calls)
    exchange, _, revoke, me_call = transport.calls
    assert exchange.headers is not None
    assert exchange.headers["Authorization"].startswith("Basic ")
    assert revoke.headers is not None
    assert (revoke.form, revoke.headers["Authorization"][:6]) == ({"token": "a2"}, "Basic ")
    assert me_call.headers is not None
    assert (me_call.headers["Authorization"], me_call.params) == ("bearer a1", {"raw_json": 1})
    with pytest.raises(ProviderError, match="nombre de la cuenta"):
        await oauth.identity(token)


async def test_la_cuenta_es_el_activo(transport: FakeTransport, client: RedditClient) -> None:
    transport.on("GET", "api/v1/me", ME)
    [asset] = await RedditAssetDirectory(client).discover(TOKEN)
    assert (asset.kind, asset.external_id, asset.name, asset.metadata) == (
        "reddit_account",
        "abc12",
        "u/ana",
        {"username": "ana"},
    )


# ── Publicaciones ───────────────────────────────────────────────────────────────────────────────


async def test_las_publicaciones_van_de_la_mas_nueva_a_la_mas_vieja(
    transport: FakeTransport, client: RedditClient
) -> None:
    link = post(2, T0 - DAY, is_self=False, url="https://ejemplo.com/nota", selftext="")
    transport.on(
        "GET",
        "user/ana/submitted",
        listing(post(1, T0, selftext="Cuerpo"), {"sin": "nombre"}, after="t3_p1"),
        listing(link, post(3, T0 - 40 * DAY)),
    )
    reader = RedditContentReader(client)
    window = TimeWindow(datetime.fromtimestamp(T0 - 7 * DAY, UTC), None)
    posts = await reader.list_posts(ACCOUNT, TOKEN, window=window, limit=None)
    assert [p.external_id for p in posts] == ["t3_p1", "t3_p2"]
    first, second = posts
    assert (first.text, first.permalink, first.media_type, first.media_url) == (
        "Título 1\n\nCuerpo",
        "https://www.reddit.com/r/argentina/comments/p1/titulo/",
        "self",
        None,
    )
    assert (first.like_count, first.comment_count, first.created_at) == (
        10,
        1,
        datetime.fromtimestamp(T0, UTC),
    )
    assert (second.text, second.media_type, second.media_url) == (
        "Título 2",
        "link",
        "https://ejemplo.com/nota",
    )
    assert [call.params for call in transport.calls] == [
        {"sort": "new", "limit": 100, "raw_json": 1},
        {"sort": "new", "limit": 100, "after": "t3_p1", "raw_json": 1},
    ]
    transport.calls.clear()
    assert len(await reader.list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=1)) == 1
    assert len(transport.calls) == 1


async def test_sin_nombre_de_usuario_no_se_puede_leer(client: RedditClient) -> None:
    bare = Asset("a1", "c1", ACCOUNT.provider, "dueño", ACCOUNT.kind, "abc12")
    with pytest.raises(ProviderError, match="sincronizarlo"):
        await RedditContentReader(client).list_posts(bare, TOKEN, window=TimeWindow(), limit=None)


async def test_un_listado_largo_se_corta_en_el_tope_de_paginas(transport: FakeTransport) -> None:
    client = RedditClient(config(max_pages=2), transport)
    transport.on("GET", "user/ana/submitted", listing(post(1, T0), after="sigue"))
    await RedditContentReader(client).list_posts(ACCOUNT, TOKEN, window=TimeWindow(), limit=None)
    assert len(transport.calls) == 2


# ── Comentarios ─────────────────────────────────────────────────────────────────────────────────


async def test_los_comentarios_vienen_en_arbol(transport: FakeTransport, client: RedditClient) -> None:
    nested = comment("t1_c2", "t1_c1")
    top = comment("t1_c1", "t3_p1", nested, more=True)
    transport.on(
        "GET",
        "comments/p1",
        [listing(post(1, T0)), listing(top, kind="t1")],
        [listing(post(1, T0))],
        {"raro": True},
    )
    gateway = RedditCommentGateway(client)
    [found] = await gateway.list_comments(ACCOUNT, TOKEN, object_id="t3_p1")
    assert (found.external_id, found.object_external_id, found.text) == ("t1_c1", "t3_p1", "Texto de t1_c1")
    assert (found.author_name, found.author_id, found.like_count, found.reply_count) == (
        "beto",
        "t2_beto",
        5,
        1,
    )
    # Lo que Reddit deja para pedir aparte no es un comentario.
    assert [reply.external_id for reply in found.replies] == ["t1_c2"]
    assert "replies" not in found.raw
    assert transport.calls[0].params == {"limit": 100, "sort": "new", "raw_json": 1}
    assert await gateway.list_comments(ACCOUNT, TOKEN, object_id="p1") == []
    assert await gateway.list_comments(ACCOUNT, TOKEN, object_id="p1") == []


async def test_responder_quitar_aprobar_y_borrar(transport: FakeTransport, client: RedditClient) -> None:
    created = {"json": {"errors": [], "data": {"things": [{"kind": "t1", "data": {"name": "t1_nuevo"}}]}}}
    transport.on("POST", "api/comment", created, {"json": {"errors": [], "data": {"things": []}}})
    for path in ("api/remove", "api/approve", "api/del"):
        transport.on("POST", path, {})
    gateway = RedditCommentGateway(client)
    assert await gateway.reply(ACCOUNT, TOKEN, comment_id="t1_c1", text="¡Gracias!") == "t1_nuevo"
    assert transport.calls[0].form == {
        "thing_id": "t1_c1",
        "text": "¡Gracias!",
        "api_type": "json",
        "raw_json": "1",
    }
    # Responder no es repetible.
    assert transport.calls[0].retry_safe is None
    await gateway.set_hidden(ACCOUNT, TOKEN, comment_id="t1_c1", hidden=True)
    await gateway.set_hidden(ACCOUNT, TOKEN, comment_id="t1_c1", hidden=False)
    await gateway.delete(ACCOUNT, TOKEN, comment_id="t1_nuevo")
    assert [(call.path, (call.form or {}).get("id")) for call in transport.calls[1:]] == [
        ("api/remove", "t1_c1"),
        ("api/approve", "t1_c1"),
        ("api/del", "t1_nuevo"),
    ]
    with pytest.raises(ProviderError, match="id del comentario"):
        await gateway.reply(ACCOUNT, TOKEN, comment_id="t1_c1", text="hola")
    offered = {action for action in CommentAction if gateway.supports(ACCOUNT, action)}
    assert offered == {CommentAction.REPLY, CommentAction.HIDE, CommentAction.DELETE}
    with pytest.raises(ProviderError, match="votos"):
        await gateway.like(ACCOUNT, TOKEN, comment_id="t1_c1")


# ── Consultas auxiliares ────────────────────────────────────────────────────────────────────────


async def test_las_comunidades_propias_o_buscadas(transport: FakeTransport, client: RedditClient) -> None:
    transport.on("GET", "subreddits/mine/subscriber", COMMUNITIES)
    transport.on("GET", "subreddits/search", COMMUNITIES)
    lookups = RedditLookups(client)
    mine = await lookups.choices(ACCOUNT, TOKEN, lookup="communities", query=None, parent=None)
    assert mine == [
        Choice(
            "argentina",
            "r/argentina",
            detail="Argentina",
            data={"subscribers": "900000", "submission_type": "any", "over18": "false"},
        ),
        Choice("cocina", "r/cocina"),
    ]
    found = await lookups.choices(ACCOUNT, TOKEN, lookup="communities", query="arg", parent=None)
    assert found == mine
    assert transport.calls[-1].params == {"q": "arg", "limit": 100, "raw_json": 1}


async def test_las_etiquetas_de_una_comunidad(transport: FakeTransport, client: RedditClient) -> None:
    transport.on(
        "GET",
        "r/argentina/api/link_flair_v2",
        FLAIRS,
        failure(403),
        failure(404),
        failure(403, "insufficient_scope"),
    )
    lookups = RedditLookups(client)
    flairs = await lookups.choices(ACCOUNT, TOKEN, lookup="flairs", query=None, parent="r/argentina")
    assert flairs == [
        Choice("f1", "Pregunta", data={"text_editable": "false"}),
        Choice("f2", "f2", data={"text_editable": "true"}),
    ]
    # Una comunidad sin etiquetas responde 403 o 404: no hay qué elegir.
    for _ in range(2):
        assert await lookups.choices(ACCOUNT, TOKEN, lookup="flairs", query=None, parent="argentina") == []
    with pytest.raises(PermissionMissing):
        await lookups.choices(ACCOUNT, TOKEN, lookup="flairs", query=None, parent="argentina")


# ── Errores ─────────────────────────────────────────────────────────────────────────────────────


async def test_los_errores_llegan_por_el_estado_la_cabecera_o_el_cuerpo(
    transport: FakeTransport, client: RedditClient
) -> None:
    transport.on(
        "GET",
        "api/v1/me",
        failure(401),
        failure(403, "insufficient_scope"),
        failure(429, **{"X-Ratelimit-Reset": "45"}),
        failure(429, **{"X-Ratelimit-Reset": "ya", "Retry-After": "3"}),
        HttpResponse(403, {"message": "Forbidden", "reason": "private", "error": 403}, ""),
    )
    with pytest.raises(TokenRejected):
        await client.get("api/v1/me", "t")
    with pytest.raises(PermissionMissing):
        await client.get("api/v1/me", "t")
    for seconds in (45.0, 3.0):
        with pytest.raises(RateLimited) as limited:
            await client.get("api/v1/me", "t")
        assert limited.value.retry_after == seconds
    # Una comunidad privada no es un permiso faltante: reconectar no lo arregla.
    with pytest.raises(ProviderError, match=r"Forbidden \(private\)") as private:
        await client.get("api/v1/me", "t")
    assert private.value.kind.value == "unknown"

    transport.on(
        "POST",
        "api/del",
        refused("RATELIMIT", "you are doing that too much. try again in 9 minutes.", "ratelimit"),
        refused("USER_REQUIRED", "please login to do that"),
        refused("THREAD_LOCKED"),
        {"json": {"errors": [["SOLO_CODIGO"]]}},
    )
    with pytest.raises(RateLimited) as wait:
        await client.act("api/del", "t", {"id": "t1_c1"})
    assert wait.value.retry_after == 540.0
    with pytest.raises(TokenRejected):
        await client.act("api/del", "t", {"id": "t1_c1"})
    for code in ("THREAD_LOCKED", "SOLO_CODIGO"):
        with pytest.raises(ProviderError) as invalid:
            await client.act("api/del", "t", {"id": "t1_c1"})
        assert (invalid.value.code, invalid.value.kind.value) == (code, "invalid_request")


async def test_el_proveedor_respeta_el_ritmo_de_reddit(transport: FakeTransport) -> None:
    provider = reddit_provider(config(), transport)
    assert provider.spec is not None
    assert provider.spec.pace == Pace(max_concurrent=2, min_interval=0.6)
    transport.on("GET", "api/v1/me", ME)
    assert provider.identity is not None
    await provider.identity.identity(TOKEN)
    assert transport.calls[0].headers is not None
    assert transport.calls[0].headers["User-Agent"] == AGENT
