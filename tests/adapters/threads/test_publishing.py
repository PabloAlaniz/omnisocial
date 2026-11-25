"""Publicar posts e hilos en Threads, con una API falsa."""

from __future__ import annotations

import json

import pytest

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.threads.client import ThreadsClient
from omnisocial.adapters.providers.threads.config import ThreadsOptions
from omnisocial.adapters.providers.threads.publishing import ThreadsPublisher
from omnisocial.adapters.providers.threads.spec import ACCOUNT_LIMITS
from omnisocial.domain.errors import (
    NotPublished,
    PermissionMissing,
    ProviderError,
    RateLimited,
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
from tests.adapters.threads.conftest import ACCOUNT, TOKEN, failure

CREATE = "17841400000/threads"
PUBLISH = "17841400000/threads_publish"
IMAGE = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/a.jpg", alt_text="un gato")
VIDEO = Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/a.mp4")
PERMALINK = {"permalink": "https://www.threads.com/@mimarca/post/abc"}


@pytest.fixture
def publisher(client: ThreadsClient) -> ThreadsPublisher:
    return ThreadsPublisher(client)


def forms(transport: FakeTransport) -> list[dict[str, str]]:
    posts = [call for call in transport.calls if call.method == "POST"]
    return [{k: v for k, v in (call.form or {}).items() if k != "access_token"} for call in posts]


async def test_un_post_de_texto_sale_en_un_paso(
    transport: FakeTransport, publisher: ThreadsPublisher
) -> None:
    transport.on("POST", CREATE, {"id": "100"})
    transport.on("GET", "100", PERMALINK)
    options = ThreadsOptions(reply_control="followers_only", topic_tag="cocina")
    draft = Draft("Hola Threads", link="https://ejemplo.com", options=options)
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=draft)
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        "100",
        "https://www.threads.com/@mimarca/post/abc",
    )
    assert forms(transport) == [
        {
            "text": "Hola Threads",
            "reply_control": "followers_only",
            "topic_tag": "cocina",
            "media_type": "TEXT",
            "auto_publish_text": "true",
            "link_attachment": "https://ejemplo.com",
        }
    ]
    # Los datos van en el cuerpo, no en la URL; y publicar no es repetible.
    assert transport.calls[0].params == {}
    assert transport.calls[0].retry_safe is None


async def test_una_imagen_va_en_etapas(transport: FakeTransport, publisher: ThreadsPublisher) -> None:
    transport.on("POST", CREATE, {"id": "cont-1"})
    transport.on("GET", "cont-1", {"status": "IN_PROGRESS"}, {"status": "FINISHED"})
    pending = await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Mirá", media=(IMAGE,)))
    assert (pending.status, pending.post_id) == (PublicationStatus.PENDING, None)
    assert pending.resume["container"] == "cont-1"
    assert forms(transport) == [
        {"text": "Mirá", "media_type": "IMAGE", "image_url": IMAGE.url, "alt_text": "un gato"}
    ]

    transport.on("POST", PUBLISH, {"id": "100"})
    transport.on("GET", "100", HttpResponse(500, None, "ups"))
    done = await publisher.resume(ACCOUNT, TOKEN, resume=pending.resume)
    # Sin permalink (la consulta falló) sigue siendo un post que salió.
    assert (done.status, done.post_id, done.url) == (PublicationStatus.PUBLISHED, "100", None)
    assert forms(transport)[-1] == {"creation_id": "cont-1"}


async def test_un_carrusel(transport: FakeTransport, publisher: ThreadsPublisher) -> None:
    transport.on("POST", CREATE, {"id": "hijo-1"}, {"id": "hijo-2"}, {"id": "cont-1"})
    transport.on("GET", "cont-1", {"status": "IN_PROGRESS"})
    await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Carrusel", media=(IMAGE, VIDEO)))
    assert forms(transport) == [
        {"media_type": "IMAGE", "image_url": IMAGE.url, "alt_text": "un gato", "is_carousel_item": "true"},
        {"media_type": "VIDEO", "video_url": VIDEO.url, "is_carousel_item": "true"},
        {"text": "Carrusel", "media_type": "CAROUSEL", "children": "hijo-1,hijo-2"},
    ]


async def test_un_hilo_de_texto_encadena_cada_parte(
    transport: FakeTransport, publisher: ThreadsPublisher
) -> None:
    transport.on("POST", CREATE, {"id": "100"}, {"id": "101"}, {"id": "102"})
    transport.on("GET", "100", PERMALINK)
    draft = Draft(
        "Uno", thread=(Draft("Dos"), Draft("Tres")), options=ThreadsOptions(reply_to="55", topic_tag="x")
    )
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=draft)
    assert (outcome.status, outcome.post_id) == (PublicationStatus.PUBLISHED, "100")
    first, second, third = forms(transport)
    # El tema va solo en la primera parte; cada parte responde a la anterior.
    assert (first["reply_to_id"], first["topic_tag"]) == ("55", "x")
    assert (second["reply_to_id"], second["text"], "topic_tag" in second) == ("100", "Dos", False)
    assert third["reply_to_id"] == "101"


async def test_un_hilo_con_medios_espera_en_cada_parte(
    transport: FakeTransport, publisher: ThreadsPublisher
) -> None:
    transport.on("POST", CREATE, {"id": "100"}, {"id": "cont-2"})
    transport.on("GET", "cont-2", {"status": "IN_PROGRESS"}, {"status": "FINISHED"})
    draft = Draft("Uno", thread=(Draft("Dos", media=(VIDEO,)), Draft("Tres")))
    pending = await publisher.publish(ACCOUNT, TOKEN, draft=draft)
    # La primera parte ya salió; la segunda espera a Threads; la tercera todavía no se armó.
    assert (pending.status, pending.post_id) == (PublicationStatus.PENDING, "100")
    assert (pending.resume["index"], pending.resume["first"], pending.resume["previous"]) == (
        "1",
        "100",
        "100",
    )
    assert len(json.loads(pending.resume["plan"])) == 3

    transport.routes[("POST", CREATE)] = [HttpResponse(200, {"id": "102"}, "")]
    transport.on("POST", PUBLISH, {"id": "101"})
    transport.on("GET", "100", PERMALINK)
    done = await publisher.resume(ACCOUNT, TOKEN, resume=pending.resume)
    assert (done.status, done.post_id) == (PublicationStatus.PUBLISHED, "100")
    assert forms(transport)[-1] == {
        "text": "Tres",
        "reply_to_id": "101",
        "media_type": "TEXT",
        "auto_publish_text": "true",
    }


@pytest.mark.parametrize(
    "failure_at_second",
    [failure(100, "texto inválido"), TransportError("se cortó"), failure(190, status=401)],
)
async def test_un_hilo_que_se_corta_ya_salio_en_parte(
    transport: FakeTransport, publisher: ThreadsPublisher, failure_at_second: HttpResponse | TransportError
) -> None:
    transport.on("POST", CREATE, {"id": "100"}, failure_at_second)
    outcome = await publisher.publish(
        ACCOUNT, TOKEN, draft=Draft("Uno", thread=(Draft("Dos"), Draft("Tres")))
    )
    assert (outcome.status, outcome.post_id) == (PublicationStatus.PUBLISHED_WITH_ERROR, "100")
    assert "cortado en la parte 2" in (outcome.error or "")
    assert len(forms(transport)) == 2


@pytest.mark.parametrize(
    ("state", "first", "status", "error"),
    [
        (
            {"status": "ERROR", "error_message": "FAILED_DOWNLOADING_VIDEO"},
            "",
            PublicationStatus.FAILED,
            "FAILED_DOWNLOADING_VIDEO",
        ),
        ({"status": "EXPIRED"}, "", PublicationStatus.FAILED, "EXPIRED"),
        ({}, "", PublicationStatus.FAILED, "sin estado"),
        # Con el comienzo del hilo ya publicado, no es un fracaso: quedó cortado.
        (
            {"status": "ERROR", "error_message": "UNKNOWN"},
            "100",
            PublicationStatus.PUBLISHED_WITH_ERROR,
            "cortado en la parte 2",
        ),
        # Un intento anterior publicó y se perdió la respuesta: no se publica de nuevo.
        (
            {"status": "PUBLISHED"},
            "",
            PublicationStatus.PUBLISHED_WITH_ERROR,
            "ya había publicado la parte 2",
        ),
    ],
)
async def test_estados_del_contenedor(
    transport: FakeTransport,
    publisher: ThreadsPublisher,
    state: dict[str, object],
    first: str,
    status: PublicationStatus,
    error: str,
) -> None:
    plan = json.dumps([{"text": "Uno", "link": "", "media": []}, {"text": "Dos", "link": "", "media": []}])
    resume = {"plan": plan, "index": "1", "previous": first, "first": first, "container": "cont-2"}
    transport.on("GET", "cont-2", state)
    outcome = await publisher.resume(ACCOUNT, TOKEN, resume=resume)
    assert outcome.status is status
    assert error in (outcome.error or "")
    assert forms(transport) == []


async def test_si_no_se_puede_consultar_el_estado_queda_pendiente(
    transport: FakeTransport, publisher: ThreadsPublisher
) -> None:
    """El contenedor ya existe: no hay que armar otro, alcanza con retomar."""
    transport.on("POST", CREATE, {"id": "cont-1"})
    transport.on("GET", "cont-1", TransportError("se cortó"))
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Mirá", media=(IMAGE,)))
    assert (outcome.status, outcome.resume["container"]) == (PublicationStatus.PENDING, "cont-1")
    with pytest.raises(ProviderError, match="retomar"):
        await publisher.resume(ACCOUNT, TOKEN, resume={})


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (TransportError("se cortó"), NotPublished),
        (HttpResponse(503, None, "ups"), NotPublished),
        (failure(999, "raro", status=403), NotPublished),
        ({"success": True}, NotPublished),
        (failure(10, status=403), PermissionMissing),
        (failure(4), RateLimited),
        (failure(190, status=401), TokenRejected),
    ],
)
async def test_si_no_se_arma_la_primera_parte_con_certeza_no_salio(
    transport: FakeTransport, publisher: ThreadsPublisher, answer: object, error: type[Exception]
) -> None:
    transport.on("POST", CREATE, answer)
    with pytest.raises(error) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Hola"))
    assert type(raised.value) is error


@pytest.mark.parametrize(
    ("answer", "certain"),
    [
        (failure(100, "rechazado"), True),
        (failure(999, "raro", status=403), True),
        # Un 5xx o una respuesta sin id: no se sabe, y no se afirma que no salió.
        (HttpResponse(503, None, "ups"), False),
        (HttpResponse(200, {}, ""), False),
    ],
)
async def test_al_publicar_el_contenedor_solo_un_rechazo_es_certeza(
    transport: FakeTransport, publisher: ThreadsPublisher, answer: HttpResponse, certain: bool
) -> None:
    transport.on("POST", CREATE, {"id": "cont-1"})
    transport.on("GET", "cont-1", {"status": "FINISHED"})
    transport.on("POST", PUBLISH, answer)
    with pytest.raises(ProviderError) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Mirá", media=(IMAGE,)))
    refused_kind = raised.value.kind.value == "invalid_request"
    assert (isinstance(raised.value, NotPublished) or refused_kind) is certain


async def test_borrar(transport: FakeTransport, publisher: ThreadsPublisher) -> None:
    transport.on("DELETE", "100", {"success": True, "deleted_id": "100"})
    await publisher.delete(ACCOUNT, TOKEN, post_id="100")
    assert transport.calls[0].method == "DELETE"


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("Hola", media=(IMAGE, VIDEO), options=ThreadsOptions()), ACCOUNT_LIMITS) == ()
    assert check_draft(Draft("Hola", link="https://ejemplo.com"), ACCOUNT_LIMITS) == ()
    assert check_draft(Draft("á" * 500), ACCOUNT_LIMITS) == ()
    # Los emojis cuentan por sus bytes: 125 emojis ya son 500.
    assert check_draft(Draft("🎉" * 125), ACCOUNT_LIMITS) == ()
    assert [p.issue for p in check_draft(Draft("🎉" * 126), ACCOUNT_LIMITS)] == [DraftIssue.TEXT_TOO_LONG]
    by_file = Draft("Hola", media=(Media(MediaKind.IMAGE, file=BytesFile(b"x", "image/png")),))
    assert [p.issue for p in check_draft(by_file, ACCOUNT_LIMITS)] == [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED]
    assert [p.issue for p in check_draft(Draft("Hola", first_comment="x"), ACCOUNT_LIMITS)] == [
        DraftIssue.FIRST_COMMENT_NOT_SUPPORTED
    ]
