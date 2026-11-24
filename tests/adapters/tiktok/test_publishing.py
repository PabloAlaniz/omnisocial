"""Publicar en TikTok, con una API falsa."""

from __future__ import annotations

import pytest

from omnisocial.adapters.providers.tiktok.client import TikTokClient
from omnisocial.adapters.providers.tiktok.config import TIKTOK, TIKTOK_ACCOUNT, TikTokOptions
from omnisocial.adapters.providers.tiktok.publishing import TikTokPublisher
from omnisocial.adapters.providers.tiktok.spec import ACCOUNT_LIMITS
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ErrorKind, ProviderError, QuotaExhausted, RateLimited
from omnisocial.domain.publishing import Draft, DraftIssue, Media, MediaKind, PublicationStatus, check_draft
from omnisocial.domain.token import Token, TokenKind
from omnisocial.testing import FakeTransport
from tests.adapters.tiktok.conftest import BASE, config, failure, ok

TOKEN = Token(TokenKind.USER, "act.1")
ACCOUNT = Asset("a1", "c1", TIKTOK, "dueño", TIKTOK_ACCOUNT, "oid-1")
VIDEO = Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/a.mp4")
PHOTO = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/a.jpg")
INIT_VIDEO = "post/publish/video/init/"
INIT_PHOTOS = "post/publish/content/init/"
STATUS = "post/publish/status/fetch/"


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport(base=BASE)


@pytest.fixture
def publisher(transport: FakeTransport) -> TikTokPublisher:
    return TikTokPublisher(TikTokClient(config(), transport))


async def test_un_video_queda_pendiente_y_en_privado_si_no_se_dice_otra_cosa(
    transport: FakeTransport, publisher: TikTokPublisher
) -> None:
    transport.on("POST", INIT_VIDEO, ok({"publish_id": "v_pub_1"}))
    outcome = await publisher.publish(ACCOUNT, TOKEN, draft=Draft("mi video", media=(VIDEO,)))
    assert (outcome.status, outcome.resume) == (PublicationStatus.PENDING, {"publish_id": "v_pub_1"})
    call = transport.calls[0]
    assert call.json == {
        "post_info": {
            "title": "mi video",
            "privacy_level": "SELF_ONLY",
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False,
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
        },
        "source_info": {"source": "PULL_FROM_URL", "video_url": VIDEO.url},
    }
    assert call.headers == {"Authorization": "Bearer act.1"}
    # Iniciar una publicación no es repetible: un reintento automático la duplicaría.
    assert call.retry_safe is None


async def test_las_opciones_propias(transport: FakeTransport, publisher: TikTokPublisher) -> None:
    transport.on("POST", INIT_VIDEO, ok({"publish_id": "v_pub_1"}))
    options = TikTokOptions(privacy_level="PUBLIC_TO_EVERYONE", disable_duet=True, brand_organic=True)
    await publisher.publish(ACCOUNT, TOKEN, draft=Draft("video", media=(VIDEO,), options=options))
    info = transport.calls[0].json["post_info"]  # type: ignore[index]
    assert (info["privacy_level"], info["disable_duet"], info["brand_organic_toggle"]) == (  # type: ignore[index]
        "PUBLIC_TO_EVERYONE",
        True,
        True,
    )


async def test_fotos(transport: FakeTransport, publisher: TikTokPublisher) -> None:
    transport.on("POST", INIT_PHOTOS, ok({"publish_id": "p_pub_1"}))
    text = "t" * 89 + "🎉 y sigue"
    await publisher.publish(ACCOUNT, TOKEN, draft=Draft(text, media=(PHOTO, PHOTO)))
    body = transport.calls[0].json
    assert body is not None
    info = body["post_info"]
    assert isinstance(info, dict)
    # El título admite 90 unidades UTF-16: el emoji (2) no entra después de 89 letras.
    assert info["title"] == "t" * 89
    assert info["description"] == text
    assert body["source_info"] == {
        "source": "PULL_FROM_URL",
        "photo_cover_index": 0,
        "photo_images": [PHOTO.url, PHOTO.url],
    }
    assert (body["post_mode"], body["media_type"]) == ("DIRECT_POST", "PHOTO")

    transport.calls.clear()
    titled = Draft("texto", media=(PHOTO,), options=TikTokOptions(photo_title="Mi título"))
    await publisher.publish(ACCOUNT, TOKEN, draft=titled)
    assert transport.calls[0].json["post_info"]["title"] == "Mi título"  # type: ignore[index]


@pytest.mark.parametrize(
    ("state", "status", "post_id", "error"),
    [
        ({"status": "PROCESSING_DOWNLOAD"}, PublicationStatus.PENDING, None, None),
        (
            {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7301]},
            PublicationStatus.PUBLISHED,
            "7301",
            None,
        ),
        # En privado sale, pero TikTok no informa el id.
        (
            {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": []},
            PublicationStatus.PUBLISHED,
            None,
            None,
        ),
        (
            {"status": "FAILED", "fail_reason": "video_pull_failed"},
            PublicationStatus.FAILED,
            None,
            "video_pull_failed",
        ),
        ({"status": "FAILED"}, PublicationStatus.FAILED, None, "sin motivo"),
    ],
)
async def test_retomar(
    transport: FakeTransport,
    publisher: TikTokPublisher,
    state: dict[str, object],
    status: PublicationStatus,
    post_id: str | None,
    error: str | None,
) -> None:
    transport.on("POST", STATUS, ok(state))
    outcome = await publisher.resume(ACCOUNT, TOKEN, resume={"publish_id": "v_pub_1"})
    assert (outcome.status, outcome.post_id) == (status, post_id)
    assert (error or "") in (outcome.error or "")
    if status is PublicationStatus.PENDING:
        assert outcome.resume == {"publish_id": "v_pub_1"}
    call = transport.calls[0]
    assert call.json == {"publish_id": "v_pub_1"}
    # Consultar el estado es una lectura: se puede repetir.
    assert call.retry_safe


async def test_respuestas_incompletas(transport: FakeTransport, publisher: TikTokPublisher) -> None:
    transport.on("POST", INIT_VIDEO, ok({}))
    with pytest.raises(ProviderError, match="id de la publicación"):
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("video", media=(VIDEO,)))
    with pytest.raises(ProviderError, match="retomar"):
        await publisher.resume(ACCOUNT, TOKEN, resume={})
    with pytest.raises(ProviderError, match="borrar"):
        await publisher.delete(ACCOUNT, TOKEN, post_id="7301")


@pytest.mark.parametrize(
    ("code", "error", "kind"),
    [
        ("spam_risk_too_many_posts", RateLimited, ErrorKind.RATE_LIMITED),
        ("reached_active_user_cap", QuotaExhausted, ErrorKind.QUOTA_EXHAUSTED),
        ("unaudited_client_can_only_post_to_private_accounts", ProviderError, ErrorKind.INVALID_REQUEST),
        ("url_ownership_unverified", ProviderError, ErrorKind.INVALID_REQUEST),
        ("invalid_param", ProviderError, ErrorKind.INVALID_REQUEST),
    ],
)
async def test_errores_al_publicar(
    transport: FakeTransport,
    publisher: TikTokPublisher,
    code: str,
    error: type[ProviderError],
    kind: ErrorKind,
) -> None:
    # Algunos vienen con HTTP 200: manda el código del sobre, no el estado.
    transport.on("POST", INIT_VIDEO, failure(code, "no"))
    with pytest.raises(error) as raised:
        await publisher.publish(ACCOUNT, TOKEN, draft=Draft("video", media=(VIDEO,)))
    assert raised.value.kind is kind


def test_los_limites_declarados() -> None:
    assert check_draft(Draft("video", media=(VIDEO,), options=TikTokOptions()), ACCOUNT_LIMITS) == ()
    assert check_draft(Draft("fotos", media=(PHOTO,) * 35), ACCOUNT_LIMITS) == ()
    problems = check_draft(Draft("x" * 2201, first_comment="primero"), ACCOUNT_LIMITS)
    assert [p.issue for p in problems] == [
        DraftIssue.TEXT_TOO_LONG,
        DraftIssue.MEDIA_REQUIRED,
        DraftIssue.FIRST_COMMENT_NOT_SUPPORTED,
    ]
    assert not ACCOUNT_LIMITS.delete
