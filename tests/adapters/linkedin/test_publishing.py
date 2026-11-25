"""Publicar en un perfil y en una página, con una API falsa."""

from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.linkedin.client import LinkedInClient
from omnisocial.adapters.providers.linkedin.config import LinkedInOptions
from omnisocial.adapters.providers.linkedin.publishing import LinkedInPublisher
from omnisocial.adapters.providers.linkedin.spec import MEMBER_LIMITS, ORGANIZATION_LIMITS
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
from tests.adapters.linkedin.conftest import MEMBER, ORGANIZATION, TOKEN, failure

POST_URN = "urn:li:share:7001"
CREATED = HttpResponse(201, {}, "", {"x-restli-id": POST_URN})
IMAGE_UPLOAD = "https://www.linkedin.com/dms-uploads/imagen-1"
PHOTO = Media(MediaKind.IMAGE, file=BytesFile(b"\x89PNG-datos", "image/png"), alt_text="El equipo")
OTHER = Media(MediaKind.IMAGE, file=BytesFile(b"JPEG-datos", "image/jpeg"))
VIDEO = Media(MediaKind.VIDEO, file=BytesFile(b"0123456789", "video/mp4"))


def image_started(number: int = 1) -> dict[str, object]:
    return {"value": {"uploadUrl": IMAGE_UPLOAD, "image": f"urn:li:image:{number}"}}


@pytest.fixture
def publisher(client: LinkedInClient) -> LinkedInPublisher:
    return LinkedInPublisher(client)


async def test_texto_como_persona(transport: FakeTransport, publisher: LinkedInPublisher) -> None:
    transport.on("POST", "posts", CREATED)
    outcome = await publisher.publish(MEMBER, TOKEN, draft=Draft("Hola (mundo) #novedad"))
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        POST_URN,
        "https://www.linkedin.com/feed/update/urn:li:share:7001/",
    )
    call = transport.calls[0]
    assert call.json == {
        "author": "urn:li:person:abc123",
        # Los paréntesis van escapados; el hashtag, no.
        "commentary": r"Hola \(mundo\) #novedad",
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    # Crear la publicación no es repetible: un reintento automático la duplicaría.
    assert call.retry_safe is None


async def test_las_opciones_propias_y_un_link(transport: FakeTransport, publisher: LinkedInPublisher) -> None:
    transport.on("POST", "posts", CREATED)
    options = LinkedInOptions(
        visibility="CONNECTIONS",
        link_title="Nuestro informe",
        link_description="Lo que aprendimos",
        reshare_disabled=True,
        little_text=True,
    )
    mention = "Con @[Mi Empresa](urn:li:organization:5515715)"
    await publisher.publish(
        MEMBER, TOKEN, draft=Draft(mention, link="https://ejemplo.com/informe", options=options)
    )
    body = transport.calls[0].json
    assert body is not None
    # Con `little_text` el texto se manda tal cual: la mención no se escapa.
    assert (body["commentary"], body["visibility"], body["isReshareDisabledByAuthor"]) == (
        mention,
        "CONNECTIONS",
        True,
    )
    assert body["content"] == {
        "article": {
            "source": "https://ejemplo.com/informe",
            "title": "Nuestro informe",
            "description": "Lo que aprendimos",
        }
    }
    transport.calls.clear()
    await publisher.publish(MEMBER, TOKEN, draft=Draft("mirá", link="https://ejemplo.com"))
    # LinkedIn no lee la página: sin título propio, queda la URL.
    assert transport.calls[0].json["content"] == {  # type: ignore[index]
        "article": {"source": "https://ejemplo.com", "title": "https://ejemplo.com"}
    }


async def test_una_imagen_como_pagina_con_primer_comentario(
    transport: FakeTransport, publisher: LinkedInPublisher
) -> None:
    transport.on("POST", "images", image_started())
    transport.on("PUT", IMAGE_UPLOAD, HttpResponse(201, None, ""))
    transport.on("POST", "posts", CREATED)
    transport.on("POST", "socialActions/urn%3Ali%3Ashare%3A7001/comments", HttpResponse(201, {}, ""))
    draft = Draft("Nuevo equipo", media=(PHOTO,), first_comment="Más info en el link.")
    outcome = await publisher.publish(ORGANIZATION, TOKEN, draft=draft)
    assert outcome.status is PublicationStatus.PUBLISHED
    started, upload, post, comment = transport.calls
    assert started.path == "images?action=initializeUpload"
    assert started.json == {"initializeUploadRequest": {"owner": "urn:li:organization:5515715"}}
    assert started.retry_safe
    # La subida de una imagen lleva el token.
    assert (upload.content, upload.headers) == (b"\x89PNG-datos", {"Authorization": "Bearer AQV-acceso"})
    assert post.json["content"] == {"media": {"id": "urn:li:image:1", "altText": "El equipo"}}  # type: ignore[index]
    assert comment.json == {
        "actor": "urn:li:organization:5515715",
        "object": POST_URN,
        "message": {"text": "Más info en el link."},
    }


async def test_varias_imagenes(transport: FakeTransport, publisher: LinkedInPublisher) -> None:
    transport.on("POST", "images", image_started(1), image_started(2))
    transport.on("PUT", IMAGE_UPLOAD, HttpResponse(201, None, ""))
    transport.on("POST", "posts", CREATED)
    await publisher.publish(ORGANIZATION, TOKEN, draft=Draft("Fotos", media=(PHOTO, OTHER)))
    assert transport.calls[-1].json["content"] == {  # type: ignore[index]
        "multiImage": {"images": [{"id": "urn:li:image:1", "altText": "El equipo"}, {"id": "urn:li:image:2"}]}
    }


async def test_un_video_se_sube_en_las_partes_que_dice_linkedin(
    transport: FakeTransport, publisher: LinkedInPublisher
) -> None:
    part_1, part_2 = (
        "https://www.linkedin.com/dms-uploads/video-1?p=1",
        "https://www.linkedin.com/dms-uploads/video-1?p=2",
    )
    started = {
        "value": {
            "video": "urn:li:video:55",
            "uploadToken": "",
            "uploadInstructions": [
                {"uploadUrl": part_1, "firstByte": 0, "lastByte": 5},
                {"uploadUrl": part_2, "firstByte": 6, "lastByte": 9},
            ],
        }
    }
    transport.on("POST", "videos?action=initializeUpload", started)
    transport.on("PUT", part_1, HttpResponse(200, None, "", {"ETag": "etag-1"}))
    transport.on("PUT", part_2, HttpResponse(200, None, "", {"etag": "etag-2"}))
    transport.on("POST", "videos?action=finalizeUpload", HttpResponse(200, {}, ""))
    transport.on("POST", "posts", CREATED)
    outcome = await publisher.publish(ORGANIZATION, TOKEN, draft=Draft("Video", media=(VIDEO,)))
    assert outcome.post_id == POST_URN
    init, first, second, finalize, post = transport.calls
    assert init.json == {
        "initializeUploadRequest": {
            "owner": "urn:li:organization:5515715",
            "fileSizeBytes": 10,
            "uploadCaptions": False,
            "uploadThumbnail": False,
        }
    }
    assert (first.content, second.content) == (b"012345", b"6789")
    # La subida de un video no lleva el token.
    assert first.headers == {"Content-Type": "application/octet-stream"}
    assert finalize.json == {
        "finalizeUploadRequest": {
            "video": "urn:li:video:55",
            "uploadToken": "",
            "uploadedPartIds": ["etag-1", "etag-2"],
        }
    }
    assert post.json["content"] == {"media": {"id": "urn:li:video:55"}}  # type: ignore[index]


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (TransportError("se cortó"), NotPublished),
        (HttpResponse(503, None, "ups"), NotPublished),
        (failure(403), NotPublished),
        (failure(403, "ACCESS_DENIED"), PermissionMissing),
        (failure(429, "TOO_MANY_REQUESTS"), RateLimited),
        (failure(401), TokenRejected),
        ({"value": {}}, NotPublished),
    ],
)
async def test_si_falla_la_subida_con_certeza_no_salio(
    transport: FakeTransport,
    publisher: LinkedInPublisher,
    answer: object,
    error: type[Exception],
) -> None:
    transport.on("POST", "images", answer)
    with pytest.raises(error) as raised:
        await publisher.publish(ORGANIZATION, TOKEN, draft=Draft("Foto", media=(PHOTO,)))
    assert type(raised.value) is error
    assert all(call.path != "posts" for call in transport.calls)


async def test_si_se_corta_al_mandar_el_archivo_tampoco_salio(
    transport: FakeTransport, publisher: LinkedInPublisher
) -> None:
    transport.on("POST", "images", image_started())
    transport.on("PUT", IMAGE_UPLOAD, HttpResponse(500, None, "ups"))
    with pytest.raises(NotPublished):
        await publisher.publish(ORGANIZATION, TOKEN, draft=Draft("Foto", media=(PHOTO,)))
    broken = {"value": {"video": "urn:li:video:55", "uploadInstructions": [{"uploadUrl": "https://x"}]}}
    transport.on("POST", "videos?action=initializeUpload", broken)
    with pytest.raises(NotPublished, match="sin sus datos"):
        await publisher.publish(ORGANIZATION, TOKEN, draft=Draft("Video", media=(VIDEO,)))
    transport.routes.clear()
    transport.on("POST", "videos?action=initializeUpload", {"value": {"video": "urn:li:video:55"}})
    with pytest.raises(NotPublished, match="dónde subir el video"):
        await publisher.publish(ORGANIZATION, TOKEN, draft=Draft("Video", media=(VIDEO,)))


@pytest.mark.parametrize(
    ("answer", "error", "certain"),
    [
        # Un 4xx es un rechazo: LinkedIn no creó nada.
        (failure(422, "UNPROCESSABLE_ENTITY", "contenido duplicado"), ProviderError, True),
        (failure(403), NotPublished, True),
        (failure(403, "ACCESS_DENIED"), PermissionMissing, True),
        # Un 5xx o una respuesta sin id: no se sabe, y no se afirma que no salió.
        (HttpResponse(503, None, "ups"), ProviderError, False),
        (HttpResponse(201, {}, ""), ProviderError, False),
    ],
)
async def test_al_crear_la_publicacion_solo_un_rechazo_es_certeza(
    transport: FakeTransport,
    publisher: LinkedInPublisher,
    answer: HttpResponse,
    error: type[Exception],
    certain: bool,
) -> None:
    transport.on("POST", "posts", answer)
    with pytest.raises(error) as raised:
        await publisher.publish(MEMBER, TOKEN, draft=Draft("Hola"))
    assert isinstance(raised.value, NotPublished) or type(raised.value) is error
    if not certain:
        assert not isinstance(raised.value, NotPublished)


async def test_si_el_primer_comentario_falla_la_publicacion_salio_igual(
    transport: FakeTransport, publisher: LinkedInPublisher
) -> None:
    transport.on("POST", "posts", CREATED)
    transport.on(
        "POST",
        "socialActions/urn%3Ali%3Ashare%3A7001/comments",
        failure(403, "ACCESS_DENIED", "falta el permiso"),
    )
    outcome = await publisher.publish(ORGANIZATION, TOKEN, draft=Draft("Hola", first_comment="primero"))
    assert (outcome.status, outcome.post_id) == (PublicationStatus.PUBLISHED_WITH_ERROR, POST_URN)
    assert "falta el permiso" in (outcome.error or "")


async def test_borrar_y_retomar(transport: FakeTransport, publisher: LinkedInPublisher) -> None:
    transport.on("DELETE", "posts/urn%3Ali%3Ashare%3A7001", HttpResponse(204, None, ""))
    await publisher.delete(ORGANIZATION, TOKEN, post_id=POST_URN)
    assert transport.calls[0].headers is not None
    assert transport.calls[0].headers["X-RestLi-Method"] == "DELETE"
    with pytest.raises(ProviderError, match="una sola etapa"):
        await publisher.resume(ORGANIZATION, TOKEN, resume={})


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("Hola", media=(PHOTO, OTHER), options=LinkedInOptions()), MEMBER_LIMITS) == ()
    assert check_draft(Draft("Hola", first_comment="primero"), ORGANIZATION_LIMITS) == ()
    # Como persona, el primer comentario pide un permiso restringido: no se ofrece.
    assert [p.issue for p in check_draft(Draft("Hola", first_comment="primero"), MEMBER_LIMITS)] == [
        DraftIssue.FIRST_COMMENT_NOT_SUPPORTED
    ]
    by_url = Draft("Hola", media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/a.jpg"),))
    assert [p.issue for p in check_draft(by_url, MEMBER_LIMITS)] == [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED]
    assert [p.issue for p in check_draft(Draft("x" * 3001), MEMBER_LIMITS)] == [DraftIssue.TEXT_TOO_LONG]
    assert MEMBER_LIMITS.delete
