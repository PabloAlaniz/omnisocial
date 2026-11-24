"""Publicar posts e hilos en X, con una API falsa."""

from __future__ import annotations

import base64
import json

import pytest

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.x.client import XClient
from omnisocial.adapters.providers.x.config import X_ACCOUNT, XOptions
from omnisocial.adapters.providers.x.provider import x_provider
from omnisocial.adapters.providers.x.publishing import XPublisher
from omnisocial.adapters.providers.x.spec import ACCOUNT_LIMITS, SPEC
from omnisocial.domain.errors import (
    NotPublished,
    PermissionMissing,
    ProviderError,
    QuotaExhausted,
    TokenRejected,
)
from omnisocial.domain.publishing import (
    BytesFile,
    Draft,
    DraftIssue,
    Media,
    MediaKind,
    PublicationStatus,
    check_draft,
)
from omnisocial.testing import FakeTransport
from tests.adapters.x.conftest import ACCOUNT, TOKEN, config, problem
from tests.fakes import FakeClock

PHOTO = Media(MediaKind.IMAGE, file=BytesFile(b"0123456789", "image/png"), alt_text="El equipo")
GIF = Media(MediaKind.IMAGE, file=BytesFile(b"GIF89a", "image/gif"))
VIDEO = Media(MediaKind.VIDEO, file=BytesFile(b"video-datos", "video/mp4"))


def created(post_id: str) -> HttpResponse:
    return HttpResponse(201, {"data": {"id": post_id, "text": "…"}}, "")


def media_routes(transport: FakeTransport, media_id: str, finalize: dict[str, object] | None = None) -> None:
    transport.on("POST", "media/upload/initialize", {"data": {"id": media_id, "media_key": f"3_{media_id}"}})
    transport.on("POST", f"media/upload/{media_id}/append", {"data": {}})
    transport.on("POST", f"media/upload/{media_id}/finalize", {"data": {"id": media_id, **(finalize or {})}})
    transport.on("POST", "media/metadata", {"data": {"id": media_id}})


@pytest.fixture
def publisher(client: XClient) -> XPublisher:
    return XPublisher(client)


async def test_un_post_de_texto(transport: FakeTransport, publisher: XPublisher) -> None:
    transport.on("POST", "tweets", created("100"))
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Hola mundo"))
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        "100",
        "https://x.com/i/web/status/100",
    )
    call = transport.calls[0]
    assert call.json == {"text": "Hola mundo"}
    # Crear un post no es repetible: un reintento automático lo duplicaría (y lo cobraría dos veces).
    assert call.retry_safe is None


async def test_una_foto_se_sube_por_partes_con_su_texto_alternativo(transport: FakeTransport) -> None:
    client = XClient(config(media_segment_bytes=4), transport, FakeClock())
    media_routes(transport, "m1")
    transport.on("POST", "tweets", created("100"))
    await XPublisher(client).publish(ACCOUNT, TOKEN, draft=Draft("Mirá", media=(PHOTO,)))
    init, *appends, finalize, metadata, post = transport.calls
    assert init.json == {"media_type": "image/png", "total_bytes": 10, "media_category": "tweet_image"}
    assert [a.json for a in appends] == [
        {"media": base64.b64encode(b"0123").decode(), "segment_index": 0},
        {"media": base64.b64encode(b"4567").decode(), "segment_index": 1},
        {"media": base64.b64encode(b"89").decode(), "segment_index": 2},
    ]
    assert (finalize.path, finalize.json) == ("media/upload/m1/finalize", None)
    assert metadata.json == {"id": "m1", "metadata": {"alt_text": {"text": "El equipo"}}}
    assert post.json == {"text": "Mirá", "media": {"media_ids": ["m1"]}}
    # Subir un medio no publica nada: esos pasos se pueden repetir.
    assert all(call.retry_safe for call in (init, *appends, finalize, metadata))


async def test_un_gif_y_una_respuesta(transport: FakeTransport, publisher: XPublisher) -> None:
    media_routes(transport, "m1")
    transport.on("POST", "tweets", created("100"))
    draft = Draft("", media=(GIF,), options=XOptions(reply_to="55"))
    await publisher.publish(ACCOUNT, TOKEN, draft=draft)
    assert transport.calls[0].json["media_category"] == "tweet_gif"  # type: ignore[index]
    # Sin texto, el post lleva solo el medio.
    assert transport.calls[-1].json == {
        "media": {"media_ids": ["m1"]},
        "reply": {"in_reply_to_tweet_id": "55"},
    }


async def test_un_hilo_encadena_cada_parte_con_la_anterior(
    transport: FakeTransport, publisher: XPublisher
) -> None:
    transport.on("POST", "tweets", created("100"), created("101"), created("102"))
    draft = Draft("Uno", thread=(Draft("Dos"), Draft("Tres")))
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=draft)
    # El id de la publicación es el del primer post.
    assert (outcome.status, outcome.post_id) == (PublicationStatus.PUBLISHED, "100")
    assert [call.json for call in transport.calls] == [
        {"text": "Uno"},
        {"text": "Dos", "reply": {"in_reply_to_tweet_id": "100"}},
        {"text": "Tres", "reply": {"in_reply_to_tweet_id": "101"}},
    ]


@pytest.mark.parametrize("failure", [problem(403, detail="Reply not allowed"), TransportError("se cortó")])
async def test_un_hilo_que_se_corta_ya_salio_en_parte(
    transport: FakeTransport, publisher: XPublisher, failure: HttpResponse | TransportError
) -> None:
    transport.on("POST", "tweets", created("100"), failure)
    outcome = await publisher.publish(
        ACCOUNT, TOKEN, draft=Draft("Uno", thread=(Draft("Dos"), Draft("Tres")))
    )
    assert (outcome.status, outcome.post_id) == (PublicationStatus.PUBLISHED_WITH_ERROR, "100")
    assert "cortado en la parte 2" in (outcome.error or "")
    # No se sigue con la parte 3: quedaría colgada de la 1.
    assert len(transport.calls) == 2


async def test_un_video_queda_pendiente_hasta_que_x_lo_procesa(
    transport: FakeTransport, publisher: XPublisher
) -> None:
    media_routes(transport, "v1", {"processing_info": {"state": "pending", "check_after_secs": 5}})
    draft = Draft("Video", media=(VIDEO,), thread=(Draft("Y sigue"),), options=XOptions(reply_to="55"))
    pending = await publisher.publish(ACCOUNT, TOKEN, draft=draft)
    assert pending.status is PublicationStatus.PENDING
    assert pending.resume["waiting"] == "v1"
    assert pending.resume["reply_to"] == "55"
    # El plan de lo que falta crear queda guardado, con los medios ya subidos.
    assert json.loads(pending.resume["plan"]) == [
        {"text": "Video", "media": ["v1"]},
        {"text": "Y sigue", "media": []},
    ]
    assert transport.calls[0].json["media_category"] == "tweet_video"  # type: ignore[index]
    assert all(call.path != "tweets" for call in transport.calls)

    transport.on(
        "GET",
        "media/upload",
        {"data": {"processing_info": {"state": "in_progress", "progress_percent": 40}}},
        {"data": {"processing_info": {"state": "succeeded"}}},
    )
    still = await publisher.resume(ACCOUNT, TOKEN, resume=pending.resume)
    assert (still.status, still.resume) == (PublicationStatus.PENDING, pending.resume)
    transport.on("POST", "tweets", created("100"), created("101"))
    done = await publisher.resume(ACCOUNT, TOKEN, resume=pending.resume)
    assert (done.status, done.post_id) == (PublicationStatus.PUBLISHED, "100")
    assert transport.calls[-3].params == {"media_id": "v1"}
    assert transport.calls[-2].json == {
        "text": "Video",
        "media": {"media_ids": ["v1"]},
        "reply": {"in_reply_to_tweet_id": "55"},
    }
    assert transport.calls[-1].json == {"text": "Y sigue", "reply": {"in_reply_to_tweet_id": "100"}}


async def test_retomar_cuando_x_no_pudo_o_rechaza(transport: FakeTransport, publisher: XPublisher) -> None:
    resume = {"plan": json.dumps([{"text": "Video", "media": ["v1"]}]), "waiting": "v1", "reply_to": ""}
    transport.on("GET", "media/upload", {"data": {"processing_info": {"state": "failed"}}})
    failed = await publisher.resume(ACCOUNT, TOKEN, resume=resume)
    assert (failed.status, failed.error) == (PublicationStatus.FAILED, "X no pudo procesar el video.")

    # Ya procesado, pero X rechaza el post: no sale, y reintentar daría lo mismo.
    transport.routes.clear()
    transport.on("GET", "media/upload", {"data": {"id": "v1"}})
    transport.on("POST", "tweets", problem(403, detail="duplicate content"))
    rejected = await publisher.resume(ACCOUNT, TOKEN, resume=resume)
    assert rejected.status is PublicationStatus.FAILED
    assert "duplicate content" in (rejected.error or "")

    # Un límite de uso, en cambio, deja la publicación pendiente para retomarla después.
    transport.routes.clear()
    transport.on("GET", "media/upload", {"data": {}})
    transport.on("POST", "tweets", problem(402, detail="Add credits"))
    with pytest.raises(QuotaExhausted):
        await publisher.resume(ACCOUNT, TOKEN, resume=resume)
    with pytest.raises(ProviderError, match="retomar"):
        await publisher.resume(ACCOUNT, TOKEN, resume={})


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (TransportError("se cortó"), NotPublished),
        (HttpResponse(503, None, "ups"), NotPublished),
        (problem(403, detail="forbidden"), NotPublished),
        (problem(403, "client-forbidden"), PermissionMissing),
        (problem(402, detail="Add credits"), QuotaExhausted),
        (problem(401), TokenRejected),
        ({"data": {}}, NotPublished),
    ],
)
async def test_si_falla_la_subida_con_certeza_no_salio(
    transport: FakeTransport, publisher: XPublisher, answer: object, error: type[Exception]
) -> None:
    transport.on("POST", "media/upload/initialize", answer)
    with pytest.raises(error) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Foto", media=(PHOTO,)))
    assert type(raised.value) is error
    assert all(call.path != "tweets" for call in transport.calls)


@pytest.mark.parametrize(
    ("answer", "certain"),
    [
        # Un 4xx es un rechazo: X no creó nada.
        (problem(403, detail="You are not allowed to create a Tweet with duplicate content."), True),
        (problem(400, "invalid-request", "text too long"), True),
        # Un 5xx o una respuesta sin id: no se sabe, y no se afirma que no salió.
        (HttpResponse(503, None, "ups"), False),
        (HttpResponse(201, {"data": {}}, ""), False),
    ],
)
async def test_al_crear_el_post_solo_un_rechazo_es_certeza(
    transport: FakeTransport, publisher: XPublisher, answer: HttpResponse, certain: bool
) -> None:
    transport.on("POST", "tweets", answer)
    with pytest.raises(ProviderError) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Hola"))
    refused_kind = raised.value.kind.value == "invalid_request"
    assert (isinstance(raised.value, NotPublished) or refused_kind) is certain


async def test_borrar(transport: FakeTransport, publisher: XPublisher) -> None:
    transport.on("DELETE", "tweets/100", {"data": {"deleted": True}})
    await publisher.delete(ACCOUNT, TOKEN, post_id="100")
    assert transport.calls[0].method == "DELETE"


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("Hola", media=(PHOTO,) * 4, options=XOptions()), ACCOUNT_LIMITS) == ()
    thread = Draft("Uno", thread=tuple(Draft(f"Parte {n}") for n in range(2, 26)))
    assert check_draft(thread, ACCOUNT_LIMITS) == ()
    # Una URL cuenta 23, mida lo que mida: entra aunque el texto pase de 280 letras.
    assert check_draft(Draft("x" * 250 + " https://ejemplo.com/" + "a" * 200), ACCOUNT_LIMITS) == ()
    problems = check_draft(Draft("x" * 281, media=(PHOTO, VIDEO), first_comment="primero"), ACCOUNT_LIMITS)
    assert [p.issue for p in problems] == [
        DraftIssue.TEXT_TOO_LONG,
        DraftIssue.MIXED_MEDIA,
        DraftIssue.FIRST_COMMENT_NOT_SUPPORTED,
    ]
    by_url = Draft("Hola", media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/a.jpg"),))
    assert [p.issue for p in check_draft(by_url, ACCOUNT_LIMITS)] == [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED]


def test_con_premium_el_limite_de_texto_es_el_de_la_configuracion(transport: FakeTransport) -> None:
    assert x_provider(config(), transport).spec is SPEC
    premium = x_provider(config(max_post_length=25_000), transport).spec
    assert premium is not None
    assert premium.publishing[X_ACCOUNT].max_text == 25_000
    assert check_draft(Draft("x" * 5000), premium.publishing[X_ACCOUNT]) == ()
