"""Publicar en páginas e Instagram, con una Graph API falsa."""

from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.meta.config import FACEBOOK_PAGE, INSTAGRAM_ACCOUNT, META
from omnisocial.adapters.providers.meta.graph import GraphClient
from omnisocial.adapters.providers.meta.publishing import MetaPublisher
from omnisocial.adapters.providers.meta.spec import INSTAGRAM_LIMITS, PAGE_LIMITS
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ProviderError, QuotaExhausted, RateLimited
from omnisocial.domain.publishing import Draft, Media, MediaKind, PublicationStatus, check_draft
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport
from tests.adapters.meta.conftest import BASE, config

VIDEO_BASE = "https://graph-video.facebook.com/v24.0/"
TOKEN = Token(TokenKind.ASSET, "tok-p1")
PAGE = Asset("a1", "c1", META, "dueño", FACEBOOK_PAGE, "p1")
INSTAGRAM = Asset("a2", "c1", META, "dueño", INSTAGRAM_ACCOUNT, "ig1")
IMAGE = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/a.jpg", alt_text="un gato")
OTHER = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/b.jpg")
VIDEO = Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/a.mp4")


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def publisher(transport: FakeTransport) -> MetaPublisher:
    return MetaPublisher(GraphClient(config(), transport))


def bodies(transport: FakeTransport) -> list[tuple[str, str, object]]:
    return [(call.method, call.path, call.json) for call in transport.calls]


# ── Página ──────────────────────────────────────────────────────────────────────────────────────


async def test_pagina_texto_con_link(transport: FakeTransport, publisher: MetaPublisher) -> None:
    transport.on("POST", "p1/feed", {"id": "p1_9"})
    outcome = await publisher.publish(PAGE, TOKEN, draft=Draft("hola", link="https://ejemplo.com"))
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        "p1_9",
        "https://www.facebook.com/p1_9",
    )
    call = transport.calls[0]
    # El contenido va en el cuerpo; en la URL solo el token y su firma.
    assert call.json == {"message": "hola", "link": "https://ejemplo.com"}
    assert set(call.params) == {"access_token", "appsecret_proof"}
    # Publicar no es repetible: un reintento automático duplicaría el post.
    assert call.retry_safe is None


async def test_pagina_una_foto(transport: FakeTransport, publisher: MetaPublisher) -> None:
    transport.on("POST", "p1/photos", {"id": "foto-1", "post_id": "p1_10"})
    outcome = await publisher.publish(PAGE, TOKEN, draft=Draft("mirá", media=(IMAGE,)))
    assert outcome.post_id == "p1_10"
    assert transport.calls[0].json == {"url": IMAGE.url, "alt_text_custom": "un gato", "caption": "mirá"}


async def test_pagina_varias_fotos(transport: FakeTransport, publisher: MetaPublisher) -> None:
    transport.on("POST", "p1/photos", {"id": "foto-1"}, {"id": "foto-2"})
    transport.on("POST", "p1/feed", {"id": "p1_11"})
    outcome = await publisher.publish(PAGE, TOKEN, draft=Draft("álbum", media=(IMAGE, OTHER)))
    assert outcome.post_id == "p1_11"
    assert bodies(transport) == [
        ("POST", "p1/photos", {"url": IMAGE.url, "alt_text_custom": "un gato", "published": "false"}),
        ("POST", "p1/photos", {"url": OTHER.url, "published": "false"}),
        (
            "POST",
            "p1/feed",
            {"message": "álbum", "attached_media": [{"media_fbid": "foto-1"}, {"media_fbid": "foto-2"}]},
        ),
    ]


async def test_pagina_un_video_va_al_servidor_de_videos(
    transport: FakeTransport, publisher: MetaPublisher
) -> None:
    transport.on("POST", f"{VIDEO_BASE}p1/videos", {"id": "video-1"})
    outcome = await publisher.publish(PAGE, TOKEN, draft=Draft("video", media=(VIDEO,)))
    assert outcome.post_id == "video-1"
    assert transport.calls[0].json == {"file_url": VIDEO.url, "description": "video"}


async def test_pagina_primer_comentario(transport: FakeTransport, publisher: MetaPublisher) -> None:
    transport.on("POST", "p1/feed", {"id": "p1_9"})
    transport.on("POST", "p1_9/comments", {"id": "com-1"})
    outcome = await publisher.publish(PAGE, TOKEN, draft=Draft("hola", first_comment="primero"))
    assert outcome.status is PublicationStatus.PUBLISHED
    assert transport.calls[1].json == {"message": "primero"}


async def test_si_el_primer_comentario_falla_la_publicacion_salio_igual(
    transport: FakeTransport, publisher: MetaPublisher
) -> None:
    transport.on("POST", "p1/feed", {"id": "p1_9"})
    transport.on("POST", "p1_9/comments", {"error": {"code": 200, "message": "falta el permiso"}}, status=403)
    outcome = await publisher.publish(PAGE, TOKEN, draft=Draft("hola", first_comment="primero"))
    assert (outcome.status, outcome.post_id) == (PublicationStatus.PUBLISHED_WITH_ERROR, "p1_9")
    assert "falta el permiso" in (outcome.error or "")


async def test_pagina_sin_id_en_la_respuesta(transport: FakeTransport, publisher: MetaPublisher) -> None:
    transport.on("POST", "p1/feed", {"success": True})
    with pytest.raises(ProviderError, match="id"):
        await publisher.publish(PAGE, TOKEN, draft=Draft("hola"))


async def test_borrar(transport: FakeTransport, publisher: MetaPublisher) -> None:
    transport.on("DELETE", "p1_9", {"success": True})
    await publisher.delete(PAGE, TOKEN, post_id="p1_9")
    assert transport.calls[0].method == "DELETE"


# ── Instagram ───────────────────────────────────────────────────────────────────────────────────


async def test_instagram_una_imagen_sale_enseguida(
    transport: FakeTransport, publisher: MetaPublisher
) -> None:
    transport.on("POST", "ig1/media", {"id": "cont-1"})
    transport.on("GET", "cont-1", {"status_code": "FINISHED"})
    transport.on("POST", "ig1/media_publish", {"id": "media-1"})
    transport.on("GET", "media-1", {"permalink": "https://www.instagram.com/p/abc/"})
    outcome = await publisher.publish(INSTAGRAM, TOKEN, draft=Draft("hola", media=(IMAGE,)))
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        "media-1",
        "https://www.instagram.com/p/abc/",
    )
    assert transport.calls[0].json == {"image_url": IMAGE.url, "alt_text": "un gato", "caption": "hola"}
    assert transport.calls[2].json == {"creation_id": "cont-1"}


async def test_instagram_un_video_es_un_reel_y_queda_pendiente(
    transport: FakeTransport, publisher: MetaPublisher
) -> None:
    transport.on("POST", "ig1/media", {"id": "cont-1"})
    transport.on("GET", "cont-1", {"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"})
    transport.on("POST", "ig1/media_publish", {"id": "media-1"})
    transport.on("GET", "media-1", HttpResponse(500, None, "ups"))
    transport.on("POST", "media-1/comments", {"id": "com-1"})
    draft = Draft("reel", media=(VIDEO,), first_comment="primero")
    pending = await publisher.publish(INSTAGRAM, TOKEN, draft=draft)
    assert pending.status is PublicationStatus.PENDING
    assert pending.resume == {"container": "cont-1", "first_comment": "primero"}
    assert transport.calls[0].json == {"video_url": VIDEO.url, "media_type": "REELS", "caption": "reel"}
    assert [c.path for c in transport.calls] == ["ig1/media", "cont-1"]

    done = await publisher.resume(INSTAGRAM, TOKEN, resume=pending.resume)
    # Sin permalink (la consulta falló) sigue siendo una publicación que salió.
    assert (done.status, done.post_id, done.url) == (PublicationStatus.PUBLISHED, "media-1", None)
    assert transport.calls[-1].json == {"message": "primero"}


async def test_instagram_carrusel(transport: FakeTransport, publisher: MetaPublisher) -> None:
    transport.on("POST", "ig1/media", {"id": "hijo-1"}, {"id": "hijo-2"}, {"id": "cont-1"})
    transport.on("GET", "cont-1", {"status_code": "IN_PROGRESS"})
    await publisher.publish(INSTAGRAM, TOKEN, draft=Draft("carrusel", media=(OTHER, VIDEO)))
    assert [call.json for call in transport.calls[:3]] == [
        {"image_url": OTHER.url, "is_carousel_item": "true"},
        {"video_url": VIDEO.url, "media_type": "VIDEO", "is_carousel_item": "true"},
        {"media_type": "CAROUSEL", "children": "hijo-1,hijo-2", "caption": "carrusel"},
    ]


@pytest.mark.parametrize(
    ("state", "status", "error"),
    [
        (
            {"status_code": "ERROR", "status": "Error: formato no soportado"},
            PublicationStatus.FAILED,
            "formato",
        ),
        ({"status_code": "EXPIRED"}, PublicationStatus.FAILED, "EXPIRED"),
        ({}, PublicationStatus.FAILED, "sin estado"),
        # Un intento anterior publicó y se perdió la respuesta: no se publica de nuevo.
        ({"status_code": "PUBLISHED"}, PublicationStatus.PUBLISHED_WITH_ERROR, "ya la había publicado"),
    ],
)
async def test_instagram_estados_del_contenedor(
    transport: FakeTransport,
    publisher: MetaPublisher,
    state: dict[str, object],
    status: PublicationStatus,
    error: str,
) -> None:
    transport.on("GET", "cont-1", state)
    outcome = await publisher.resume(INSTAGRAM, TOKEN, resume={"container": "cont-1"})
    assert outcome.status is status
    assert error in (outcome.error or "")
    assert [call.method for call in transport.calls] == ["GET"]


@pytest.mark.parametrize(
    "failure", [HttpResponse(500, {"error": {"code": 2, "message": "ups"}}, ""), TransportError("se cortó")]
)
async def test_instagram_si_falla_despues_de_armar_el_contenedor_queda_pendiente(
    publisher: MetaPublisher, transport: FakeTransport, failure: HttpResponse | TransportError
) -> None:
    """El contenedor ya existe: no hay que armar otro, alcanza con retomar."""
    transport.on("POST", "ig1/media", {"id": "cont-1"})
    transport.on("GET", "cont-1", failure)
    outcome = await publisher.publish(INSTAGRAM, TOKEN, draft=Draft("hola", media=(IMAGE,)))
    assert (outcome.status, outcome.resume) == (PublicationStatus.PENDING, {"container": "cont-1"})


async def test_instagram_sin_nada_que_retomar(publisher: MetaPublisher) -> None:
    with pytest.raises(ProviderError, match="retomar"):
        await publisher.resume(INSTAGRAM, TOKEN, resume={})


async def test_el_tope_diario_de_instagram_es_cuota_y_no_limite_de_uso(
    transport: FakeTransport, publisher: MetaPublisher
) -> None:
    quota = {"error": {"code": 9, "error_subcode": 2207042, "message": "tope de publicaciones"}}
    transport.on("POST", "ig1/media", quota, status=400)
    with pytest.raises(QuotaExhausted, match="tope"):
        await publisher.publish(INSTAGRAM, TOKEN, draft=Draft("hola", media=(IMAGE,)))
    transport.routes.clear()
    # Otro subcódigo del mismo código no se confunde con la cuota.
    transport.on(
        "POST", "ig1/media", {"error": {"code": 9, "error_subcode": 1, "message": "otro"}}, status=400
    )
    with pytest.raises(ProviderError) as raised:
        await publisher.publish(INSTAGRAM, TOKEN, draft=Draft("hola", media=(IMAGE,)))
    assert not isinstance(raised.value, QuotaExhausted | RateLimited)


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("hola", link="https://ejemplo.com", first_comment="primero"), PAGE_LIMITS) == ()
    assert check_draft(Draft("hola", media=(IMAGE, VIDEO)), INSTAGRAM_LIMITS) == ()
    assert check_draft(Draft("hola"), INSTAGRAM_LIMITS) != ()
    assert check_draft(Draft("hola", media=(IMAGE, VIDEO)), PAGE_LIMITS) != ()
    assert PAGE_LIMITS.delete
    assert not INSTAGRAM_LIMITS.delete
