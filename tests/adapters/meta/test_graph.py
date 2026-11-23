from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.meta.config import MetaConfig
from omnisocial.adapters.providers.meta.graph import GraphClient, parse_time, summary_count
from omnisocial.domain.errors import PermissionMissing, ProviderError, TokenRejected
from omnisocial.domain.window import TimeWindow
from tests.adapters.meta.conftest import FakeGraph, config


def test_fechas_de_la_graph_api() -> None:
    expected = datetime(2026, 11, 20, 15, 4, 5, tzinfo=UTC)
    assert parse_time("2026-11-20T15:04:05+0000") == expected
    assert parse_time("2026-11-20T15:04:05.000+0000") == expected
    assert parse_time("2026-11-20T15:04:05") == expected
    assert parse_time(int(expected.timestamp())) == expected
    assert parse_time(int(expected.timestamp()) * 1000) == expected
    assert parse_time("no es fecha") is None
    assert parse_time(None) is None
    assert parse_time(True) is None


def test_contadores_de_summary() -> None:
    assert summary_count({"summary": {"total_count": 4}}) == 4
    assert summary_count(None) is None


def test_la_configuracion_valida_lo_basico() -> None:
    with pytest.raises(ValueError, match="los dos o ninguno"):
        MetaConfig(app_id="a", app_secret="", api_version="v24.0")
    with pytest.raises(ValueError, match="los dos o ninguno"):
        MetaConfig(app_secret="s", api_version="v24.0")
    with pytest.raises(ValueError, match=r"v24\.0"):
        MetaConfig(app_id="a", app_secret="s", api_version="24")
    assert "secreto" not in repr(config())
    assert config().app_access_token == "app|secreto"


async def test_firma_cada_llamada_con_appsecret_proof(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("GET", "me", {"id": "1"})
    await graph.get("me", "tok", {"fields": "id"})
    [call] = fake.calls
    expected = hmac.new(b"secreto", b"tok", hashlib.sha256).hexdigest()
    assert call.params == {"fields": "id", "access_token": "tok", "appsecret_proof": expected}


async def test_sin_appsecret_proof_si_se_desactiva(fake: FakeGraph) -> None:
    fake.on("GET", "me", {"id": "1"})
    await GraphClient(config(use_appsecret_proof=False), fake).get("me", "tok")
    assert "appsecret_proof" not in fake.calls[0].params


@pytest.mark.parametrize("code", [190, 102])
async def test_token_muerto(fake: FakeGraph, graph: GraphClient, code: int) -> None:
    fake.on("GET", "me", {"error": {"message": "Session expired", "code": code}}, status=400)
    with pytest.raises(TokenRejected, match="Session expired") as error:
        await graph.get("me", "tok")
    assert error.value.code == str(code)


@pytest.mark.parametrize("code", [10, 200, 230, 299])
async def test_permisos_faltantes(fake: FakeGraph, graph: GraphClient, code: int) -> None:
    fake.on("GET", "me", {"error": {"message": "Falta permiso", "code": code}}, status=403)
    with pytest.raises(PermissionMissing, match="Falta permiso") as error:
        await graph.get("me", "tok")
    assert (error.value.status, error.value.code) == (403, str(code))


async def test_otros_errores(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("GET", "me", {"error": {"message": "Pedido inválido", "code": 100}}, status=400)
    with pytest.raises(ProviderError, match="Pedido inválido") as error:
        await graph.get("me", "tok")
    assert not isinstance(error.value, PermissionMissing)
    assert (error.value.status, error.value.code) == (400, "100")


async def test_errores_sin_json(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("GET", "me", HttpResponse(502, None, "Bad gateway"))
    with pytest.raises(ProviderError, match="Bad gateway"):
        await graph.get("me", "tok")
    fake.on("GET", "otra", HttpResponse(200, None, "<html>"))
    with pytest.raises(ProviderError, match="JSON"):
        await graph.get("otra", "tok")


async def test_respuestas_booleanas(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("DELETE", "me/permissions", HttpResponse(200, True, "true"))
    assert await graph.delete("me/permissions", "tok") == {"success": True}


async def test_paginacion_sigue_next(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("GET", "p/posts", {"data": [{"id": "1"}], "paging": {"next": "next:2"}})
    fake.on("GET", "next:2", {"data": [{"id": "2"}]})
    pages = [page async for page in graph.paginate("p/posts", "tok")]
    assert pages == [[{"id": "1"}], [{"id": "2"}]]


def _item(item_id: str, days_ago: int) -> dict[str, object]:
    moment = datetime(2026, 11, 23, tzinfo=UTC) - timedelta(days=days_ago)
    return {"id": item_id, "t": moment.strftime("%Y-%m-%dT%H:%M:%S+0000")}


async def test_collect_aplica_ventana_y_corta_cuando_todo_es_viejo(
    fake: FakeGraph, graph: GraphClient
) -> None:
    fake.on("GET", "p/media", {"data": [_item("nuevo", 0), _item("1", 2)], "paging": {"next": "next:2"}})
    fake.on("GET", "next:2", {"data": [_item("2", 5), _item("viejo", 20)], "paging": {"next": "next:3"}})
    fake.on("GET", "next:3", {"data": [_item("viejísimo", 30)], "paging": {"next": "next:4"}})
    window = TimeWindow(datetime(2026, 11, 13, tzinfo=UTC), datetime(2026, 11, 22, tzinfo=UTC))
    items = await graph.collect("p/media", "tok", None, time_field="t", window=window)
    assert [i["id"] for i in items] == ["1", "2"]
    assert [c.url for c in fake.calls][-1] == "next:3"


async def test_collect_respeta_el_tope(fake: FakeGraph, graph: GraphClient) -> None:
    fake.on("GET", "p/media", {"data": [_item("1", 0), _item("2", 1)], "paging": {"next": "next:2"}})
    items = await graph.collect("p/media", "tok", None, time_field="t", limit=1)
    assert [i["id"] for i in items] == ["1"]
    assert len(fake.calls) == 1


async def test_modo_token_sin_app(fake: FakeGraph) -> None:
    token_only = MetaConfig(api_version="v24.0")
    assert not token_only.has_app
    with pytest.raises(ValueError, match="modo token"):
        _ = token_only.app_access_token
    fake.on("GET", "me", {"id": "1"})
    await GraphClient(token_only, fake).get("me", "tok")
    assert "appsecret_proof" not in fake.calls[0].params
