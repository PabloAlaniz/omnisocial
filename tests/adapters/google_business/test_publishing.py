"""Publicar novedades en una sede, con una API falsa."""

from __future__ import annotations

from datetime import datetime

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.google_business.client import GoogleBusinessClient
from omnisocial.adapters.providers.google_business.config import GoogleBusinessOptions
from omnisocial.adapters.providers.google_business.publishing import GoogleBusinessPublisher
from omnisocial.adapters.providers.google_business.spec import LOCATION_LIMITS
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
from tests.adapters.google_business.conftest import LOCATION, LOCATION_NAME, POSTS, TOKEN, failure

NAME = f"{LOCATION_NAME}/localPosts/9"
LIVE = {"name": NAME, "state": "LIVE", "searchUrl": "https://local.google.com/place?id=1&lpsid=9"}
PHOTO = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/cafe.jpg")


@pytest.fixture
def publisher(client: GoogleBusinessClient) -> GoogleBusinessPublisher:
    return GoogleBusinessPublisher(client)


async def test_una_novedad_con_foto_y_boton(
    transport: FakeTransport, publisher: GoogleBusinessPublisher
) -> None:
    transport.on("POST", POSTS, LIVE)
    options = GoogleBusinessOptions(action="ORDER", action_url="https://cafecentral.ejemplo.com/pedir")
    outcome = await publisher.publish(
        LOCATION, TOKEN, draft=Draft("Nuevo menú de otoño", media=(PHOTO,), options=options)
    )
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        NAME,
        LIVE["searchUrl"],
    )
    call = transport.calls[0]
    assert call.json == {
        "languageCode": "es",
        "summary": "Nuevo menú de otoño",
        "topicType": "STANDARD",
        "media": [{"mediaFormat": "PHOTO", "sourceUrl": "https://cdn.ejemplo.com/cafe.jpg"}],
        "callToAction": {"actionType": "ORDER", "url": "https://cafecentral.ejemplo.com/pedir"},
    }
    # Crear una novedad no es repetible: un reintento automático la duplicaría.
    assert call.retry_safe is None


async def test_un_evento_una_oferta_y_el_boton_de_llamar(
    transport: FakeTransport, publisher: GoogleBusinessPublisher
) -> None:
    transport.on("POST", POSTS, LIVE)
    dates = {
        "event_title": "Noche de jazz",
        "starts_at": datetime(2026, 12, 5, 21, 30),  # noqa: DTZ001  # la hora de la sede, sin zona
        "ends_at": datetime(2026, 12, 6, 1, 0),  # noqa: DTZ001
    }
    event = GoogleBusinessOptions(topic="EVENT", action="CALL", language_code="en", **dates)  # type: ignore[arg-type]
    await publisher.publish(LOCATION, TOKEN, draft=Draft("Live music", options=event))
    body = transport.calls[0].json
    assert body is not None
    assert (body["languageCode"], body["topicType"], body["callToAction"]) == (
        "en",
        "EVENT",
        {"actionType": "CALL"},
    )
    assert body["event"] == {
        "title": "Noche de jazz",
        "schedule": {
            "startDate": {"year": 2026, "month": 12, "day": 5},
            "startTime": {"hours": 21, "minutes": 30},
            "endDate": {"year": 2026, "month": 12, "day": 6},
            "endTime": {"hours": 1, "minutes": 0},
        },
    }
    offer = GoogleBusinessOptions(
        topic="OFFER",
        coupon_code="OTOÑO",
        redeem_url="https://ejemplo.com/cupon",
        terms="Hasta agotar",
        **dates,  # type: ignore[arg-type]
    )
    await publisher.publish(LOCATION, TOKEN, draft=Draft("2x1 en café", options=offer))
    body = transport.calls[1].json
    assert body is not None
    assert body["offer"] == {
        "couponCode": "OTOÑO",
        "redeemOnlineUrl": "https://ejemplo.com/cupon",
        "termsConditions": "Hasta agotar",
    }
    assert "callToAction" not in body
    assert "event" in body
    # Sin opciones, una novedad común.
    await publisher.publish(LOCATION, TOKEN, draft=Draft("Abrimos los domingos"))
    assert transport.calls[2].json == {
        "languageCode": "es",
        "summary": "Abrimos los domingos",
        "topicType": "STANDARD",
    }


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"topic": "ALERT"}, "tipo de novedad"),
        ({"action": "GET_OFFER"}, "botón es uno"),
        ({"action": "SHOP"}, "lleva una URL"),
        ({"action": "CALL", "action_url": "https://ejemplo.com"}, "lleva una URL"),
        ({"topic": "EVENT", "event_title": "Sin fechas"}, "título, comienzo y fin"),
    ],
)
def test_las_opciones_que_google_no_aceptaria_no_se_arman(options: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        GoogleBusinessOptions(**options)  # type: ignore[arg-type]


async def test_una_novedad_en_revision_queda_pendiente(
    transport: FakeTransport, publisher: GoogleBusinessPublisher
) -> None:
    transport.on("POST", POSTS, {"name": NAME, "state": "PROCESSING"})
    transport.on(
        "GET", f"https://mybusiness.googleapis.com/v4/{NAME}", LIVE, {"name": NAME, "state": "REJECTED"}
    )
    outcome = await publisher.publish(LOCATION, TOKEN, draft=Draft("Hola"))
    assert (outcome.status, outcome.post_id, outcome.resume) == (
        PublicationStatus.PENDING,
        NAME,
        {"name": NAME},
    )
    done = await publisher.resume(LOCATION, TOKEN, resume=outcome.resume)
    assert (done.status, done.url) == (PublicationStatus.PUBLISHED, LIVE["searchUrl"])
    rejected = await publisher.resume(LOCATION, TOKEN, resume=outcome.resume)
    assert (rejected.status, rejected.error) == (PublicationStatus.FAILED, "Google rechazó la novedad.")
    with pytest.raises(ProviderError, match="retomar"):
        await publisher.resume(LOCATION, TOKEN, resume={})


@pytest.mark.parametrize(
    ("answer", "error", "certain"),
    [
        (failure(400, "INVALID_ARGUMENT"), ProviderError, True),
        (failure(400, "FAILED_PRECONDITION"), ProviderError, True),
        (failure(403, "PERMISSION_DENIED"), NotPublished, True),
        (failure(403, "PERMISSION_DENIED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"), PermissionMissing, True),
        (failure(429, "RESOURCE_EXHAUSTED"), RateLimited, True),
        (failure(401, "UNAUTHENTICATED"), TokenRejected, True),
        # Un 5xx o una respuesta sin nombre: no se sabe, y no se afirma que no salió.
        (HttpResponse(503, None, "ups"), ProviderError, False),
        ({"state": "LIVE"}, ProviderError, False),
    ],
)
async def test_solo_un_rechazo_es_certeza(
    transport: FakeTransport,
    publisher: GoogleBusinessPublisher,
    answer: object,
    error: type[Exception],
    certain: bool,
) -> None:
    transport.on("POST", POSTS, answer)
    with pytest.raises(error) as raised:
        await publisher.publish(LOCATION, TOKEN, draft=Draft("Hola"))
    assert type(raised.value) is error
    kind = getattr(raised.value, "kind", None)
    says_why = kind is not None and kind.value in {"invalid_request", "rate_limited", "missing_permission"}
    assert (isinstance(raised.value, NotPublished | TokenRejected) or says_why) is certain


async def test_borrar_una_novedad(transport: FakeTransport, publisher: GoogleBusinessPublisher) -> None:
    transport.on("DELETE", f"https://mybusiness.googleapis.com/v4/{NAME}", {})
    await publisher.delete(LOCATION, TOKEN, post_id=NAME)
    assert transport.calls[0].method == "DELETE"


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("x" * 1500, media=(PHOTO,) * 10), LOCATION_LIMITS) == ()
    file = Media(MediaKind.IMAGE, file=BytesFile(b"datos", "image/jpeg"))
    video = Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/v.mp4")
    problems = {
        "largo": Draft("x" * 1501),
        "archivo": Draft("hola", media=(file,)),
        "video": Draft("hola", media=(video,)),
        "link": Draft("hola", link="https://ejemplo.com"),
    }
    assert {
        name: [p.issue for p in check_draft(draft, LOCATION_LIMITS)] for name, draft in problems.items()
    } == {
        "largo": [DraftIssue.TEXT_TOO_LONG],
        "archivo": [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED],
        "video": [DraftIssue.TOO_MANY_VIDEOS],
        "link": [DraftIssue.LINK_NOT_SUPPORTED],
    }
