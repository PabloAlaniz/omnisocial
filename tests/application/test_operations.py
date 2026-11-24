from __future__ import annotations

from datetime import timedelta

import pytest

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
from omnisocial.domain.content import CommentAction
from omnisocial.domain.errors import (
    PermissionMissing,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.lookup import Choice
from omnisocial.domain.messaging import Message
from omnisocial.domain.metrics import CanonicalMetric, Period
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.window import TimeWindow
from tests.application.conftest import World, build_world
from tests.fakes import NOW, FakeAssets, FakeLookups, FakeNetwork


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


async def test_borrar_y_dar_like_a_un_comentario(world: World) -> None:
    page = await _page_id(world)
    assert await world.social.delete_comment.execute(page, comment_id="com-1") == Done(None)
    assert await world.social.like_comment.execute(page, comment_id="com-2") == Done(None)
    assert world.network.comments.deleted == ["com-1"]
    assert world.network.comments.liked == ["com-2"]


async def test_una_accion_que_la_red_no_ofrece_se_niega_sin_llamarla(world: World) -> None:
    page = await _page_id(world)
    world.network.comments.not_offered = {CommentAction.LIKE}
    result = await world.social.like_comment.execute(page, comment_id="com-1")
    assert isinstance(result, Refused)
    assert (result.reason, result.detail) == (Refusal.ACTION_NOT_OFFERED, "like")
    assert world.network.comments.liked == []


async def test_un_permiso_faltante_vuelve_como_negativa(world: World) -> None:
    page = await _page_id(world)
    world.network.comments.fail_with = PermissionMissing(ProviderId("falsa"), "falta leer comentarios")
    result = await world.social.list_comments.execute(page, object_id="post-1")
    assert isinstance(result, Refused)
    assert result.reason is Refusal.MISSING_PERMISSION
    assert result.detail == "falta leer comentarios"
    # La conexión sigue sana: falta un permiso, el token sirve.
    again = await world.social.list_posts.execute(page)
    assert isinstance(again, Done)


async def test_un_token_rechazado_en_una_operacion_invalida_la_conexion(world: World) -> None:
    page = await _page_id(world)
    world.network.comments.fail_with = TokenRejected(ProviderId("falsa"), "la red revocó el token")
    result = await world.social.list_comments.execute(page, object_id="post-1")
    assert isinstance(result, Refused)
    assert (result.reason, result.detail) == (Refusal.CONNECTION_INVALID, "la red revocó el token")
    # Las demás operaciones ya no llaman a la red hasta que alguien reconecte.
    posts = await world.social.list_posts.execute(page)
    assert isinstance(posts, Refused)
    assert posts.reason is Refusal.CONNECTION_INVALID
    # Si ya estaba marcada, se informa el estado guardado sin volver a marcar.
    again = await world.social.list_comments.execute(page, object_id="post-1")
    assert isinstance(again, Refused)
    assert again.reason is Refusal.CONNECTION_INVALID


async def test_invalidar_una_conexion_que_no_existe(world: World) -> None:
    result = await world.social.get_valid_token.invalidate("no-existe", "x")
    assert result == Refused(Refusal.NOT_FOUND)


async def test_un_limite_de_uso_vuelve_como_negativa_con_la_espera(world: World) -> None:
    page = await _page_id(world)
    world.network.comments.fail_with = RateLimited(ProviderId("falsa"), "despacio", retry_after=30.0)
    limited = await world.social.list_comments.execute(page, object_id="post-1")
    assert limited == Refused(
        Refusal.RATE_LIMITED, detail="despacio", capability=Capability.COMMENTS, retry_after=30.0
    )
    world.network.comments.fail_with = QuotaExhausted(ProviderId("falsa"), "sin crédito")
    exhausted = await world.social.list_comments.execute(page, object_id="post-1")
    assert isinstance(exhausted, Refused)
    assert exhausted.reason is Refusal.QUOTA_EXHAUSTED
    # La conexión sigue sana: el token no tiene la culpa.
    world.network.comments.fail_with = None
    assert isinstance(await world.social.list_comments.execute(page, object_id="post-1"), Done)


async def test_un_error_que_no_es_una_decision_sigue_siendo_una_excepcion(world: World) -> None:
    page = await _page_id(world)
    world.network.comments.fail_with = ProviderError(ProviderId("falsa"), "se cayó", status=500)
    with pytest.raises(ProviderError, match="se cayó"):
        await world.social.list_comments.execute(page, object_id="post-1")


async def test_consultas_auxiliares_para_publicar() -> None:
    lookups = FakeLookups()
    world = build_world(FakeNetwork(lookups=lookups))
    page = await _page_id(world)
    available = await world.social.list_choices.available(page)
    assert isinstance(available, Done)
    assert [(spec.name, spec.parent) for spec in available.value] == [
        ("tableros", None),
        ("secciones", "tableros"),
    ]
    assert await world.social.list_choices.execute(page, "tableros", query="rec") == Done(
        (Choice("t1", "Recetas"),)
    )
    assert await world.social.list_choices.execute(page, "secciones", parent="t1") == Done(
        (Choice("t1", "Recetas"),)
    )
    assert lookups.calls == [("tableros", "rec", None), ("secciones", None, "t1")]
    # Lo que la red no declara no llega al adaptador, y una consulta que depende de otra pide su elección.
    unknown = await world.social.list_choices.execute(page, "etiquetas")
    assert isinstance(unknown, Refused)
    assert (unknown.reason, unknown.detail) == (Refusal.UNKNOWN_LOOKUP, "etiquetas")
    orphan = await world.social.list_choices.execute(page, "secciones")
    assert isinstance(orphan, Refused)
    assert (orphan.reason, orphan.detail) == (Refusal.PARENT_REQUIRED, "tableros")
    assert len(lookups.calls) == 2
    assert await world.social.list_choices.execute("no-existe", "tableros") == Refused(Refusal.NOT_FOUND)


async def test_una_red_sin_consultas_auxiliares_no_ofrece_ninguna(world: World) -> None:
    page = await _page_id(world)
    assert await world.social.list_choices.available(page) == Done(())
    refused = await world.social.list_choices.execute(page, "tableros")
    assert isinstance(refused, Refused)
    assert refused.reason is Refusal.UNKNOWN_LOOKUP


async def test_un_token_rechazado_al_consultar_invalida_la_conexion() -> None:
    class Dead:
        async def choices(self, *_: object, **__: object) -> tuple[Choice, ...]:
            raise TokenRejected(ProviderId("falsa"), "token muerto")

    world = build_world(FakeNetwork(lookups=Dead()))  # type: ignore[arg-type]
    page = await _page_id(world)
    refused = await world.social.list_choices.execute(page, "tableros")
    assert isinstance(refused, Refused)
    assert refused.reason is Refusal.CONNECTION_INVALID
