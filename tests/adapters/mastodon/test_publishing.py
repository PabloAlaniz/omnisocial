"""Publicar en Mastodon y en Pixelfed, con una API falsa."""

from __future__ import annotations

import json

import pytest

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.mastodon.client import MastodonClient
from omnisocial.adapters.providers.mastodon.config import MastodonOptions
from omnisocial.adapters.providers.mastodon.publishing import MastodonPublisher, multipart
from omnisocial.adapters.providers.mastodon.spec import MASTODON_LIMITS, PIXELFED_LIMITS
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
from tests.adapters.mastodon.conftest import ACCOUNT, TOKEN, failure
from tests.fakes import SequentialIds

STATUSES = "api/v1/statuses"
MEDIA = "api/v2/media"
PHOTO = Media(MediaKind.IMAGE, file=BytesFile(b"PNG-datos", "image/png"), alt_text="El equipo")
VIDEO = Media(MediaKind.VIDEO, file=BytesFile(b"MP4-datos", "video/mp4"))


def created(status_id: str) -> dict[str, str]:
    return {"id": status_id, "url": f"https://mastodon.social/@ana/{status_id}"}


@pytest.fixture
def publisher(client: MastodonClient) -> MastodonPublisher:
    return MastodonPublisher(client, SequentialIds("clave-"))


def bodies(transport: FakeTransport) -> list[object]:
    return [call.json for call in transport.calls if call.path == STATUSES]


async def test_una_publicacion_de_texto_lleva_su_clave_de_idempotencia(
    transport: FakeTransport, publisher: MastodonPublisher
) -> None:
    transport.on("POST", STATUSES, created("100"))
    options = MastodonOptions(visibility="unlisted", sensitive=True, spoiler_text="Spoiler", language="es")
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Hola fediverso", options=options))
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        "100",
        "https://mastodon.social/@ana/100",
    )
    call = transport.calls[0]
    assert call.json == {
        "visibility": "unlisted",
        "sensitive": True,
        "spoiler_text": "Spoiler",
        "language": "es",
        "status": "Hola fediverso",
    }
    assert call.headers == {"Authorization": "Bearer acceso-1", "Idempotency-Key": "clave-1"}
    # Con la clave, el servidor no la publica dos veces: el transporte la puede repetir.
    assert call.retry_safe


def test_el_formulario_de_una_subida() -> None:
    body = multipart("LIMITE", b"\x00\x01", "image/png", "Un gato")
    assert body == (
        b'--LIMITE\r\nContent-Disposition: form-data; name="file"; filename="media"\r\n'
        b"Content-Type: image/png\r\n\r\n\x00\x01\r\n"
        b'--LIMITE\r\nContent-Disposition: form-data; name="description"\r\n\r\nUn gato\r\n'
        b"--LIMITE--\r\n"
    )
    assert b"description" not in multipart("LIMITE", b"x", "image/png", None)


async def test_una_imagen_se_sube_y_se_adjunta(
    transport: FakeTransport, publisher: MastodonPublisher
) -> None:
    transport.on("POST", MEDIA, {"id": "m1", "url": "https://files/m1.png"})
    transport.on("POST", STATUSES, created("100"))
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Mirá", media=(PHOTO,)))
    assert outcome.status is PublicationStatus.PUBLISHED
    upload = transport.calls[0]
    assert upload.headers is not None
    assert upload.headers["Content-Type"] == "multipart/form-data; boundary=omnisocial-clave-1"
    assert upload.content is not None
    assert b"PNG-datos" in upload.content
    assert b"El equipo" in upload.content
    assert bodies(transport) == [{"visibility": "public", "status": "Mirá", "media_ids": ["m1"]}]


async def test_un_video_queda_pendiente_hasta_que_el_servidor_lo_procesa(
    transport: FakeTransport, publisher: MastodonPublisher
) -> None:
    transport.on("POST", MEDIA, HttpResponse(202, {"id": "v1", "url": None}, ""))
    draft = Draft("Video", media=(VIDEO,), thread=(Draft("Y sigue"),), options=MastodonOptions(reply_to="55"))
    pending = await publisher.publish(ACCOUNT, TOKEN, draft=draft)
    assert (pending.status, pending.resume["waiting"]) == (PublicationStatus.PENDING, "v1")
    # El plan guarda la clave de cada parte: retomar dos veces no publica dos veces.
    assert json.loads(pending.resume["plan"]) == [
        {"text": "Video", "media": ["v1"], "key": "clave-2"},
        {"text": "Y sigue", "media": [], "key": "clave-3"},
    ]
    assert bodies(transport) == []

    transport.on(
        "GET",
        "api/v1/media/v1",
        HttpResponse(206, {"id": "v1", "url": None}, ""),
        {"id": "v1", "url": "https://files/v1.mp4"},
    )
    still = await publisher.resume(ACCOUNT, TOKEN, resume=pending.resume)
    assert (still.status, still.resume) == (PublicationStatus.PENDING, pending.resume)
    transport.on("POST", STATUSES, created("100"), created("101"))
    done = await publisher.resume(ACCOUNT, TOKEN, resume=pending.resume)
    assert (done.status, done.post_id) == (PublicationStatus.PUBLISHED, "100")
    assert bodies(transport) == [
        {"visibility": "public", "status": "Video", "media_ids": ["v1"], "in_reply_to_id": "55"},
        {"visibility": "public", "status": "Y sigue", "in_reply_to_id": "100"},
    ]
    keys = [(call.headers or {}).get("Idempotency-Key") for call in transport.calls if call.path == STATUSES]
    assert keys == ["clave-2", "clave-3"]


async def test_retomar_cuando_el_servidor_no_pudo_o_rechaza(
    transport: FakeTransport, publisher: MastodonPublisher
) -> None:
    plan = json.dumps([{"text": "Video", "media": ["v1"], "key": "k1"}])
    resume = {"plan": plan, "waiting": "v1", "options": json.dumps({"visibility": "public", "reply_to": ""})}
    transport.on("GET", "api/v1/media/v1", failure(422, "Error processing thumbnail"))
    failed = await publisher.resume(ACCOUNT, TOKEN, resume=resume)
    assert failed.status is PublicationStatus.FAILED
    assert "thumbnail" in (failed.error or "")

    transport.routes.clear()
    transport.on("GET", "api/v1/media/v1", {"id": "v1"})
    transport.on("POST", STATUSES, failure(403, "Empty statuses are not allowed"))
    rejected = await publisher.resume(ACCOUNT, TOKEN, resume=resume)
    assert rejected.status is PublicationStatus.FAILED
    with pytest.raises(ProviderError, match="retomar"):
        await publisher.resume(ACCOUNT, TOKEN, resume={})


@pytest.mark.parametrize("failure_at_second", [failure(422, "Validation failed"), TransportError("se cortó")])
async def test_un_hilo_que_se_corta_ya_salio_en_parte(
    transport: FakeTransport, publisher: MastodonPublisher, failure_at_second: HttpResponse | TransportError
) -> None:
    transport.on("POST", STATUSES, created("100"), failure_at_second)
    outcome = await publisher.publish(
        ACCOUNT, TOKEN, draft=Draft("Uno", thread=(Draft("Dos"), Draft("Tres")))
    )
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED_WITH_ERROR,
        "100",
        "https://mastodon.social/@ana/100",
    )
    assert "cortado en la parte 2" in (outcome.error or "")
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (TransportError("se cortó"), NotPublished),
        (HttpResponse(503, None, "ups"), NotPublished),
        (failure(403, "raro"), NotPublished),
        ({"url": "sin id"}, NotPublished),
        (failure(422, "Validation failed: File content type is invalid"), ProviderError),
        (failure(403, "This action is outside the authorized scopes"), PermissionMissing),
        (failure(429, "Too many requests"), RateLimited),
        (failure(401, "The access token is invalid"), TokenRejected),
    ],
)
async def test_si_falla_la_subida_con_certeza_no_salio(
    transport: FakeTransport, publisher: MastodonPublisher, answer: object, error: type[Exception]
) -> None:
    transport.on("POST", MEDIA, answer)
    with pytest.raises(error) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Foto", media=(PHOTO,)))
    assert type(raised.value) is error
    assert bodies(transport) == []


@pytest.mark.parametrize(
    ("answer", "certain"),
    [
        (failure(422, "Validation failed: Text can't be blank"), True),
        (failure(403, "Empty statuses are not allowed"), True),
        # Un 5xx o una respuesta sin id: no se sabe, y no se afirma que no salió.
        (HttpResponse(503, None, "ups"), False),
        (HttpResponse(200, {"url": "x"}, ""), False),
    ],
)
async def test_al_crear_la_publicacion_solo_un_rechazo_es_certeza(
    transport: FakeTransport, publisher: MastodonPublisher, answer: HttpResponse, certain: bool
) -> None:
    transport.on("POST", STATUSES, answer)
    with pytest.raises(ProviderError) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Hola"))
    refused_kind = raised.value.kind.value == "invalid_request"
    assert (isinstance(raised.value, NotPublished) or refused_kind) is certain


async def test_borrar(transport: FakeTransport, publisher: MastodonPublisher) -> None:
    transport.on("DELETE", f"{STATUSES}/100", {"id": "100"})
    await publisher.delete(ACCOUNT, TOKEN, post_id="100")
    assert transport.calls[0].method == "DELETE"


def test_los_limites_de_cada_red() -> None:
    assert check_draft(Draft("Hola", media=(PHOTO,) * 4, options=MastodonOptions()), MASTODON_LIMITS) == ()
    assert check_draft(Draft("Uno", thread=(Draft("Dos"),)), MASTODON_LIMITS) == ()
    assert [p.issue for p in check_draft(Draft("x" * 501), MASTODON_LIMITS)] == [DraftIssue.TEXT_TOO_LONG]
    # Pixelfed es para fotos: sin medios no publica, y por defecto no acepta videos ni hilos.
    assert check_draft(Draft("Foto", media=(PHOTO,)), PIXELFED_LIMITS) == ()
    assert [p.issue for p in check_draft(Draft("Solo texto"), PIXELFED_LIMITS)] == [DraftIssue.MEDIA_REQUIRED]
    assert [p.issue for p in check_draft(Draft("Video", media=(VIDEO,)), PIXELFED_LIMITS)] == [
        DraftIssue.TOO_MANY_VIDEOS
    ]
    thread = Draft("Uno", media=(PHOTO,), thread=(Draft("Dos", media=(PHOTO,)),))
    assert [p.issue for p in check_draft(thread, PIXELFED_LIMITS)] == [DraftIssue.THREAD_NOT_SUPPORTED]
    by_url = Draft("Hola", media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/a.jpg"),))
    assert [p.issue for p in check_draft(by_url, MASTODON_LIMITS)] == [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED]
