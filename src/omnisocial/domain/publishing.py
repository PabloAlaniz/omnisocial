"""Publicar: el borrador, los límites de cada red y el estado de una publicación."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

from typing_extensions import override

from omnisocial.domain.provider import ProviderId

# ── El borrador ─────────────────────────────────────────────────────────────────────────────────


class MediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class MediaFile(Protocol):
    """Un archivo que se sube a la red por partes. No hace falta tenerlo entero en memoria."""

    @property
    def size(self) -> int: ...

    @property
    def content_type(self) -> str:
        """`video/mp4`, `image/jpeg`…"""
        ...

    async def read(self, offset: int, length: int) -> bytes:
        """Hasta `length` bytes desde `offset`. Se puede pedir la misma parte más de una vez."""
        ...


@dataclass(frozen=True, slots=True)
class BytesFile:
    """Un `MediaFile` que ya está en memoria."""

    data: bytes = field(repr=False)
    content_type: str

    @property
    def size(self) -> int:
        return len(self.data)

    async def read(self, offset: int, length: int) -> bytes:
        return self.data[offset : offset + length]


@dataclass(frozen=True, slots=True)
class Media:
    """Una imagen o un video: una URL pública que la red va a buscar, o un archivo que se le sube.

    Cada red acepta una de las dos formas, o las dos: lo dicen sus límites.
    """

    kind: MediaKind
    url: str | None = None
    alt_text: str | None = None
    size_bytes: int | None = None
    """Si se conocen, el tamaño y la duración se validan antes de llamar a la red."""
    duration_seconds: float | None = None
    file: MediaFile | None = None

    def __post_init__(self) -> None:
        if (self.url is None) == (self.file is None):
            raise ValueError("Un medio es una URL o un archivo: uno de los dos, no ambos.")

    @property
    def public_url(self) -> str:
        if self.url is None:
            raise ValueError("Este medio es un archivo: no tiene URL.")
        return self.url

    @property
    def upload(self) -> MediaFile:
        if self.file is None:
            raise ValueError("Este medio es una URL: no hay archivo para subir.")
        return self.file

    @property
    def known_size(self) -> int | None:
        return self.file.size if self.file is not None else self.size_bytes


class PublishOptions:
    """Base de las opciones propias de una red (la privacidad de un video de TikTok, por ejemplo)."""


@dataclass(frozen=True, slots=True)
class Draft:
    text: str = ""
    media: tuple[Media, ...] = ()
    link: str | None = None
    first_comment: str | None = None
    """Un comentario propio que se publica apenas sale la publicación."""
    options: PublishOptions | None = None


# ── Los límites ─────────────────────────────────────────────────────────────────────────────────


class TextCount(StrEnum):
    """Cómo cuenta la red el largo del texto."""

    CHARACTERS = "characters"
    UTF16 = "utf16"
    """En unidades UTF-16: un emoji fuera del plano básico cuenta dos."""
    UTF8 = "utf8"
    """En bytes UTF-8: una letra con tilde cuenta dos."""


@dataclass(frozen=True, slots=True)
class PublishLimits:
    """Lo que un tipo de activo acepta al publicar. Lo declara cada red en su descripción."""

    max_text: int
    text_count: TextCount = TextCount.CHARACTERS
    max_images: int = 0
    max_videos: int = 0
    max_media: int | None = None
    """Tope de imágenes y videos sumados. `None`: alcanza con los topes de cada tipo."""
    mix_media: bool = False
    """Si acepta imágenes y videos en la misma publicación."""
    media_required: bool = False
    media_by_url: bool = True
    """Si toma los medios de una URL pública."""
    media_by_file: bool = False
    """Si acepta que se le suban archivos."""
    link: bool = False
    first_comment: bool = False
    delete: bool = False
    max_image_bytes: int | None = None
    max_video_bytes: int | None = None
    max_video_seconds: int | None = None
    options: type[PublishOptions] | None = None
    """El tipo de las opciones propias que entiende. `None`: no tiene."""


class DraftIssue(StrEnum):
    EMPTY = "empty"
    TEXT_TOO_LONG = "text_too_long"
    MEDIA_REQUIRED = "media_required"
    TOO_MANY_IMAGES = "too_many_images"
    TOO_MANY_VIDEOS = "too_many_videos"
    TOO_MANY_MEDIA = "too_many_media"
    MIXED_MEDIA = "mixed_media"
    MEDIA_URL_INVALID = "media_url_invalid"
    MEDIA_SOURCE_NOT_SUPPORTED = "media_source_not_supported"
    MEDIA_TOO_BIG = "media_too_big"
    VIDEO_TOO_LONG = "video_too_long"
    LINK_NOT_SUPPORTED = "link_not_supported"
    LINK_WITH_MEDIA = "link_with_media"
    FIRST_COMMENT_NOT_SUPPORTED = "first_comment_not_supported"
    WRONG_OPTIONS = "wrong_options"


@dataclass(frozen=True, slots=True)
class DraftProblem:
    issue: DraftIssue
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def text_length(text: str, count: TextCount) -> int:
    if count is TextCount.UTF16:
        return len(text.encode("utf-16-le")) // 2
    return len(text.encode()) if count is TextCount.UTF8 else len(text)


def public_https_url(url: str) -> bool:
    """Una URL que una red puede ir a buscar: https y con un nombre o una dirección públicos."""
    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme != "https" or not host or host == "localhost":
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host


def _text(draft: Draft, limits: PublishLimits) -> Iterator[DraftProblem]:
    if not draft.text.strip() and not draft.media and not draft.link:
        yield DraftProblem(DraftIssue.EMPTY, "El borrador está vacío.")
    length = text_length(draft.text, limits.text_count)
    if length > limits.max_text:
        yield DraftProblem(
            DraftIssue.TEXT_TOO_LONG, f"El texto mide {length} y el máximo es {limits.max_text}."
        )


def _media_count(draft: Draft, limits: PublishLimits) -> Iterator[DraftProblem]:
    images = sum(1 for m in draft.media if m.kind is MediaKind.IMAGE)
    videos = len(draft.media) - images
    if limits.media_required and not draft.media:
        yield DraftProblem(DraftIssue.MEDIA_REQUIRED, "Hace falta al menos una imagen o un video.")
    if images > limits.max_images:
        yield DraftProblem(
            DraftIssue.TOO_MANY_IMAGES, f"Hay {images} imágenes y el máximo es {limits.max_images}."
        )
    if videos > limits.max_videos:
        yield DraftProblem(
            DraftIssue.TOO_MANY_VIDEOS, f"Hay {videos} videos y el máximo es {limits.max_videos}."
        )
    if limits.max_media is not None and len(draft.media) > limits.max_media:
        yield DraftProblem(
            DraftIssue.TOO_MANY_MEDIA, f"Hay {len(draft.media)} medios y el máximo es {limits.max_media}."
        )
    if images and videos and not limits.mix_media:
        yield DraftProblem(DraftIssue.MIXED_MEDIA, "No se pueden mezclar imágenes y videos.")


def _each_media(draft: Draft, limits: PublishLimits) -> Iterator[DraftProblem]:
    for position, media in enumerate(draft.media, start=1):
        yield from _source(position, media, limits)
        top = limits.max_image_bytes if media.kind is MediaKind.IMAGE else limits.max_video_bytes
        size = media.known_size
        if top is not None and size is not None and size > top:
            yield DraftProblem(
                DraftIssue.MEDIA_TOO_BIG, f"El medio {position} pesa {size} bytes; máximo {top}."
            )
        seconds = limits.max_video_seconds
        if seconds is not None and media.duration_seconds is not None and media.duration_seconds > seconds:
            yield DraftProblem(
                DraftIssue.VIDEO_TOO_LONG, f"El medio {position} dura más de {seconds} segundos."
            )


def _source(position: int, media: Media, limits: PublishLimits) -> Iterator[DraftProblem]:
    by_url = media.url is not None
    if not (limits.media_by_url if by_url else limits.media_by_file):
        wanted = "un archivo para subir" if by_url else "una URL pública"
        yield DraftProblem(
            DraftIssue.MEDIA_SOURCE_NOT_SUPPORTED, f"El medio {position} tiene que ser {wanted}."
        )
    elif media.url is not None and not public_https_url(media.url):
        yield DraftProblem(
            DraftIssue.MEDIA_URL_INVALID, f"El medio {position} no tiene una URL https pública."
        )


def _extras(draft: Draft, limits: PublishLimits) -> Iterator[DraftProblem]:
    if draft.link is not None and not limits.link:
        yield DraftProblem(DraftIssue.LINK_NOT_SUPPORTED, "Este activo no acepta un link adjunto.")
    if draft.link is not None and draft.media:
        yield DraftProblem(
            DraftIssue.LINK_WITH_MEDIA, "Un link adjunto y medios no van juntos: el link va en el texto."
        )
    if draft.first_comment is not None and not limits.first_comment:
        yield DraftProblem(
            DraftIssue.FIRST_COMMENT_NOT_SUPPORTED, "Este activo no acepta un primer comentario."
        )
    if draft.options is not None and (
        limits.options is None or not isinstance(draft.options, limits.options)
    ):
        yield DraftProblem(DraftIssue.WRONG_OPTIONS, "Las opciones son de otra red o de otro tipo de activo.")


def check_draft(draft: Draft, limits: PublishLimits) -> tuple[DraftProblem, ...]:
    """Lo que impide publicar ese borrador en ese tipo de activo. Vacío si se puede. No llama a la red."""
    checks = (_text, _media_count, _each_media, _extras)
    return tuple(problem for check in checks for problem in check(draft, limits))


# ── La publicación ──────────────────────────────────────────────────────────────────────────────


class PublicationStatus(StrEnum):
    STARTED = "started"
    """Se reservó y se llamó a la red, pero no quedó registrado qué respondió. Si se la encuentra así
    después, está en duda: pudo haber salido. No se vuelve a publicar sola."""
    PENDING = "pending"
    """La red la está procesando. Se retoma con `check_publication`."""
    PUBLISHED = "published"
    PUBLISHED_WITH_ERROR = "published_with_error"
    """Salió, pero un paso posterior falló (el primer comentario, por ejemplo). No hay que repetirla."""
    FAILED = "failed"
    """La red la rechazó mientras la procesaba. No salió."""


FINAL_STATUSES = frozenset(
    {PublicationStatus.PUBLISHED, PublicationStatus.PUBLISHED_WITH_ERROR, PublicationStatus.FAILED}
)


@dataclass(frozen=True, slots=True)
class Outcome:
    """Lo que devuelve la red al publicar o al retomar una publicación."""

    status: PublicationStatus
    post_id: str | None = None
    url: str | None = None
    error: str | None = None
    resume: Mapping[str, str] = field(default_factory=dict)
    """Lo que el adaptador necesita para retomarla. Sin tokens: se guarda sin cifrar."""


@dataclass(frozen=True, slots=True)
class Publication:
    id: str
    asset_id: str
    owner: str
    provider: ProviderId
    status: PublicationStatus
    created_at: datetime
    updated_at: datetime
    idempotency_key: str | None = None
    post_id: str | None = None
    """El id de la publicación en la red, cuando ya salió."""
    url: str | None = None
    error: str | None = None
    resume: Mapping[str, str] = field(default_factory=dict)
    version: int = 1

    @property
    def is_final(self) -> bool:
        return self.status in FINAL_STATUSES

    def with_outcome(self, outcome: Outcome, now: datetime) -> Publication:
        return replace(
            self,
            status=outcome.status,
            post_id=outcome.post_id or self.post_id,
            url=outcome.url or self.url,
            error=outcome.error,
            resume=dict(outcome.resume),
            version=self.version + 1,
            updated_at=now,
        )
