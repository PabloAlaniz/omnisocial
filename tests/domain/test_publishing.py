from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from omnisocial.adapters.files import PathFile
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.publishing import (
    BytesFile,
    Draft,
    DraftIssue,
    Media,
    MediaKind,
    Outcome,
    Publication,
    PublicationStatus,
    PublishLimits,
    PublishOptions,
    TextCount,
    check_draft,
    public_https_url,
    text_length,
)
from omnisocial.domain.spec import NetworkSpec
from tests.fakes import NOW


@dataclass(frozen=True)
class Propias(PublishOptions):
    privado: bool = True


class Ajenas(PublishOptions):
    pass


IMAGE = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/a.jpg")
VIDEO = Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/a.mp4")
TEXT_ONLY = PublishLimits(max_text=10)
RICH = PublishLimits(
    max_text=10,
    max_images=2,
    max_videos=1,
    max_media=2,
    link=True,
    first_comment=True,
    max_image_bytes=100,
    max_video_bytes=1000,
    max_video_seconds=60,
    options=Propias,
)


def issues(draft: Draft, limits: PublishLimits) -> list[DraftIssue]:
    return [problem.issue for problem in check_draft(draft, limits)]


def test_un_borrador_que_entra() -> None:
    assert check_draft(Draft("hola"), TEXT_ONLY) == ()
    full = Draft("hola", media=(IMAGE, IMAGE), first_comment="primero", options=Propias())
    assert check_draft(full, RICH) == ()
    assert check_draft(Draft(link="https://ejemplo.com"), RICH) == ()


@pytest.mark.parametrize(
    ("draft", "limits", "issue"),
    [
        (Draft("   "), TEXT_ONLY, DraftIssue.EMPTY),
        (Draft("x" * 11), TEXT_ONLY, DraftIssue.TEXT_TOO_LONG),
        (
            Draft("hola"),
            PublishLimits(max_text=10, max_images=1, media_required=True),
            DraftIssue.MEDIA_REQUIRED,
        ),
        (Draft("hola", media=(IMAGE,)), TEXT_ONLY, DraftIssue.TOO_MANY_IMAGES),
        (Draft("hola", media=(VIDEO, VIDEO)), RICH, DraftIssue.TOO_MANY_VIDEOS),
        (
            Draft("hola", media=(IMAGE, IMAGE, IMAGE)),
            PublishLimits(max_text=10, max_images=5, max_media=2),
            DraftIssue.TOO_MANY_MEDIA,
        ),
        (Draft("hola", media=(IMAGE, VIDEO)), RICH, DraftIssue.MIXED_MEDIA),
        (
            Draft("hola", media=(Media(MediaKind.IMAGE, "http://cdn.ejemplo.com/a.jpg"),)),
            RICH,
            DraftIssue.MEDIA_URL_INVALID,
        ),
        (
            Draft("hola", media=(Media(MediaKind.IMAGE, IMAGE.url, size_bytes=101),)),
            RICH,
            DraftIssue.MEDIA_TOO_BIG,
        ),
        (
            Draft("hola", media=(Media(MediaKind.VIDEO, VIDEO.url, size_bytes=1001),)),
            RICH,
            DraftIssue.MEDIA_TOO_BIG,
        ),
        (
            Draft("hola", media=(Media(MediaKind.VIDEO, VIDEO.url, duration_seconds=61),)),
            RICH,
            DraftIssue.VIDEO_TOO_LONG,
        ),
        (Draft("hola", link="https://ejemplo.com"), TEXT_ONLY, DraftIssue.LINK_NOT_SUPPORTED),
        (Draft("hola", media=(IMAGE,), link="https://ejemplo.com"), RICH, DraftIssue.LINK_WITH_MEDIA),
        (Draft("hola", first_comment="primero"), TEXT_ONLY, DraftIssue.FIRST_COMMENT_NOT_SUPPORTED),
        (Draft("hola", options=Ajenas()), RICH, DraftIssue.WRONG_OPTIONS),
        (Draft("hola", options=Propias()), TEXT_ONLY, DraftIssue.WRONG_OPTIONS),
    ],
)
def test_lo_que_impide_publicar(draft: Draft, limits: PublishLimits, issue: DraftIssue) -> None:
    assert issues(draft, limits) == [issue]


def test_se_informan_todos_los_problemas_juntos() -> None:
    draft = Draft("x" * 11, media=(IMAGE,), first_comment="primero")
    assert issues(draft, TEXT_ONLY) == [
        DraftIssue.TEXT_TOO_LONG,
        DraftIssue.TOO_MANY_IMAGES,
        DraftIssue.FIRST_COMMENT_NOT_SUPPORTED,
    ]
    assert str(check_draft(draft, TEXT_ONLY)[0]) == "El texto mide 11 y el máximo es 10."


def test_las_mezclas_se_aceptan_si_el_activo_las_admite() -> None:
    carousel = PublishLimits(max_text=10, max_images=5, max_videos=5, mix_media=True)
    assert check_draft(Draft("hola", media=(IMAGE, VIDEO)), carousel) == ()


def test_el_largo_segun_como_cuenta_la_red() -> None:
    assert text_length("hola 🎉", TextCount.CHARACTERS) == 6
    assert text_length("hola 🎉", TextCount.UTF16) == 7
    assert issues(Draft("12345678 🎉"), PublishLimits(max_text=10, text_count=TextCount.UTF16)) == [
        DraftIssue.TEXT_TOO_LONG
    ]


@pytest.mark.parametrize(
    ("url", "public"),
    [
        ("https://cdn.ejemplo.com/a.jpg", True),
        ("https://8.8.8.8/a.jpg", True),
        ("http://cdn.ejemplo.com/a.jpg", False),
        ("https://localhost/a.jpg", False),
        ("https://interno/a.jpg", False),
        ("https://127.0.0.1/a.jpg", False),
        ("https://10.0.0.8/a.jpg", False),
        ("https://169.254.169.254/latest/meta-data", False),
        ("https://[::1]/a.jpg", False),
        ("a.jpg", False),
    ],
)
def test_solo_urls_https_publicas(url: str, public: bool) -> None:
    assert public_https_url(url) is public


def test_una_publicacion_avanza_con_lo_que_dice_la_red() -> None:
    started = Publication("pub-1", "a1", "dueño", ProviderId("red"), PublicationStatus.STARTED, NOW, NOW)
    assert not started.is_final
    pending = started.with_outcome(Outcome(PublicationStatus.PENDING, resume={"id": "9"}), NOW)
    assert (pending.status, pending.resume, pending.version) == (PublicationStatus.PENDING, {"id": "9"}, 2)
    done = pending.with_outcome(Outcome(PublicationStatus.PUBLISHED, post_id="p1", url="https://red/p1"), NOW)
    assert done.is_final
    assert (done.post_id, done.url, done.resume, done.version) == ("p1", "https://red/p1", {}, 3)


def test_un_activo_publica_si_y_solo_si_declara_sus_limites() -> None:
    red = ProviderId("red")
    publishing = frozenset({Capability.PUBLISHING})
    with pytest.raises(ValueError, match="límites"):
        NetworkSpec(id=red, name="Red", capabilities=publishing, assets={"cuenta": publishing})
    with pytest.raises(ValueError, match="límites"):
        NetworkSpec(
            id=red,
            name="Red",
            capabilities=publishing,
            assets={"cuenta": frozenset()},
            publishing={"cuenta": TEXT_ONLY},
        )


def test_un_medio_es_una_url_o_un_archivo() -> None:
    file = BytesFile(b"0123456789", "video/mp4")
    upload = Media(MediaKind.VIDEO, file=file)
    assert (upload.upload, upload.known_size, upload.url) == (file, 10, None)
    assert (IMAGE.public_url, IMAGE.known_size) == (IMAGE.url, None)
    with pytest.raises(ValueError, match="uno de los dos"):
        Media(MediaKind.VIDEO)
    with pytest.raises(ValueError, match="uno de los dos"):
        Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/a.mp4", file=file)
    with pytest.raises(ValueError, match="no tiene URL"):
        _ = upload.public_url
    with pytest.raises(ValueError, match="no hay archivo"):
        _ = IMAGE.upload


async def test_los_archivos_se_leen_de_a_partes(tmp_path: Path) -> None:
    in_memory = BytesFile(b"0123456789", "video/mp4")
    assert await in_memory.read(4, 3) == b"456"
    assert await in_memory.read(8, 100) == b"89"
    assert "0123" not in repr(in_memory)
    path = tmp_path / "video.mp4"
    path.write_bytes(b"0123456789")
    on_disk = PathFile.open(str(path), "video/mp4")
    assert (on_disk.size, on_disk.content_type) == (10, "video/mp4")
    assert await on_disk.read(4, 3) == b"456"
    assert await on_disk.read(8, 100) == b"89"


def test_cada_red_dice_de_donde_toma_los_medios() -> None:
    upload = Media(MediaKind.VIDEO, file=BytesFile(b"x" * 20, "video/mp4"))
    only_files = PublishLimits(
        max_text=10, max_videos=1, media_by_url=False, media_by_file=True, max_video_bytes=10
    )
    assert issues(Draft("hola", media=(VIDEO,)), only_files) == [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED]
    assert issues(Draft("hola", media=(upload,)), RICH) == [DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED]
    # El tamaño de un archivo se conoce: se valida sin que nadie lo declare.
    assert issues(Draft("hola", media=(upload,)), only_files) == [DraftIssue.MEDIA_TOO_BIG]


THREADS = PublishLimits(max_text=10, max_images=1, max_thread=2)


def test_un_hilo_se_valida_parte_por_parte() -> None:
    assert check_draft(Draft("uno", thread=(Draft("dos"), Draft("tres", media=(IMAGE,)))), THREADS) == ()
    assert issues(Draft("uno", thread=(Draft("dos"),)), TEXT_ONLY) == [DraftIssue.THREAD_NOT_SUPPORTED]
    long = Draft("uno", thread=(Draft("dos"), Draft("tres"), Draft("cuatro")))
    assert issues(long, THREADS) == [DraftIssue.THREAD_TOO_LONG]
    [problem] = check_draft(Draft("uno", thread=(Draft("dos"), Draft("x" * 11))), THREADS)
    assert (problem.issue, problem.part, problem.detail) == (
        DraftIssue.TEXT_TOO_LONG,
        3,
        "Parte 3: El texto mide 11 y el máximo es 10.",
    )
    # El problema de la primera parte no dice de qué parte es: es la 1.
    assert check_draft(Draft("x" * 11), THREADS)[0].part == 1


@pytest.mark.parametrize(
    "part",
    [Draft("dos", thread=(Draft("tres"),)), Draft("dos", first_comment="x"), Draft("dos", options=Propias())],
)
def test_las_partes_de_un_hilo_no_llevan_hilo_ni_comentario_ni_opciones(part: Draft) -> None:
    limits = PublishLimits(max_text=10, max_thread=3, first_comment=True, options=Propias)
    problems = check_draft(Draft("uno", thread=(part,)), limits)
    assert [(p.issue, p.part) for p in problems] == [(DraftIssue.THREAD_NOT_SUPPORTED, 2)]


@pytest.mark.parametrize(
    ("text", "length"),
    [
        ("hola", 4),
        ("año nuevo", 9),
        # Una URL cuenta 23, mida lo que mida.
        ("mirá https://ejemplo.com/una/ruta/muy/larga/que/no/termina/nunca?x=1", 5 + 23),
        ("a https://a.co b http://b.co", 5 + 23 + 23),
        # Los emojis y la escritura china, japonesa o coreana cuentan dos.
        ("hola 🎉", 5 + 2),
        ("日本語", 6),
        ("“comillas” — raya", 17),
    ],
)
def test_el_largo_con_peso(text: str, length: int) -> None:
    assert text_length(text, TextCount.WEIGHTED) == length
