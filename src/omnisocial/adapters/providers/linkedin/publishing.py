"""Publicar en un perfil o en una página de empresa.

1. Cada imagen o video se sube: se pide a LinkedIn dónde, se manda el archivo y queda un URN.
2. Se crea la publicación con el texto y esos URN.

Hasta el paso 2 no hay nada publicado: si una subida falla, con certeza no salió (`NotPublished`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.linkedin.client import (
    LinkedInClient,
    api_error,
    as_dict,
    as_int,
    as_list,
    as_str,
    bearer,
    encode,
    unwrap,
)
from omnisocial.adapters.providers.linkedin.config import LINKEDIN, LinkedInOptions, urn
from omnisocial.adapters.providers.linkedin.content import permalink
from omnisocial.adapters.providers.linkedin.text import escape
from omnisocial.application.ports import Publisher
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ErrorKind, NotPublished, OmnisocialError, ProviderError, TokenRejected
from omnisocial.domain.publishing import Draft, Media, MediaKind, Outcome, PublicationStatus
from omnisocial.domain.token import Token

_CLIENT_ERROR = 400
_SERVER_ERROR = 500
# Errores que ya dicen por qué no salió: el núcleo los traduce a su propia negativa.
_SAYS_WHY = frozenset(
    {
        ErrorKind.MISSING_PERMISSION,
        ErrorKind.RATE_LIMITED,
        ErrorKind.QUOTA_EXHAUSTED,
        ErrorKind.INVALID_REQUEST,
    }
)


def _not_published(error: OmnisocialError, status: int | None = None) -> OmnisocialError:
    """Un error antes de crear la publicación: con certeza no salió."""
    if isinstance(error, TokenRejected) or (isinstance(error, ProviderError) and error.kind in _SAYS_WHY):
        return error
    return NotPublished(LINKEDIN, str(error), status=status)


def _content(
    draft: Draft, options: LinkedInOptions, uploaded: Sequence[tuple[Media, str]]
) -> dict[str, object]:
    if draft.link:
        article: dict[str, object] = {"source": draft.link, "title": options.link_title or draft.link}
        if options.link_description:
            article["description"] = options.link_description
        return {"article": article}
    items = [
        {"id": media_urn, **({"altText": media.alt_text} if media.alt_text else {})}
        for media, media_urn in uploaded
    ]
    if len(items) > 1:
        return {"multiImage": {"images": items}}
    return {"media": items[0]} if items else {}


def _post(
    author: str, draft: Draft, options: LinkedInOptions, content: dict[str, object]
) -> dict[str, object]:
    body: dict[str, object] = {
        "author": author,
        "commentary": draft.text if options.little_text else escape(draft.text),
        "visibility": options.visibility,
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": options.reshare_disabled,
    }
    if content:
        body["content"] = content
    return body


class LinkedInPublisher(Publisher):
    def __init__(self, client: LinkedInClient) -> None:
        self._client = client

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options if isinstance(draft.options, LinkedInOptions) else LinkedInOptions()
        author = urn(asset.kind, asset.external_id)
        uploaded = [(media, await self._upload(author, token.access_token, media)) for media in draft.media]
        post_urn = await self._create(
            token.access_token, _post(author, draft, options, _content(draft, options, uploaded))
        )
        return await self._finish(author, token.access_token, post_urn, draft.first_comment)

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        raise ProviderError(LINKEDIN, "LinkedIn publica en una sola etapa: no hay nada para retomar.")

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        response = await self._client.call(
            "DELETE", f"posts/{encode(post_id)}", token.access_token, restli_method="DELETE"
        )
        unwrap(response)

    # ── La publicación ──────────────────────────────────────────────────────────────────────────

    async def _create(self, token: str, body: Mapping[str, object]) -> str:
        response = await self._client.call("POST", "posts", token, json=body)
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            # Un 4xx es un rechazo: LinkedIn no creó nada.
            raise _not_published(api_error(response), response.status)
        created = unwrap(response)
        post_urn = response.header("x-restli-id") or as_str(created.get("id"))
        if not post_urn:
            # Respondió bien: la publicación existe. No se puede decir que no salió.
            raise ProviderError(LINKEDIN, "LinkedIn creó la publicación pero no devolvió su id.")
        return post_urn

    async def _finish(self, author: str, token: str, post_urn: str, first_comment: str | None) -> Outcome:
        """Ya salió. Si el primer comentario falla, no es un fracaso: repetir duplicaría la publicación."""
        url = permalink(post_urn)
        if first_comment is None:
            return Outcome(PublicationStatus.PUBLISHED, post_id=post_urn, url=url)
        body = {"actor": author, "object": post_urn, "message": {"text": first_comment}}
        try:
            unwrap(
                await self._client.call(
                    "POST", f"socialActions/{encode(post_urn)}/comments", token, json=body
                )
            )
        except (ProviderError, TransportError) as error:
            return Outcome(
                PublicationStatus.PUBLISHED_WITH_ERROR,
                post_id=post_urn,
                url=url,
                error=f"El primer comentario no salió: {error}",
            )
        return Outcome(PublicationStatus.PUBLISHED, post_id=post_urn, url=url)

    # ── Los medios ──────────────────────────────────────────────────────────────────────────────

    async def _upload(self, owner: str, token: str, media: Media) -> str:
        try:
            if media.kind is MediaKind.IMAGE:
                return await self._image(owner, token, media)
            return await self._video(owner, token, media)
        except TransportError as error:
            raise NotPublished(LINKEDIN, f"La subida se cortó: {error}") from error
        except (TokenRejected, ProviderError) as error:
            raise _not_published(error) from error

    async def _start(self, resource: str, token: str, request: Mapping[str, object]) -> dict[str, object]:
        response = await self._client.call(
            "POST",
            f"{resource}?action=initializeUpload",
            token,
            json={"initializeUploadRequest": request},
            read=True,
        )
        return as_dict(unwrap(response).get("value"))

    async def _put(self, url: str, data: bytes, headers: Mapping[str, str]) -> HttpResponse:
        response = await self._client.transport.request("PUT", url, content=data, headers=headers)
        if response.status >= _CLIENT_ERROR:
            raise api_error(response)
        return response

    async def _image(self, owner: str, token: str, media: Media) -> str:
        file = media.upload
        started = await self._start("images", token, {"owner": owner})
        upload_url, image = as_str(started.get("uploadUrl")), as_str(started.get("image"))
        if not upload_url or not image:
            raise ProviderError(LINKEDIN, "LinkedIn no dijo dónde subir la imagen.")
        # La subida de una imagen sí lleva el token; la de un video, no.
        await self._put(upload_url, await file.read(0, file.size), bearer(token))
        return image

    async def _video(self, owner: str, token: str, media: Media) -> str:
        file = media.upload
        request = {
            "owner": owner,
            "fileSizeBytes": file.size,
            "uploadCaptions": False,
            "uploadThumbnail": False,
        }
        started = await self._start("videos", token, request)
        video = as_str(started.get("video"))
        instructions = as_list(started.get("uploadInstructions"))
        if not video or not instructions:
            raise ProviderError(LINKEDIN, "LinkedIn no dijo dónde subir el video.")
        parts: list[str] = []
        for instruction in instructions:
            first, last = as_int(instruction.get("firstByte")), as_int(instruction.get("lastByte"))
            upload_url = as_str(instruction.get("uploadUrl"))
            if first is None or last is None or not upload_url:
                raise ProviderError(LINKEDIN, "LinkedIn devolvió una parte del video sin sus datos.")
            data = await file.read(first, last - first + 1)
            sent = await self._put(upload_url, data, {"Content-Type": "application/octet-stream"})
            parts.append(sent.header("etag") or "")
        finalize = {
            "video": video,
            "uploadToken": as_str(started.get("uploadToken")) or "",
            "uploadedPartIds": parts,
        }
        response = await self._client.call(
            "POST", "videos?action=finalizeUpload", token, json={"finalizeUploadRequest": finalize}, read=True
        )
        unwrap(response)
        return video
