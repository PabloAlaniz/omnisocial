from __future__ import annotations

from datetime import UTC, datetime

import pytest

from omnisocial.adapters.providers.meta.comments import MetaCommentGateway
from omnisocial.adapters.providers.meta.config import FACEBOOK_PAGE, INSTAGRAM_ACCOUNT, META
from omnisocial.adapters.providers.meta.content import PAGE_POST_BASIC_FIELDS, MetaContentReader
from omnisocial.adapters.providers.meta.graph import GraphClient
from omnisocial.domain.asset import Asset
from omnisocial.domain.content import CommentAction
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.token import Token, TokenKind
from omnisocial.domain.window import TimeWindow
from tests.adapters.meta.conftest import FakeGraph

TOKEN = Token(TokenKind.ASSET, "tok")


def asset(kind: str, external_id: str = "p1", parent: str | None = None) -> Asset:
    return Asset("a1", "c1", META, "dueño", kind, external_id, parent_external_id=parent)


PAGE = asset(FACEBOOK_PAGE)
INSTAGRAM = asset(INSTAGRAM_ACCOUNT, "ig1", parent="p1")


async def test_publicaciones_de_pagina_con_contadores(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on(
        "GET",
        "p1/posts",
        {
            "data": [
                {
                    "id": "p1_1",
                    "message": "Hola",
                    "created_time": "2026-11-20T10:00:00+0000",
                    "permalink_url": "https://fb/1",
                    "status_type": "added_photos",
                    "full_picture": "https://img",
                    "likes": {"summary": {"total_count": 7}},
                    "comments": {"summary": {"total_count": 2}},
                },
                {"id": "p1_2", "story": "Cambió su foto", "created_time": "2026-11-19T10:00:00+0000"},
            ]
        },
    )
    window = TimeWindow(datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 23, tzinfo=UTC))
    posts = await MetaContentReader(graph).list_posts(PAGE, TOKEN, window=window, limit=None)
    first, second = posts
    assert (first.text, first.like_count, first.comment_count, first.media_type) == (
        "Hola",
        7,
        2,
        "added_photos",
    )
    assert first.created_at == datetime(2026, 11, 20, 10, tzinfo=UTC)
    assert (second.text, second.like_count) == ("Cambió su foto", None)
    params = fake.calls[0].params
    assert params["since"] == int(window.since.timestamp())  # type: ignore[union-attr]
    assert params["until"] == int(window.until.timestamp())  # type: ignore[union-attr]


async def test_sin_permiso_de_contadores_trae_las_publicaciones_igual(
    fake: FakeGraph, graph: GraphClient
) -> None:
    fake.on("GET", "p1/posts", {"error": {"message": "permiso", "code": 10}}, status=403)
    fake.routes[("GET", "p1/posts")].append(
        fake.routes[("GET", "p1/posts")][0].__class__(200, {"data": [{"id": "p1_1", "message": "Hola"}]}, "x")
    )
    posts = await MetaContentReader(graph).list_posts(PAGE, TOKEN, window=TimeWindow(), limit=None)
    assert [p.external_id for p in posts] == ["p1_1"]
    assert fake.calls[1].params["fields"] == PAGE_POST_BASIC_FIELDS


async def test_otros_errores_de_publicaciones_se_propagan(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("GET", "p1/posts", {"error": {"message": "caído", "code": 2}}, status=500)
    with pytest.raises(ProviderError, match="caído"):
        await MetaContentReader(graph).list_posts(PAGE, TOKEN, window=TimeWindow(), limit=None)


async def test_media_de_instagram(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on(
        "GET",
        "ig1/media",
        {
            "data": [
                {
                    "id": "m1",
                    "caption": "Reel",
                    "media_type": "VIDEO",
                    "media_product_type": "REELS",
                    "timestamp": "2026-11-20T10:00:00+0000",
                    "thumbnail_url": "https://thumb",
                    "like_count": 30,
                    "comments_count": 4,
                },
                {"caption": "sin id"},
            ]
        },
    )
    [post] = await MetaContentReader(graph).list_posts(INSTAGRAM, TOKEN, window=TimeWindow(), limit=5)
    assert (post.text, post.media_type, post.media_url, post.like_count, post.comment_count) == (
        "Reel",
        "REELS",
        "https://thumb",
        30,
        4,
    )
    assert "since" not in fake.calls[0].params


async def test_comentarios_de_pagina(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on(
        "GET",
        "p1_1/comments",
        {
            "data": [
                {
                    "id": "c1",
                    "message": "Genial",
                    "from": {"id": "u1", "name": "Ana"},
                    "created_time": "2026-11-20T10:00:00+0000",
                    "like_count": 1,
                    "comment_count": 1,
                    "is_hidden": False,
                },
                {"id": "c2", "message": "Gracias", "parent": {"id": "c1"}},
            ]
        },
    )
    first, reply = await MetaCommentGateway(graph).list_comments(PAGE, TOKEN, object_id="p1_1")
    assert (first.author_name, first.object_external_id, first.hidden, first.reply_count) == (
        "Ana",
        "p1_1",
        False,
        1,
    )
    assert reply.object_external_id == "c1"
    assert fake.calls[0].params["filter"] == "stream"


async def test_comentarios_de_instagram_con_respuestas(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on(
        "GET",
        "m1/comments",
        {
            "data": [
                {
                    "id": "c1",
                    "text": "Lindo",
                    "username": "ana",
                    "timestamp": "2026-11-20T10:00:00+0000",
                    "hidden": True,
                    "from": {"id": "u1", "username": "ana"},
                    "replies": {
                        "data": [{"id": "c2", "text": "Gracias", "from": {"id": "ig1", "username": "pagina"}}]
                    },
                }
            ]
        },
    )
    [comment] = await MetaCommentGateway(graph).list_comments(INSTAGRAM, TOKEN, object_id="m1")
    assert (comment.author_name, comment.hidden, comment.reply_count) == ("ana", True, 1)
    [reply] = comment.replies
    assert (reply.object_external_id, reply.author_name) == ("c1", "pagina")


async def test_responder_y_ocultar_segun_la_red(fake: FakeGraph, graph: GraphClient) -> None:
    gateway = MetaCommentGateway(graph)
    fake.on("POST", "c1/comments", {"id": "c9"})
    fake.on("POST", "c1/replies", {"id": "c8"})
    fake.on("POST", "c1", {"success": True})
    assert await gateway.reply(PAGE, TOKEN, comment_id="c1", text="Gracias") == "c9"
    assert await gateway.reply(INSTAGRAM, TOKEN, comment_id="c1", text="Gracias") == "c8"
    await gateway.set_hidden(PAGE, TOKEN, comment_id="c1", hidden=True)
    await gateway.set_hidden(INSTAGRAM, TOKEN, comment_id="c1", hidden=False)
    assert fake.calls[0].params["message"] == "Gracias"
    assert fake.calls[2].params["is_hidden"] == "true"
    assert fake.calls[3].params["hide"] == "false"


async def test_borrar_y_dar_like(fake: FakeGraph, graph: GraphClient) -> None:
    gateway = MetaCommentGateway(graph)
    fake.on("DELETE", "c1", {"success": True})
    fake.on("POST", "c1/likes", {"success": True})
    await gateway.delete(INSTAGRAM, TOKEN, comment_id="c1")
    await gateway.like(PAGE, TOKEN, comment_id="c1")
    assert [(c.method, c.path) for c in fake.calls] == [("DELETE", "c1"), ("POST", "c1/likes")]


def test_instagram_no_ofrece_like_de_comentarios(graph: GraphClient) -> None:
    gateway = MetaCommentGateway(graph)
    assert not gateway.supports(INSTAGRAM, CommentAction.LIKE)
    assert gateway.supports(INSTAGRAM, CommentAction.DELETE)
    assert gateway.supports(PAGE, CommentAction.LIKE)


async def test_responder_sin_id_es_error(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("POST", "c1/comments", {"success": True})
    with pytest.raises(ProviderError, match="id de la respuesta"):
        await MetaCommentGateway(graph).reply(PAGE, TOKEN, comment_id="c1", text="x")
