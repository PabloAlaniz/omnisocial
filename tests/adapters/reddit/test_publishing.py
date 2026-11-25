"""Publicar en una comunidad, con una API falsa."""

from __future__ import annotations

import pytest

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.reddit.client import RedditClient
from omnisocial.adapters.providers.reddit.config import RedditOptions
from omnisocial.adapters.providers.reddit.publishing import RedditPublisher
from omnisocial.adapters.providers.reddit.spec import ACCOUNT_LIMITS
from omnisocial.domain.errors import (
    NotPublished,
    PermissionMissing,
    ProviderError,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.publishing import Draft, DraftIssue, Media, MediaKind, PublicationStatus, check_draft
from omnisocial.testing import FakeTransport
from tests.adapters.reddit.conftest import ACCOUNT, TOKEN, failure, refused

WHERE = RedditOptions(subreddit="r/argentina", title="Consulta sobre trámites")
CREATED = {
    "json": {
        "errors": [],
        "data": {
            "name": "t3_p9",
            "id": "p9",
            "url": "https://www.reddit.com/r/argentina/comments/p9/consulta_sobre_tramites/",
        },
    }
}


@pytest.fixture
def publisher(client: RedditClient) -> RedditPublisher:
    return RedditPublisher(client)


async def test_un_texto_en_una_comunidad(transport: FakeTransport, publisher: RedditPublisher) -> None:
    transport.on("POST", "api/submit", CREATED)
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=Draft("¿Alguien sabe?", options=WHERE))
    assert (outcome.status, outcome.post_id, outcome.url) == (
        PublicationStatus.PUBLISHED,
        "t3_p9",
        "https://www.reddit.com/r/argentina/comments/p9/consulta_sobre_tramites/",
    )
    call = transport.calls[0]
    assert call.form == {
        "sr": "argentina",
        "title": "Consulta sobre trámites",
        "kind": "self",
        "text": "¿Alguien sabe?",
        "nsfw": "false",
        "spoiler": "false",
        "sendreplies": "true",
        "resubmit": "true",
        "api_type": "json",
        "raw_json": "1",
    }
    # Publicar no es repetible: un reintento automático lo duplicaría.
    assert call.retry_safe is None


async def test_un_link_con_etiqueta(transport: FakeTransport, publisher: RedditPublisher) -> None:
    transport.on("POST", "api/submit", CREATED)
    options = RedditOptions(
        subreddit="argentina", title="Nota", flair_id="f1", flair_text="Noticia", nsfw=True, resubmit=False
    )
    await publisher.publish(
        ACCOUNT, TOKEN, draft=Draft("se ignora", link="https://ejemplo.com/nota", options=options)
    )
    form = transport.calls[0].form
    assert form is not None
    assert (
        form["kind"],
        form["url"],
        form["flair_id"],
        form["flair_text"],
        form["nsfw"],
        form["resubmit"],
    ) == (
        "link",
        "https://ejemplo.com/nota",
        "f1",
        "Noticia",
        "true",
        "false",
    )
    assert "text" not in form


@pytest.mark.parametrize(
    ("answer", "error", "certain"),
    [
        # Reddit responde 200 también cuando rechaza: el motivo viene en el cuerpo.
        (refused("SUBREDDIT_NOEXIST", "that subreddit doesn't exist"), ProviderError, True),
        (refused("NO_LINKS", "that subreddit only allows text posts"), ProviderError, True),
        (refused("RATELIMIT", "try again in 30 seconds"), RateLimited, True),
        (failure(403, "insufficient_scope"), PermissionMissing, True),
        (failure(403), NotPublished, True),
        (failure(401, "invalid_token"), TokenRejected, True),
        # Un 5xx o una respuesta sin id: no se sabe, y no se afirma que no salió.
        (HttpResponse(503, None, "ups"), ProviderError, False),
        ({"json": {"errors": [], "data": {}}}, ProviderError, False),
    ],
)
async def test_solo_un_rechazo_es_certeza(
    transport: FakeTransport,
    publisher: RedditPublisher,
    answer: object,
    error: type[Exception],
    certain: bool,
) -> None:
    transport.on("POST", "api/submit", answer)
    with pytest.raises(error) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Hola", options=WHERE))
    assert type(raised.value) is error
    kind = getattr(raised.value, "kind", None)
    says_why = kind is not None and kind.value in {"invalid_request", "rate_limited", "missing_permission"}
    assert (isinstance(raised.value, NotPublished | TokenRejected) or says_why) is certain


async def test_borrar_retomar_y_publicar_sin_destino(
    transport: FakeTransport, publisher: RedditPublisher
) -> None:
    transport.on("POST", "api/del", {})
    await publisher.delete(ACCOUNT, TOKEN, post_id="t3_p9")
    await publisher.delete(ACCOUNT, TOKEN, post_id="p9")
    assert [(call.form or {}).get("id") for call in transport.calls] == ["t3_p9", "t3_p9"]
    with pytest.raises(ProviderError, match="una sola etapa"):
        await publisher.resume(ACCOUNT, TOKEN, resume={})
    with pytest.raises(ProviderError, match="comunidad"):
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("Hola"))


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("x" * 40000, options=WHERE), ACCOUNT_LIMITS) == ()
    assert check_draft(Draft("", link="https://ejemplo.com", options=WHERE), ACCOUNT_LIMITS) == ()
    photo = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/a.jpg")
    problems = {
        "sin destino": Draft("hola"),
        "con imagen": Draft("hola", media=(photo,), options=WHERE),
        "vacío": Draft("", options=WHERE),
    }
    assert {
        name: [p.issue for p in check_draft(draft, ACCOUNT_LIMITS)] for name, draft in problems.items()
    } == {
        "sin destino": [DraftIssue.OPTIONS_REQUIRED],
        "con imagen": [DraftIssue.TOO_MANY_IMAGES],
        "vacío": [DraftIssue.EMPTY],
    }
