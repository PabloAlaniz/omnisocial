"""Subir un video por partes, con una API falsa."""

from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.youtube.client import YouTubeClient
from omnisocial.adapters.providers.youtube.config import CHUNK_UNIT, YouTubeOptions
from omnisocial.adapters.providers.youtube.publishing import YouTubePublisher
from omnisocial.adapters.providers.youtube.spec import CHANNEL_LIMITS
from omnisocial.adapters.stores.memory import InMemoryQuotaLedger
from omnisocial.application.quota import QuotaBudget
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
from tests.adapters.youtube.conftest import CHANNEL, SESSION, TOKEN, UPLOAD_URL, config, failure
from tests.fakes import FakeClock

SIZE = 2 * CHUNK_UNIT + 100
DATA = bytes(range(256)) * (SIZE // 256) + bytes(SIZE % 256)
FILE = BytesFile(DATA, "video/mp4")
DRAFT = Draft("Receta de invierno\n\nPaso a paso.", media=(Media(MediaKind.VIDEO, file=FILE),))
OPENED = HttpResponse(200, None, "", {"Location": SESSION})
CREATED = HttpResponse(201, {"id": "vid-1", "status": {"uploadStatus": "uploaded"}}, "")


def received(last_byte: int) -> HttpResponse:
    return HttpResponse(308, None, "", {"Range": f"bytes=0-{last_byte}"})


@pytest.fixture
def publisher(transport: FakeTransport) -> YouTubePublisher:
    # Partes de 256 KB: el archivo de prueba entra en tres.
    return YouTubePublisher(YouTubeClient(config(upload_chunk_bytes=CHUNK_UNIT), transport))


def ranges(transport: FakeTransport) -> list[str]:
    return [(call.headers or {})["Content-Range"] for call in transport.calls if call.method == "PUT"]


async def test_subir_por_partes(transport: FakeTransport, publisher: YouTubePublisher) -> None:
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on("PUT", SESSION, received(CHUNK_UNIT - 1), received(2 * CHUNK_UNIT - 1), CREATED)
    options = YouTubeOptions(
        privacy_status="unlisted", made_for_kids=True, tags=("cocina",), category_id="26"
    )
    outcome = await publisher.publish(CHANNEL, TOKEN, draft=Draft(DRAFT.text, DRAFT.media, options=options))
    # El video ya existe, pero YouTube lo sigue procesando.
    assert (outcome.status, outcome.post_id, outcome.url, outcome.resume) == (
        PublicationStatus.PENDING,
        "vid-1",
        "https://www.youtube.com/watch?v=vid-1",
        {"video_id": "vid-1"},
    )
    opening = transport.calls[0]
    assert opening.params == {"uploadType": "resumable", "part": "snippet,status"}
    assert opening.json == {
        "snippet": {
            "title": "Receta de invierno",
            "description": "Receta de invierno\n\nPaso a paso.",
            "tags": ["cocina"],
            "categoryId": "26",
        },
        "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": True},
    }
    assert opening.headers == {
        "Authorization": "Bearer ya29.acceso",
        "X-Upload-Content-Length": str(SIZE),
        "X-Upload-Content-Type": "video/mp4",
    }
    assert ranges(transport) == [
        f"bytes 0-{CHUNK_UNIT - 1}/{SIZE}",
        f"bytes {CHUNK_UNIT}-{2 * CHUNK_UNIT - 1}/{SIZE}",
        f"bytes {2 * CHUNK_UNIT}-{SIZE - 1}/{SIZE}",
    ]
    sent = b"".join(call.content or b"" for call in transport.calls if call.method == "PUT")
    assert sent == DATA
    assert (transport.calls[1].headers or {})["Content-Type"] == "video/mp4"


async def test_el_titulo_y_la_privacidad_por_defecto(
    transport: FakeTransport, publisher: YouTubePublisher
) -> None:
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on("PUT", SESSION, CREATED)
    long_line = "t" * 150
    small = Media(MediaKind.VIDEO, file=BytesFile(b"video", "video/mp4"))
    await publisher.publish(CHANNEL, TOKEN, draft=Draft(f"\n{long_line}\nsegunda", media=(small,)))
    body = transport.calls[0].json
    assert body is not None
    assert body["snippet"] == {"title": "t" * 100, "description": f"\n{long_line}\nsegunda"}
    assert body["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    assert ranges(transport) == ["bytes 0-4/5"]
    transport.calls.clear()
    titled = Draft("descripción", media=(small,), options=YouTubeOptions(title="Mi título"))
    await publisher.publish(CHANNEL, TOKEN, draft=titled)
    assert transport.calls[0].json["snippet"]["title"] == "Mi título"  # type: ignore[index]


async def test_si_youtube_recibio_menos_se_sigue_desde_ahi(
    transport: FakeTransport, publisher: YouTubePublisher
) -> None:
    transport.on("POST", UPLOAD_URL, OPENED)
    half = CHUNK_UNIT // 2
    transport.on("PUT", SESSION, received(half - 1), received(CHUNK_UNIT + half - 1), CREATED)
    await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)
    assert ranges(transport) == [
        f"bytes 0-{CHUNK_UNIT - 1}/{SIZE}",
        f"bytes {half}-{CHUNK_UNIT + half - 1}/{SIZE}",
        f"bytes {CHUNK_UNIT + half}-{SIZE - 1}/{SIZE}",
    ]


async def test_una_parte_que_falla_se_retoma_preguntando_hasta_donde_llego(
    transport: FakeTransport, publisher: YouTubePublisher
) -> None:
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on(
        "PUT",
        SESSION,
        received(CHUNK_UNIT - 1),
        TransportError("se cortó"),  # la segunda parte no llega
        received(CHUNK_UNIT - 1),  # pregunta: sigue en la primera
        HttpResponse(503, None, "ups"),  # reintento: falla el servidor
        received(2 * CHUNK_UNIT - 1),  # pregunta: esta vez sí la había recibido
        CREATED,
    )
    outcome = await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)
    assert outcome.post_id == "vid-1"
    assert ranges(transport) == [
        f"bytes 0-{CHUNK_UNIT - 1}/{SIZE}",
        f"bytes {CHUNK_UNIT}-{2 * CHUNK_UNIT - 1}/{SIZE}",
        f"bytes */{SIZE}",
        f"bytes {CHUNK_UNIT}-{2 * CHUNK_UNIT - 1}/{SIZE}",
        f"bytes */{SIZE}",
        f"bytes {2 * CHUNK_UNIT}-{SIZE - 1}/{SIZE}",
    ]
    assert transport.calls[3].content == b""


async def test_si_se_pierde_la_respuesta_final_la_pregunta_trae_el_video(
    transport: FakeTransport, publisher: YouTubePublisher
) -> None:
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on(
        "PUT", SESSION, received(CHUNK_UNIT - 1), received(2 * CHUNK_UNIT - 1), TransportError("x"), CREATED
    )
    outcome = await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)
    assert outcome.post_id == "vid-1"
    assert ranges(transport)[-1] == f"bytes */{SIZE}"


async def test_una_subida_que_no_se_puede_retomar_con_certeza_no_salio(
    transport: FakeTransport, publisher: YouTubePublisher
) -> None:
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on("PUT", SESSION, received(CHUNK_UNIT - 1), TransportError("se cortó"))
    with pytest.raises(NotPublished, match="no se pudo retomar"):
        await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)
    # Tres intentos de la parte, con una pregunta entre cada uno.
    assert len(ranges(transport)) == 1 + 3 + 2


async def test_una_parte_que_nunca_avanza_no_se_reintenta_para_siempre(
    transport: FakeTransport, publisher: YouTubePublisher
) -> None:
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on("PUT", SESSION, HttpResponse(308, None, ""))
    with pytest.raises(NotPublished):
        await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)


async def test_la_sesion_vencida_corta_la_subida(
    transport: FakeTransport, publisher: YouTubePublisher
) -> None:
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on("PUT", SESSION, received(CHUNK_UNIT - 1), HttpResponse(404, None, "Not Found"))
    with pytest.raises(NotPublished, match="venció") as raised:
        await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)
    assert raised.value.status == 404
    transport.routes.clear()
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on("PUT", SESSION, failure("invalidVideoMetadata", 400, "archivo inválido"))
    with pytest.raises(NotPublished, match="archivo inválido"):
        await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)


async def test_en_la_ultima_parte_no_se_afirma_que_no_salio(
    transport: FakeTransport, publisher: YouTubePublisher
) -> None:
    """YouTube pudo haber creado el video: queda en duda en vez de arriesgar un duplicado."""
    done_two = [received(CHUNK_UNIT - 1), received(2 * CHUNK_UNIT - 1)]
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on("PUT", SESSION, *done_two, TransportError("se cortó"))
    with pytest.raises(ProviderError, match="no se sabe") as lost:
        await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)
    assert not isinstance(lost.value, NotPublished)

    transport.routes.clear()
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on("PUT", SESSION, *done_two, failure("forbidden", 403, "rechazado"))
    with pytest.raises(ProviderError, match="rechazado") as rejected:
        await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)
    assert not isinstance(rejected.value, NotPublished)

    transport.routes.clear()
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on("PUT", SESSION, *done_two, HttpResponse(200, {}, ""))
    with pytest.raises(ProviderError, match="no devolvió su id"):
        await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (failure("authError", 401), TokenRejected),
        (failure("insufficientPermissions"), PermissionMissing),
        (failure("quotaExceeded"), QuotaExhausted),
        (failure("invalidTitle", 400), ProviderError),
        # Lo que no dice por qué sigue siendo seguro: sin sesión no hay video.
        (failure("forbidden"), NotPublished),
        (HttpResponse(503, None, "ups"), NotPublished),
        (TransportError("sin red"), NotPublished),
        (HttpResponse(200, None, ""), NotPublished),
    ],
)
async def test_si_no_se_abre_la_sesion_con_certeza_no_salio(
    transport: FakeTransport,
    publisher: YouTubePublisher,
    answer: HttpResponse | TransportError,
    error: type[Exception],
) -> None:
    transport.on("POST", UPLOAD_URL, answer)
    with pytest.raises(error) as raised:
        await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)
    assert type(raised.value) is error
    assert transport.calls[0].retry_safe
    assert len(transport.calls) == 1


async def test_el_cupo_de_subidas_se_cuenta_aparte(transport: FakeTransport) -> None:
    ledger = InMemoryQuotaLedger()
    clock = FakeClock()
    client = YouTubeClient(
        config(),
        transport,
        units=QuotaBudget("u", 10, ledger, clock),
        uploads=QuotaBudget("s", 1, ledger, clock),
    )
    transport.on("POST", UPLOAD_URL, OPENED)
    transport.on("PUT", SESSION, CREATED)
    publisher = YouTubePublisher(client)
    await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)
    with pytest.raises(QuotaExhausted, match="subidas"):
        await publisher.publish(CHANNEL, TOKEN, draft=DRAFT)
    assert (await ledger.spent("s", "2026-11-23"), await ledger.spent("u", "2026-11-23")) == (1, 0)


@pytest.mark.parametrize(
    ("status", "outcome", "error"),
    [
        ({"uploadStatus": "uploaded"}, PublicationStatus.PENDING, None),
        ({"uploadStatus": "processed"}, PublicationStatus.PUBLISHED, None),
        ({"uploadStatus": "failed", "failureReason": "codec"}, PublicationStatus.FAILED, "codec"),
        ({"uploadStatus": "rejected", "rejectionReason": "duplicate"}, PublicationStatus.FAILED, "duplicate"),
        ({"uploadStatus": "deleted"}, PublicationStatus.FAILED, "sin motivo"),
    ],
)
async def test_retomar_dice_como_termino_el_procesamiento(
    transport: FakeTransport,
    publisher: YouTubePublisher,
    status: dict[str, str],
    outcome: PublicationStatus,
    error: str | None,
) -> None:
    transport.on("GET", "videos", {"items": [{"id": "vid-1", "status": status}]})
    result = await publisher.resume(CHANNEL, TOKEN, resume={"video_id": "vid-1"})
    assert result.status is outcome
    assert (error or "") in (result.error or "")
    assert transport.calls[0].params == {"part": "status", "id": "vid-1"}
    if outcome is not PublicationStatus.FAILED:
        assert result.post_id == "vid-1"


async def test_retomar_un_video_que_ya_no_esta(transport: FakeTransport, publisher: YouTubePublisher) -> None:
    transport.on("GET", "videos", {"items": []})
    gone = await publisher.resume(CHANNEL, TOKEN, resume={"video_id": "vid-1"})
    assert (gone.status, gone.post_id) == (PublicationStatus.FAILED, None)
    with pytest.raises(ProviderError, match="retomar"):
        await publisher.resume(CHANNEL, TOKEN, resume={})


async def test_borrar_un_video(transport: FakeTransport, publisher: YouTubePublisher) -> None:
    transport.on("DELETE", "videos", HttpResponse(204, None, ""))
    await publisher.delete(CHANNEL, TOKEN, post_id="vid-1")
    assert transport.calls[0].params == {"id": "vid-1"}


def test_los_limites_declarados() -> None:
    assert check_draft(Draft(DRAFT.text, DRAFT.media, options=YouTubeOptions()), CHANNEL_LIMITS) == ()
    by_url = Draft("x", media=(Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/a.mp4"),))
    assert [p.issue for p in check_draft(by_url, CHANNEL_LIMITS)] == [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED]
    # La descripción se mide en bytes: 2501 letras con tilde no entran en 5000.
    accented = Draft("á" * 2501, media=DRAFT.media)
    assert [p.issue for p in check_draft(accented, CHANNEL_LIMITS)] == [DraftIssue.TEXT_TOO_LONG]
    assert check_draft(Draft("á" * 2500, media=DRAFT.media), CHANNEL_LIMITS) == ()
    assert CHANNEL_LIMITS.delete
