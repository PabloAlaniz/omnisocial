"""Publicar pines con imágenes o con un video, con una API falsa."""

from __future__ import annotations

import base64
import json

import pytest

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.pinterest.client import PinterestClient
from omnisocial.adapters.providers.pinterest.config import PinterestOptions
from omnisocial.adapters.providers.pinterest.publishing import PinterestPublisher, multipart
from omnisocial.adapters.providers.pinterest.spec import ACCOUNT_LIMITS
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
from tests.adapters.pinterest.conftest import ACCOUNT, REGISTERED, TOKEN, UPLOAD_URL, failure
from tests.fakes import SequentialIds

BOARD = PinterestOptions(board_id="b1", title="Budín de limón", link="https://ejemplo.com/budin")
PHOTO = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/budin.jpg", alt_text="Un budín")
FILE = Media(MediaKind.IMAGE, file=BytesFile(b"PNG-datos", "image/png"))
VIDEO = Media(MediaKind.VIDEO, file=BytesFile(b"MP4-datos", "video/mp4"))
CREATED = HttpResponse(201, {"id": "p9"}, "")


@pytest.fixture
def publisher(client: PinterestClient) -> PinterestPublisher:
    return PinterestPublisher(client, SequentialIds("x"))


async def test_un_pin_con_una_imagen_por_url(transport: FakeTransport, publisher: PinterestPublisher) -> None:
    transport.on("POST", "pins", CREATED)
    outcome = await publisher.publish(
        ACCOUNT, TOKEN, draft=Draft("Fácil y rico", media=(PHOTO,), options=BOARD)
    )
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        "p9",
        "https://www.pinterest.com/pin/p9/",
    )
    call = transport.calls[0]
    assert call.json == {
        "board_id": "b1",
        "title": "Budín de limón",
        "description": "Fácil y rico",
        "link": "https://ejemplo.com/budin",
        "alt_text": "Un budín",
        "media_source": {"source_type": "image_url", "url": "https://cdn.ejemplo.com/budin.jpg"},
    }
    # Crear un pin no es repetible: un reintento automático lo duplicaría.
    assert (call.retry_safe, call.headers) == (None, {"Authorization": "Bearer pina-acceso"})


async def test_imagenes_como_archivo_y_carruseles(
    transport: FakeTransport, publisher: PinterestPublisher
) -> None:
    transport.on("POST", "pins", CREATED)
    options = PinterestOptions(board_id="b1", board_section_id="s1")
    await publisher.publish(ACCOUNT, TOKEN, draft=Draft("", media=(FILE,), options=options))
    encoded = base64.b64encode(b"PNG-datos").decode()
    assert transport.calls[0].json == {
        "board_id": "b1",
        "board_section_id": "s1",
        "media_source": {"source_type": "image_base64", "content_type": "image/png", "data": encoded},
    }
    await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Dos", media=(PHOTO, PHOTO), options=options))
    source = transport.calls[1].json["media_source"]  # type: ignore[index]
    assert source == {
        "source_type": "multiple_image_urls",
        "items": [{"url": PHOTO.url}, {"url": PHOTO.url}],
    }
    await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Dos", media=(FILE, FILE), options=options))
    assert transport.calls[2].json["media_source"]["source_type"] == "multiple_image_base64"  # type: ignore[index]
    with pytest.raises(ProviderError, match="todas") as mixed:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Dos", media=(PHOTO, FILE), options=options))
    assert mixed.value.kind.value == "invalid_request"
    assert len(transport.calls) == 3


async def test_un_video_se_sube_se_procesa_y_recien_ahi_sale(
    transport: FakeTransport, publisher: PinterestPublisher
) -> None:
    transport.on("POST", "media", HttpResponse(201, REGISTERED, ""))
    transport.on("POST", UPLOAD_URL, HttpResponse(204, None, ""))
    transport.on("GET", "media/m1", {"status": "processing"}, {"status": "succeeded"})
    transport.on("POST", "pins", CREATED)
    outcome = await publisher.publish(
        ACCOUNT, TOKEN, draft=Draft("Paso a paso", media=(VIDEO,), options=BOARD)
    )
    assert outcome.status is PublicationStatus.PENDING
    assert outcome.resume["media_id"] == "m1"
    # Lo que queda guardado para retomar no lleva el token.
    assert "pina-acceso" not in json.dumps(dict(outcome.resume))
    register, upload, _ = transport.calls
    assert (register.json, register.retry_safe is not None) == ({"media_type": "video"}, True)
    assert upload.headers == {"Content-Type": "multipart/form-data; boundary=omnisocial-x1"}
    assert upload.content == multipart(
        "omnisocial-x1",
        {"key": "uploads/m1", "policy": "abc", "x-amz-signature": "firma"},
        b"MP4-datos",
        "video/mp4",
    )
    assert upload.content is not None
    assert upload.content.index(b'name="key"') < upload.content.index(b'name="file"')

    done = await publisher.resume(ACCOUNT, TOKEN, resume=outcome.resume)
    assert (done.status, done.post_id) == (PublicationStatus.PUBLISHED, "p9")
    assert transport.calls[-1].json == {
        "board_id": "b1",
        "title": "Budín de limón",
        "description": "Paso a paso",
        "link": "https://ejemplo.com/budin",
        "media_source": {"source_type": "video_id", "media_id": "m1", "cover_image_key_frame_time": 0},
    }


async def test_la_portada_del_video_y_un_video_que_no_se_pudo_procesar(
    transport: FakeTransport, publisher: PinterestPublisher
) -> None:
    transport.on("POST", "media", HttpResponse(201, REGISTERED, ""))
    transport.on("POST", UPLOAD_URL, HttpResponse(204, None, ""))
    transport.on("GET", "media/m1", {"status": "succeeded"}, {"status": "failed"})
    transport.on("POST", "pins", CREATED)
    options = PinterestOptions(board_id="b1", cover_image_url="https://cdn.ejemplo.com/tapa.jpg")
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=Draft("", media=(VIDEO,), options=options))
    assert outcome.status is PublicationStatus.PUBLISHED
    assert transport.calls[-1].json["media_source"] == {  # type: ignore[index]
        "source_type": "video_id",
        "media_id": "m1",
        "cover_image_url": "https://cdn.ejemplo.com/tapa.jpg",
    }
    failed = await publisher.resume(ACCOUNT, TOKEN, resume={"media_id": "m1", "pin": "{}"})
    assert (failed.status, failed.post_id) == (PublicationStatus.FAILED, None)
    with pytest.raises(ProviderError, match="retomar"):
        await publisher.resume(ACCOUNT, TOKEN, resume={})


@pytest.mark.parametrize(
    ("step", "answer", "error"),
    [
        ("media", TransportError("se cortó"), NotPublished),
        ("media", HttpResponse(503, None, "ups"), NotPublished),
        ("media", HttpResponse(201, {"media_id": "m1"}, ""), NotPublished),
        ("media", failure(403, 29), PermissionMissing),
        ("media", failure(429, 8), RateLimited),
        ("media", failure(401, 2), TokenRejected),
        ("upload", HttpResponse(403, None, "AccessDenied"), NotPublished),
        ("upload", TransportError("se cortó"), NotPublished),
        ("status", TransportError("se cortó"), NotPublished),
        ("status", failure(401, 2), TokenRejected),
        ("status", HttpResponse(500, None, "ups"), NotPublished),
    ],
)
async def test_si_falla_antes_de_crear_el_pin_con_certeza_no_salio(
    transport: FakeTransport, publisher: PinterestPublisher, step: str, answer: object, error: type[Exception]
) -> None:
    routes = {
        "media": ("POST", "media", HttpResponse(201, REGISTERED, "")),
        "upload": ("POST", UPLOAD_URL, HttpResponse(204, None, "")),
        "status": ("GET", "media/m1", {"status": "succeeded"}),
    }
    for name, (method, path, fine) in routes.items():
        transport.on(method, path, answer if name == step else fine)
    with pytest.raises(error) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("", media=(VIDEO,), options=BOARD))
    assert type(raised.value) is error
    assert all(call.path != "pins" for call in transport.calls)


@pytest.mark.parametrize(
    ("answer", "certain"),
    [
        (failure(400, 1, "Invalid board"), True),
        (failure(403, 29), True),
        # Un 5xx o una respuesta sin id: no se sabe, y no se afirma que no salió.
        (HttpResponse(503, None, "ups"), False),
        (HttpResponse(201, {}, ""), False),
    ],
)
async def test_al_crear_el_pin_solo_un_rechazo_es_certeza(
    transport: FakeTransport, publisher: PinterestPublisher, answer: HttpResponse, certain: bool
) -> None:
    transport.on("POST", "pins", answer)
    with pytest.raises(ProviderError) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("", media=(PHOTO,), options=BOARD))
    says_why = raised.value.kind.value in {"invalid_request", "missing_permission"}
    assert (isinstance(raised.value, NotPublished) or says_why) is certain


async def test_borrar_y_publicar_sin_tablero(transport: FakeTransport, publisher: PinterestPublisher) -> None:
    transport.on("DELETE", "pins/p9", HttpResponse(204, None, ""))
    await publisher.delete(ACCOUNT, TOKEN, post_id="p9")
    assert transport.calls[0].method == "DELETE"
    with pytest.raises(ProviderError, match="tablero"):
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("", media=(PHOTO,)))


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("x" * 800, media=(PHOTO,) * 5, options=BOARD), ACCOUNT_LIMITS) == ()
    assert check_draft(Draft("", media=(VIDEO,), options=BOARD), ACCOUNT_LIMITS) == ()
    by_url = Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/v.mp4")
    problems = {
        "sin tablero": Draft("", media=(PHOTO,)),
        "sin medios": Draft("hola", options=BOARD),
        "video por URL": Draft("", media=(by_url,), options=BOARD),
        "largo": Draft("x" * 801, media=(PHOTO,), options=BOARD),
    }
    assert {
        name: [p.issue for p in check_draft(draft, ACCOUNT_LIMITS)] for name, draft in problems.items()
    } == {
        "sin tablero": [DraftIssue.OPTIONS_REQUIRED],
        "sin medios": [DraftIssue.MEDIA_REQUIRED],
        "video por URL": [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED],
        "largo": [DraftIssue.TEXT_TOO_LONG],
    }
