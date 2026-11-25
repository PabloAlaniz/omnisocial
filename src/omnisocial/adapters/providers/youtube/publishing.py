"""Subir un video a YouTube con el protocolo de subida reanudable.

1. Se abre una sesión con los datos del video. YouTube responde con la URL de la sesión.
2. El archivo se manda por partes a esa URL. Después de cada parte YouTube dice hasta dónde recibió.
3. Si una parte falla, se le pregunta a la sesión hasta dónde llegó y se sigue desde ahí.
4. Con la última parte YouTube crea el video y lo empieza a procesar.

Mientras no se mandó la última parte no existe ningún video: si la subida se abandona, con certeza no salió
(`NotPublished`). Si lo que se pierde es la respuesta a la última parte, no se sabe, y se dice así.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.youtube.client import (
    YouTubeClient,
    api_error,
    as_dict,
    as_list,
    as_str,
    bearer,
)
from omnisocial.adapters.providers.youtube.config import YOUTUBE, YouTubeOptions
from omnisocial.application.ports import Publisher
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ErrorKind, NotPublished, ProviderError, TokenRejected
from omnisocial.domain.publishing import Draft, MediaFile, Outcome, PublicationStatus
from omnisocial.domain.token import Token

_VIDEO_ID = "video_id"
_TITLE_MAX = 100
_RESUME_INCOMPLETE = 308
_CLIENT_ERROR = 400
_SERVER_ERROR = 500
_NOT_FOUND = 404
_RANGE = re.compile(r"bytes=0-(\d+)")

# Errores que ya dicen por qué no salió: el núcleo los traduce a su propia negativa.
_SAYS_WHY = frozenset(
    {
        ErrorKind.MISSING_PERMISSION,
        ErrorKind.RATE_LIMITED,
        ErrorKind.QUOTA_EXHAUSTED,
        ErrorKind.INVALID_REQUEST,
    }
)

# Estados de un video recién subido.
_PROCESSED = "processed"
_STILL_UPLOADING = "uploaded"


def _title(draft: Draft, options: YouTubeOptions) -> str:
    title = options.title or next((line.strip() for line in draft.text.splitlines() if line.strip()), "")
    return title[:_TITLE_MAX]


def _metadata(draft: Draft, options: YouTubeOptions) -> dict[str, object]:
    snippet: dict[str, object] = {"title": _title(draft, options), "description": draft.text}
    if options.tags:
        snippet["tags"] = list(options.tags)
    if options.category_id:
        snippet["categoryId"] = options.category_id
    status = {"privacyStatus": options.privacy_status, "selfDeclaredMadeForKids": options.made_for_kids}
    return {"snippet": snippet, "status": status}


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True, slots=True)
class _Upload:
    session: str
    file: MediaFile
    token: str


class YouTubePublisher(Publisher):
    def __init__(self, client: YouTubeClient) -> None:
        self._client = client

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options if isinstance(draft.options, YouTubeOptions) else YouTubeOptions()
        file = draft.media[0].upload
        await self._client.spend_upload()
        session = await self._open_session(token.access_token, file, _metadata(draft, options))
        video_id = await self._send(_Upload(session, file, token.access_token))
        # El video ya existe; YouTube lo sigue procesando.
        return Outcome(
            PublicationStatus.PENDING,
            post_id=video_id,
            url=_watch_url(video_id),
            resume={_VIDEO_ID: video_id},
        )

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        video_id = resume.get(_VIDEO_ID)
        if not video_id:
            raise ProviderError(YOUTUBE, "La publicación no tiene nada para retomar.")
        data = await self._client.get("videos", token.access_token, {"part": "status", "id": video_id})
        videos = as_list(data.get("items"))
        url = _watch_url(video_id)
        if not videos:
            return Outcome(PublicationStatus.FAILED, error="YouTube ya no tiene el video: lo borraron.")
        status = as_dict(videos[0].get("status"))
        upload_status = as_str(status.get("uploadStatus"))
        if upload_status == _PROCESSED:
            return Outcome(PublicationStatus.PUBLISHED, post_id=video_id, url=url)
        if upload_status == _STILL_UPLOADING:
            return Outcome(PublicationStatus.PENDING, post_id=video_id, url=url, resume=resume)
        reason = as_str(status.get("failureReason")) or as_str(status.get("rejectionReason")) or "sin motivo"
        return Outcome(PublicationStatus.FAILED, error=f"YouTube no la publicó ({upload_status}): {reason}")

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        await self._client.write("DELETE", "videos", token.access_token, params={"id": post_id})

    # ── La sesión ───────────────────────────────────────────────────────────────────────────────

    async def _open_session(self, token: str, file: MediaFile, metadata: Mapping[str, object]) -> str:
        headers = {
            **bearer(token),
            "X-Upload-Content-Length": str(file.size),
            "X-Upload-Content-Type": file.content_type,
        }
        url = f"{self._client.config.upload_base}/videos"
        try:
            response = await self._client.transport.request(
                "POST",
                url,
                params={"uploadType": "resumable", "part": "snippet,status"},
                json=metadata,
                headers=headers,
                # Abrir una sesión no crea ningún video: se puede repetir.
                retry_safe="abre una sesión de subida; el video se crea con la última parte",
            )
        except TransportError as error:
            raise NotPublished(YOUTUBE, f"No se pudo abrir la subida: {error}") from error
        if response.status >= _CLIENT_ERROR:
            raise self._before_upload(response)
        session = response.header("location")
        if not session:
            raise NotPublished(YOUTUBE, "YouTube no devolvió la sesión de subida.")
        return session

    @staticmethod
    def _before_upload(response: HttpResponse) -> Exception:
        """Un error antes de mandar el archivo: todavía no hay video, así que con certeza no salió."""
        error = api_error(response)
        told_why = isinstance(error, ProviderError) and error.kind in _SAYS_WHY
        if isinstance(error, TokenRejected) or told_why:
            return error
        return NotPublished(YOUTUBE, str(error), status=response.status)

    # ── Las partes ──────────────────────────────────────────────────────────────────────────────

    async def _send(self, upload: _Upload) -> str:
        """Manda el archivo y devuelve el id del video."""
        size = upload.file.size
        chunk = self._client.config.upload_chunk_bytes
        offset = 0
        failures = 0
        while True:
            last = offset + chunk >= size
            response = await self._try_part(upload, offset, chunk)
            if response is not None and response.status < _RESUME_INCOMPLETE:
                return self._created(response)
            if response is not None and _received(response) > offset:
                offset, failures = _received(response), 0
                continue
            # Una parte que no avanzó cuenta como falla, aunque YouTube haya respondido.
            failures += 1
            if response is not None and _fatal(response):
                raise self._abandoned(response, final=last)
            if failures >= self._client.config.upload_attempts:
                raise self._gave_up(final=last)
            # Se le pregunta a la sesión hasta dónde llegó, y se sigue desde ahí.
            state = await self._ask(upload)
            if state is not None and state.status < _RESUME_INCOMPLETE:
                return self._created(state)
            if state is not None:
                offset = max(offset, _received(state))

    async def _try_part(self, upload: _Upload, offset: int, chunk: int) -> HttpResponse | None:
        size = upload.file.size
        data = await upload.file.read(offset, min(chunk, size - offset))
        headers = {
            **bearer(upload.token),
            "Content-Type": upload.file.content_type,
            "Content-Range": f"bytes {offset}-{offset + len(data) - 1}/{size}",
        }
        try:
            return await self._client.transport.request("PUT", upload.session, content=data, headers=headers)
        except TransportError:
            return None

    async def _ask(self, upload: _Upload) -> HttpResponse | None:
        headers = {**bearer(upload.token), "Content-Range": f"bytes */{upload.file.size}"}
        try:
            return await self._client.transport.request("PUT", upload.session, content=b"", headers=headers)
        except TransportError:
            return None

    @staticmethod
    def _created(response: HttpResponse) -> str:
        video_id = as_str(as_dict(response.data).get("id"))
        if video_id is None:
            # La subida terminó bien: el video existe. No se puede decir que no salió.
            raise ProviderError(YOUTUBE, "YouTube recibió el video pero no devolvió su id.")
        return video_id

    @staticmethod
    def _abandoned(response: HttpResponse, *, final: bool) -> Exception:
        if final:
            return api_error(response)
        expired = response.status == _NOT_FOUND
        detail = "la sesión de subida venció" if expired else str(api_error(response))
        return NotPublished(YOUTUBE, f"La subida se cortó: {detail}", status=response.status)

    @staticmethod
    def _gave_up(*, final: bool) -> Exception:
        if final:
            return ProviderError(
                YOUTUBE, "Se perdió la respuesta a la última parte: no se sabe si YouTube creó el video."
            )
        return NotPublished(YOUTUBE, "La subida se cortó y no se pudo retomar.")


def _received(response: HttpResponse) -> int:
    """Desde dónde seguir: el byte siguiente al último que YouTube recibió. Sin `Range`, no recibió nada."""
    if response.status != _RESUME_INCOMPLETE:
        return 0
    match = _RANGE.fullmatch(response.header("range") or "")
    return int(match.group(1)) + 1 if match else 0


def _fatal(response: HttpResponse) -> bool:
    """Un 4xx no se arregla reintentando: la sesión venció o YouTube rechazó el archivo."""
    return _CLIENT_ERROR <= response.status < _SERVER_ERROR
