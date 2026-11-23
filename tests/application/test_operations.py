from __future__ import annotations

from datetime import timedelta

from omnisocial.application.results import (
    AuthorizationStarted,
    Connected,
    Done,
    InsightsRead,
    Refusal,
    Refused,
)
from omnisocial.domain.asset import DiscoveredAsset
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.messaging import Message
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.provider import Capability
from omnisocial.domain.window import TimeWindow
from tests.application.conftest import World, build_world
from tests.fakes import NOW, FakeAssets, FakeNetwork


async def _page_id(world: World) -> str:
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.CONNECT, owner="c")
    assert isinstance(started, AuthorizationStarted)
    result = await world.social.complete_authorization.execute(state=started.state, code="abc")
    assert isinstance(result, Connected)
    return result.assets[0].id


def _msg(hours_ago: float, *, from_asset: bool, sender: str = "persona") -> Message:
    return Message("m", "conv-1", NOW - timedelta(hours=hours_ago), sender, "hola", from_asset=from_asset)


async def test_publicaciones_con_el_token_del_activo(world: World) -> None:
    page = await _page_id(world)
    result = await world.social.list_posts.execute(page, window=TimeWindow(NOW - timedelta(days=7), NOW))
    assert isinstance(result, Done)
    assert result.value[0].external_id == "post-1"
    assert world.network.content.calls == [("pag-1", "tok-pagina")]


async def test_comentarios_responder_y_ocultar(world: World) -> None:
    page = await _page_id(world)
    listed = await world.social.list_comments.execute(page, object_id="post-1")
    assert isinstance(listed, Done)
    assert listed.value[0].object_external_id == "post-1"
    assert await world.social.reply_to_comment.execute(page, comment_id="com-1", text="¡Gracias!") == Done(
        "com-nuevo"
    )
    assert await world.social.set_comment_hidden.execute(page, comment_id="com-1", hidden=True) == Done(None)
    assert world.network.comments.replies == [("com-1", "¡Gracias!")]
    assert world.network.comments.hidden == {"com-1": True}


async def test_conversaciones_y_mensajes(world: World) -> None:
    page = await _page_id(world)
    world.network.messaging.messages = [_msg(1, from_asset=False)]
    conversations = await world.social.list_conversations.execute(page)
    assert isinstance(conversations, Done)
    assert conversations.value[0].external_id == "conv-1"
    messages = await world.social.list_messages.execute(page, conversation_id="conv-1")
    assert isinstance(messages, Done)
    assert len(messages.value) == 1


async def test_responder_un_mensaje_dentro_de_la_ventana(world: World) -> None:
    page = await _page_id(world)
    world.network.messaging.messages = [
        _msg(5, from_asset=False, sender="vieja"),
        _msg(2, from_asset=False, sender="persona"),
        _msg(1, from_asset=True, sender="pagina"),
    ]
    result = await world.social.send_message.execute(page, conversation_id="conv-1", text="Hola")
    assert result == Done("msg-nuevo")
    assert world.network.messaging.sent == [("persona", "Hola")]


async def test_fuera_de_la_ventana_no_se_llama_a_la_red(world: World) -> None:
    page = await _page_id(world)
    world.network.messaging.messages = [_msg(25, from_asset=False)]
    result = await world.social.send_message.execute(page, conversation_id="conv-1", text="Hola")
    assert result == Refused(Refusal.OUTSIDE_REPLY_WINDOW)
    assert world.network.messaging.sent == []


async def test_sin_mensajes_de_la_persona_no_hay_a_quien_responder(world: World) -> None:
    page = await _page_id(world)
    world.network.messaging.messages = [_msg(1, from_asset=True)]
    result = await world.social.send_message.execute(page, conversation_id="conv-1", text="Hola")
    assert result == Refused(Refusal.NO_RECIPIENT)


async def test_metricas_por_nombre_comun_y_propio(world: World) -> None:
    page = await _page_id(world)
    result = await world.social.read_insights.execute(
        page,
        metrics=[CanonicalMetric.REACH, "propia", CanonicalMetric.VIEWS],
        period=Period.DAY,
        window=TimeWindow(NOW - timedelta(days=28), NOW),
    )
    assert isinstance(result, InsightsRead)
    assert world.network.insights.requested == [("alcance_unico", "propia")]
    assert [(s.name, s.canonical) for s in result.series] == [
        ("alcance_unico", CanonicalMetric.REACH),
        ("propia", None),
    ]
    assert result.unresolved == (CanonicalMetric.VIEWS,)


async def test_si_nada_se_traduce_no_se_llama_a_la_red(world: World) -> None:
    page = await _page_id(world)
    result = await world.social.read_insights.execute(
        page, metrics=[CanonicalMetric.VIEWS], period=Period.DAY, window=TimeWindow()
    )
    assert result == InsightsRead(series=(), unresolved=(CanonicalMetric.VIEWS,))
    assert world.network.insights.requested == []


async def test_una_red_sin_la_capacidad_se_niega() -> None:
    world = build_world(only=frozenset({Capability.LOGIN, Capability.ASSETS}))
    page = await _page_id(world)
    result = await world.social.list_posts.execute(page)
    assert result == Refused(Refusal.NOT_SUPPORTED, capability=Capability.CONTENT)


async def test_un_activo_que_declara_capacidades_sin_esa_se_niega() -> None:
    network = FakeNetwork(
        assets=FakeAssets([DiscoveredAsset("pagina", "p", capabilities=frozenset({Capability.CONTENT}))])
    )
    world = build_world(network)
    page = await _page_id(world)
    assert isinstance(await world.social.list_posts.execute(page), Done)
    assert await world.social.list_comments.execute(page, object_id="x") == Refused(
        Refusal.NOT_SUPPORTED, capability=Capability.COMMENTS
    )


async def test_todas_las_operaciones_propagan_el_rechazo_de_acceso(world: World) -> None:
    missing = Refused(Refusal.NOT_FOUND)
    social = world.social
    assert await social.list_posts.execute("nada") == missing
    assert await social.list_comments.execute("nada", object_id="x") == missing
    assert await social.reply_to_comment.execute("nada", comment_id="x", text="t") == missing
    assert await social.set_comment_hidden.execute("nada", comment_id="x", hidden=True) == missing
    assert await social.list_conversations.execute("nada") == missing
    assert await social.list_messages.execute("nada", conversation_id="x") == missing
    assert await social.send_message.execute("nada", conversation_id="x", text="t") == missing
    assert (
        await social.read_insights.execute("nada", metrics=["x"], period=Period.DAY, window=TimeWindow())
        == missing
    )


async def test_webhooks_verifican_firma_y_enrutan(world: World) -> None:
    await _page_id(world)
    result = await world.social.handle_webhook.execute("falsa", body=b"pag-1", headers={"X-Firma": "valida"})
    assert isinstance(result, Done)
    [routed] = result.value
    assert routed.event.object_external_id == "com-9"
    assert [a.owner for a in routed.assets] == ["c"]


async def test_webhooks_sin_firma_valida_no_se_traducen(world: World) -> None:
    result = await world.social.handle_webhook.execute("falsa", body=b"pag-1", headers={"x-firma": "mala"})
    assert result == Refused(Refusal.INVALID_SIGNATURE)
