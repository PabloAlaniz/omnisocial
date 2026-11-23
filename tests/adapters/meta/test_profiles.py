from __future__ import annotations

import pytest

from omnisocial.adapters.providers.meta.config import INSTAGRAM_ACCOUNT, META
from omnisocial.adapters.providers.meta.graph import GraphClient
from omnisocial.adapters.providers.meta.profiles import MetaProfileLookup
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.handles import Handle, Network
from omnisocial.domain.token import Token, TokenKind
from tests.adapters.meta.conftest import FakeGraph

TOKEN = Token(TokenKind.USER, "tok")
VIEWER = Asset("a2", "c1", META, "dueño", INSTAGRAM_ACCOUNT, "ig1", parent_external_id="p1")
MARCA = Handle(Network.INSTAGRAM, "marca")


async def test_perfil_con_business_discovery(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on(
        "GET",
        "ig1",
        {
            "business_discovery": {
                "id": "17841400",
                "username": "marca",
                "name": "Marca",
                "followers_count": 1200,
                "follows_count": 30,
                "media_count": 88,
                "biography": "hola",
                "profile_picture_url": "https://cdn/x.jpg",
                "website": "https://marca.com",
            },
            "id": "ig1",
        },
    )
    lookup = MetaProfileLookup(graph)
    profile = await lookup.lookup(MARCA, viewer=VIEWER, token=TOKEN)
    assert profile is not None
    assert (profile.external_id, profile.followers, profile.following, profile.posts) == (
        "17841400",
        1200,
        30,
        88,
    )
    assert profile.url == "https://www.instagram.com/marca/"
    assert fake.calls[0].params["fields"].startswith("business_discovery.username(marca){id,username")  # type: ignore[union-attr]
    assert lookup.networks == frozenset({Network.INSTAGRAM})
    assert lookup.viewer_kinds(Network.INSTAGRAM) == frozenset({INSTAGRAM_ACCOUNT})


async def test_cuenta_inexistente_o_personal(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("GET", "ig1", {"error": {"message": "Invalid user id", "code": 110}}, status=400)
    assert await MetaProfileLookup(graph).lookup(MARCA, viewer=VIEWER, token=TOKEN) is None


async def test_respuesta_sin_perfil_y_otros_errores(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("GET", "ig1", {"id": "ig1"}, {"error": {"message": "Pedido inválido", "code": 100}})
    lookup = MetaProfileLookup(graph)
    assert await lookup.lookup(MARCA, viewer=VIEWER, token=TOKEN) is None
    fake.routes[("GET", "ig1")] = []
    fake.on("GET", "ig1", {"error": {"message": "Pedido inválido", "code": 100}}, status=400)
    with pytest.raises(ProviderError, match="Pedido inválido"):
        await lookup.lookup(MARCA, viewer=VIEWER, token=TOKEN)


async def test_sin_mirador_es_un_error_de_programacion(graph: GraphClient) -> None:
    with pytest.raises(ValueError, match="mirador"):
        await MetaProfileLookup(graph).lookup(MARCA, viewer=None, token=None)
