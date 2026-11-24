"""Publicar posts e hilos en Bluesky, con una API falsa."""

from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.bluesky.client import BlueskyClient, iso
from omnisocial.adapters.providers.bluesky.config import BlueskyOptions
from omnisocial.adapters.providers.bluesky.publishing import BlueskyPublisher
from omnisocial.adapters.providers.bluesky.spec import ACCOUNT_LIMITS
from omnisocial.domain.errors import NotPublished, ProviderError, RateLimited, TokenRejected
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
from tests.adapters.bluesky.conftest import ACCOUNT, CREATE_RECORD, DID, TOKEN, UPLOAD, failure
from tests.fakes import NOW

PHOTO = Media(MediaKind.IMAGE, file=BytesFile(b"PNG-datos", "image/png"), alt_text="El equipo")
OTHER = Media(MediaKind.IMAGE, file=BytesFile(b"JPG-datos", "image/jpeg"))
VIDEO = Media(MediaKind.VIDEO, file=BytesFile(b"MP4-datos", "video/mp4"), alt_text="Un paseo")
BLOB = {"$type": "blob", "ref": {"$link": "bafk1"}, "mimeType": "image/png", "size": 9}


def created(number: int) -> dict[str, str]:
    return {"uri": f"at://{DID}/app.bsky.feed.post/3k{number}", "cid": f"cid-{number}"}


@pytest.fixture
def publisher(client: BlueskyClient) -> BlueskyPublisher:
    return BlueskyPublisher(client)


def records(transport: FakeTransport) -> list[dict[str, object]]:
    found = []
    for call in transport.calls:
        if call.path == CREATE_RECORD and call.json is not None:
            record = call.json["record"]
            assert isinstance(record, dict)
            found.append(record)
    return found


async def test_un_post_de_texto_con_su_link_marcado(
    transport: FakeTransport, publisher: BlueskyPublisher
) -> None:
    transport.on("POST", CREATE_RECORD, created(1))
    draft = Draft("Mirá https://ejemplo.com #novedad", options=BlueskyOptions(langs=("es",)))
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=draft)
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        f"at://{DID}/app.bsky.feed.post/3k1",
        f"https://bsky.app/profile/{DID}/post/3k1",
    )
    call = transport.calls[0]
    assert call.json is not None
    assert (call.json["repo"], call.json["collection"]) == (DID, "app.bsky.feed.post")
    [record] = records(transport)
    assert (record["$type"], record["text"], record["createdAt"], record["langs"]) == (
        "app.bsky.feed.post",
        "Mirá https://ejemplo.com #novedad",
        iso(NOW),
        ["es"],
    )
    # Sin marcarlos, el link y el hashtag quedarían como texto.
    marks = record["facets"]
    assert isinstance(marks, list)
    assert [mark["features"][0]["$type"].rsplit("#", 1)[-1] for mark in marks] == ["link", "tag"]
    # Crear un post no es repetible: un reintento automático lo duplicaría.
    assert call.retry_safe is None


async def test_imagenes_con_texto_alternativo(transport: FakeTransport, publisher: BlueskyPublisher) -> None:
    transport.on("POST", UPLOAD, {"blob": BLOB})
    transport.on("POST", CREATE_RECORD, created(1))
    await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Fotos", media=(PHOTO, OTHER)))
    first, second, _ = transport.calls
    assert (first.content, first.headers) == (
        b"PNG-datos",
        {"Authorization": "Bearer acceso-1", "Content-Type": "image/png"},
    )
    assert (second.content, first.retry_safe is not None) == (b"JPG-datos", True)
    [record] = records(transport)
    assert record["embed"] == {
        "$type": "app.bsky.embed.images",
        "images": [{"alt": "El equipo", "image": BLOB}, {"alt": "", "image": BLOB}],
    }


async def test_un_video_y_una_tarjeta_de_link(transport: FakeTransport, publisher: BlueskyPublisher) -> None:
    transport.on("POST", UPLOAD, {"blob": BLOB})
    transport.on("POST", CREATE_RECORD, created(1))
    await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Video", media=(VIDEO,)))
    assert records(transport)[0]["embed"] == {
        "$type": "app.bsky.embed.video",
        "video": BLOB,
        "alt": "Un paseo",
    }

    options = BlueskyOptions(link_title="Nuestro informe", link_description="Lo que aprendimos")
    await publisher.publish(
        ACCOUNT, TOKEN, draft=Draft("Leé", link="https://ejemplo.com/informe", options=options)
    )
    assert records(transport)[1]["embed"] == {
        "$type": "app.bsky.embed.external",
        "external": {
            "uri": "https://ejemplo.com/informe",
            "title": "Nuestro informe",
            "description": "Lo que aprendimos",
        },
    }
    await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Leé", link="https://ejemplo.com"))
    # Bluesky no lee la página: sin título propio, queda la URL.
    assert records(transport)[2]["embed"]["external"]["title"] == "https://ejemplo.com"  # type: ignore[index]


async def test_un_hilo_apunta_siempre_a_la_raiz_y_a_la_parte_anterior(
    transport: FakeTransport, publisher: BlueskyPublisher
) -> None:
    transport.on("POST", CREATE_RECORD, created(1), created(2), created(3))
    outcome = await publisher.publish(
        ACCOUNT, TOKEN, draft=Draft("Uno", thread=(Draft("Dos"), Draft("Tres")))
    )
    assert (outcome.status, outcome.post_id) == (PublicationStatus.PUBLISHED, created(1)["uri"])
    first, second, third = records(transport)
    assert "reply" not in first
    assert second["reply"] == {"root": created(1), "parent": created(1)}
    assert third["reply"] == {"root": created(1), "parent": created(2)}


async def test_responder_a_un_post_ajeno(transport: FakeTransport, publisher: BlueskyPublisher) -> None:
    root = {"uri": "at://did:plc:otra/app.bsky.feed.post/3kraiz", "cid": "cid-raiz"}
    parent = {
        "uri": "at://did:plc:otra/app.bsky.feed.post/3kpadre",
        "cid": "cid-padre",
        "record": {"reply": {"root": root}},
    }
    transport.on(
        "GET",
        "app.bsky.feed.getPosts",
        {"posts": [parent]},
        {"posts": [{"uri": root["uri"], "cid": "cid-raiz", "record": {}}]},
    )
    transport.on("POST", CREATE_RECORD, created(1))
    reply = Draft("Coincido", options=BlueskyOptions(reply_to=str(parent["uri"])))
    await publisher.publish(ACCOUNT, TOKEN, draft=reply)
    assert records(transport)[0]["reply"] == {
        "root": root,
        "parent": {"uri": parent["uri"], "cid": "cid-padre"},
    }
    # Si el post al que se responde es la raíz, raíz y padre son el mismo.
    await publisher.publish(
        ACCOUNT, TOKEN, draft=Draft("Coincido", options=BlueskyOptions(reply_to=root["uri"]))
    )
    assert records(transport)[1]["reply"] == {"root": root, "parent": root}


@pytest.mark.parametrize(
    "failure_at_second", [failure("InvalidRequest", message="texto inválido"), TransportError("se cortó")]
)
async def test_un_hilo_que_se_corta_ya_salio_en_parte(
    transport: FakeTransport, publisher: BlueskyPublisher, failure_at_second: HttpResponse | TransportError
) -> None:
    transport.on("POST", CREATE_RECORD, created(1), failure_at_second)
    outcome = await publisher.publish(
        ACCOUNT, TOKEN, draft=Draft("Uno", thread=(Draft("Dos"), Draft("Tres")))
    )
    assert (outcome.status, outcome.post_id) == (PublicationStatus.PUBLISHED_WITH_ERROR, created(1)["uri"])
    assert "cortado en la parte 2" in (outcome.error or "")
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (TransportError("se cortó"), NotPublished),
        (HttpResponse(503, None, "ups"), NotPublished),
        (failure("ExpiredToken"), NotPublished),
        ({"blob": {}}, NotPublished),
        (failure("BlobTooLarge", message="muy grande"), ProviderError),
        (failure("RateLimitExceeded", 429), RateLimited),
        (failure("InvalidToken"), TokenRejected),
    ],
)
async def test_si_falla_la_subida_con_certeza_no_salio(
    transport: FakeTransport, publisher: BlueskyPublisher, answer: object, error: type[Exception]
) -> None:
    transport.on("POST", UPLOAD, answer)
    with pytest.raises(error) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Foto", media=(PHOTO,)))
    assert type(raised.value) is error
    assert all(call.path != CREATE_RECORD for call in transport.calls)


@pytest.mark.parametrize(
    ("answer", "certain"),
    [
        (failure("InvalidRequest", message="registro inválido"), True),
        (failure("ExpiredToken"), True),
        # Un 5xx o una respuesta sin dirección: no se sabe, y no se afirma que no salió.
        (HttpResponse(503, None, "ups"), False),
        (HttpResponse(200, {"uri": "at://x/y/z"}, ""), False),
    ],
)
async def test_al_crear_el_post_solo_un_rechazo_es_certeza(
    transport: FakeTransport, publisher: BlueskyPublisher, answer: HttpResponse, certain: bool
) -> None:
    transport.on("POST", CREATE_RECORD, answer)
    with pytest.raises(ProviderError) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Hola"))
    refused_kind = raised.value.kind.value == "invalid_request"
    assert (isinstance(raised.value, NotPublished) or refused_kind) is certain


async def test_borrar_y_retomar(transport: FakeTransport, publisher: BlueskyPublisher) -> None:
    transport.on("POST", "com.atproto.repo.deleteRecord", {})
    await publisher.delete(ACCOUNT, TOKEN, post_id=created(1)["uri"])
    assert transport.calls[0].json == {"repo": DID, "collection": "app.bsky.feed.post", "rkey": "3k1"}
    with pytest.raises(ProviderError, match="una sola etapa"):
        await publisher.resume(ACCOUNT, TOKEN, resume={})


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("Hola", media=(PHOTO,) * 4, options=BlueskyOptions()), ACCOUNT_LIMITS) == ()
    assert check_draft(Draft("x" * 300, link="https://ejemplo.com"), ACCOUNT_LIMITS) == ()
    problems = check_draft(Draft("x" * 301, media=(PHOTO, VIDEO)), ACCOUNT_LIMITS)
    assert [p.issue for p in problems] == [DraftIssue.TEXT_TOO_LONG, DraftIssue.MIXED_MEDIA]
    big = Media(MediaKind.IMAGE, file=BytesFile(b"x" * 2_000_001, "image/png"))
    assert [p.issue for p in check_draft(Draft("Hola", media=(big,)), ACCOUNT_LIMITS)] == [
        DraftIssue.MEDIA_TOO_BIG
    ]
    by_url = Draft("Hola", media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/a.jpg"),))
    assert [p.issue for p in check_draft(by_url, ACCOUNT_LIMITS)] == [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED]
