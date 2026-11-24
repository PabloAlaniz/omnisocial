"""La bandeja: comentarios, reseñas y mensajes con la misma forma."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from omnisocial.application.results import AuthorizationStarted, Connected, Done, Refusal, Refused
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.content import Comment
from omnisocial.domain.errors import PermissionMissing, TokenRejected
from omnisocial.domain.inbox import InboxKind, arrange, from_comment, from_event
from omnisocial.domain.messaging import Attachment, AttachmentKind, DeliveryStatus, Message, MessagingLimits
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.webhooks import EventAction, EventKind, SocialEvent
from tests.application.conftest import World, build_world
from tests.fakes import FAKE, FAKE_SPEC, NOW, FakeComments, FakeMessaging, FakeNetwork


async def _page_id(world: World) -> str:
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.CONNECT, owner="c")
    assert isinstance(started, AuthorizationStarted)
    result = await world.social.complete_authorization.execute(state=started.state, code="abc")
    assert isinstance(result, Connected)
    return result.assets[0].id


def _comment(name: str, hours_ago: float, *replies: Comment, rating: int | None = None) -> Comment:
    return Comment(
        name,
        "post-1",
        NOW - timedelta(hours=hours_ago),
        text=f"Texto de {name}",
        author_id="u1",
        author_name="Beto",
        rating=rating,
        replies=replies,
    )


def _message(name: str, hours_ago: float, *, from_asset: bool = False) -> Message:
    photo = Attachment(AttachmentKind.IMAGE, url="https://cdn.ejemplo.com/a.jpg")
    return Message(
        name, "conv-1", NOW - timedelta(hours=hours_ago), "persona", "Hola", from_asset, attachments=(photo,)
    )


async def test_comentarios_y_mensajes_juntos_de_lo_mas_nuevo_a_lo_mas_viejo() -> None:
    comments = FakeComments(found=[_comment("c1", 5, _comment("c1-r", 1)), _comment("c2", 30)])
    messaging = FakeMessaging(messages=[_message("m1", 3), _message("m2", 2, from_asset=True)])
    world = build_world(FakeNetwork(comments=comments, messaging=messaging))
    page = await _page_id(world)
    inbox = await world.social.read_inbox.execute(page)
    assert isinstance(inbox, Done)
    assert [(i.kind, i.external_id) for i in inbox.value.items] == [
        (InboxKind.COMMENT, "c1-r"),
        (InboxKind.MESSAGE, "m2"),
        (InboxKind.MESSAGE, "m1"),
        (InboxKind.COMMENT, "c1"),
        (InboxKind.COMMENT, "c2"),
    ]
    message = inbox.value.items[2]
    assert (message.thread_external_id, message.author_id, message.from_asset) == ("conv-1", "persona", False)
    assert message.attachments[0].kind is AttachmentKind.IMAGE
    assert inbox.value.items[1].from_asset is True
    comment = inbox.value.items[3]
    assert (comment.thread_external_id, comment.author_name, comment.text) == (
        "post-1",
        "Beto",
        "Texto de c1",
    )
    assert (comment.provider, comment.asset_external_id) == (FAKE, "pag-1")
    assert inbox.value.skipped == ()

    recent = await world.social.read_inbox.execute(page, since=NOW - timedelta(hours=4))
    assert isinstance(recent, Done)
    assert [i.external_id for i in recent.value.items] == ["c1-r", "m2", "m1"]


async def test_lo_que_no_se_pudo_leer_se_informa_y_lo_demas_viene() -> None:
    comments = FakeComments(fail_with=PermissionMissing(FAKE, "falta un permiso"))
    world = build_world(FakeNetwork(comments=comments, messaging=FakeMessaging(messages=[_message("m1", 1)])))
    page = await _page_id(world)
    inbox = await world.social.read_inbox.execute(page)
    assert isinstance(inbox, Done)
    assert [i.external_id for i in inbox.value.items] == ["m1"]
    [skipped] = inbox.value.skipped
    assert (skipped.source, skipped.refused.reason) == ("comments", Refusal.MISSING_PERMISSION)


async def test_una_conexion_que_no_sirve_corta_todo() -> None:
    comments = FakeComments(fail_with=TokenRejected(FAKE, "token muerto"))
    world = build_world(FakeNetwork(comments=comments))
    page = await _page_id(world)
    refused = await world.social.read_inbox.execute(page)
    assert isinstance(refused, Refused)
    assert refused.reason is Refusal.CONNECTION_INVALID
    assert await world.social.read_inbox.execute("no-existe") == Refused(Refusal.NOT_FOUND)


async def test_lo_que_la_red_no_tiene_no_aporta_ni_molesta() -> None:
    only = frozenset({Capability.LOGIN, Capability.ASSETS, Capability.CONTENT})
    world = build_world(only=only)
    page = await _page_id(world)
    assert await world.social.read_inbox.execute(page) == Done(_empty())
    # Mensajes que solo llegan por avisos: tampoco aportan.
    silent = FakeMessaging(limits=MessagingLimits(max_text=100, history=False))
    world = build_world(FakeNetwork(comments=FakeComments(found=[]), messaging=silent))
    page = await _page_id(world)
    assert await world.social.read_inbox.execute(page) == Done(_empty())


def _empty() -> object:
    from omnisocial.application.use_cases.inbox import Inbox  # noqa: PLC0415

    return Inbox(())


async def test_las_resenas_se_piden_una_vez_sin_recorrer_publicaciones() -> None:
    comments = FakeComments(found=[_comment("r1", 2, rating=4)])
    network = FakeNetwork(comments=comments)
    world = build_world(network, spec=replace(FAKE_SPEC, asset_comments=frozenset({"pagina"})))
    page = await _page_id(world)
    inbox = await world.social.read_inbox.execute(page)
    assert isinstance(inbox, Done)
    [review] = [i for i in inbox.value.items if i.kind is InboxKind.REVIEW]
    assert (review.external_id, review.rating) == ("r1", 4)
    assert comments.asked == ["pag-1"]
    assert network.content.calls == []


def test_un_aviso_suma_a_la_bandeja_solo_si_alguien_escribio_algo() -> None:
    photo = Attachment(AttachmentKind.IMAGE, media_id="m1", mime_type="image/jpeg")
    arrived = SocialEvent(
        provider=ProviderId("whatsapp"),
        kind=EventKind.MESSAGE,
        action=EventAction.CREATED,
        asset_external_id="tel-1",
        object_external_id="wamid.1",
        occurred_at=NOW,
        actor_id="5491100000000",
        actor_name="Ana",
        text="Hola",
        conversation_external_id="5491100000000",
        attachments=(photo,),
    )
    item = from_event(arrived)
    assert item is not None
    assert (item.kind, item.external_id, item.thread_external_id, item.author_name, item.attachments) == (
        InboxKind.MESSAGE,
        "wamid.1",
        "5491100000000",
        "Ana",
        (photo,),
    )
    delivered = replace(arrived, action=EventAction.UPDATED, status=DeliveryStatus.DELIVERED)
    assert from_event(delivered) is None
    assert from_event(replace(arrived, kind=EventKind.POST)) is None
    assert from_event(replace(arrived, object_external_id=None)) is None
    assert from_event(replace(arrived, kind=EventKind.MENTION)).kind is InboxKind.MENTION  # type: ignore[union-attr]


def test_la_bandeja_no_repite_y_deja_al_final_lo_que_no_tiene_fecha() -> None:
    dated = next(from_comment(FAKE, "pag-1", _comment("c1", 1)))
    undated = replace(dated, external_id="c2", created_at=None)
    assert [i.external_id for i in arrange([undated, dated, dated])] == ["c1", "c2"]
    # Sin fecha no se puede saber si es anterior: se conserva.
    assert [i.external_id for i in arrange([undated, dated], since=NOW)] == ["c2"]
