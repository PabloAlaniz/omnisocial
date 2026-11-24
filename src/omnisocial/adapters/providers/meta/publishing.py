"""Publicar en páginas de Facebook y en cuentas de Instagram.

- **Página:** sale en una llamada. Texto o link van a `feed`; una foto, a `photos`; varias fotos se suben
  sin publicar y se adjuntan a un post de `feed`; un video, a `videos`.
El contenido va en el cuerpo del pedido y no en la URL: un texto largo no entra en una URL.

- **Instagram:** siempre en etapas. Se arma un contenedor, Instagram descarga y procesa los medios, y
  recién cuando el contenedor está `FINISHED` se publica. Un contenedor vence a las 24 horas.

En los dos casos los medios los va a buscar Meta a su URL: tienen que ser públicos.
"""

from __future__ import annotations

from collections.abc import Mapping

from typing_extensions import override

from omnisocial.adapters.http.transport import TransportError
from omnisocial.adapters.providers.meta.config import INSTAGRAM_ACCOUNT, META
from omnisocial.adapters.providers.meta.graph import GraphClient, as_str
from omnisocial.application.ports import Publisher
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.publishing import Draft, Media, MediaKind, Outcome, PublicationStatus
from omnisocial.domain.token import Token

_CONTAINER = "container"
_FIRST_COMMENT = "first_comment"

# Estados de un contenedor de Instagram.
_IN_PROGRESS = "IN_PROGRESS"
_FINISHED = "FINISHED"
_ALREADY_PUBLISHED = "PUBLISHED"


def _created_id(body: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = as_str(body.get(key))
        if value:
            return value
    raise ProviderError(META, "Meta no devolvió el id de lo que se creó.")


def _page_photo(media: Media) -> dict[str, object]:
    params: dict[str, object] = {"url": media.public_url}
    if media.alt_text:
        params["alt_text_custom"] = media.alt_text
    return params


def _instagram_media(media: Media, *, in_carousel: bool) -> dict[str, object]:
    if media.kind is MediaKind.IMAGE:
        params: dict[str, object] = {"image_url": media.public_url}
        if media.alt_text:
            params["alt_text"] = media.alt_text
    else:
        # Un video suelto es un reel; dentro de un carrusel es un video común.
        params = {"video_url": media.public_url, "media_type": "VIDEO" if in_carousel else "REELS"}
    if in_carousel:
        params["is_carousel_item"] = "true"
    return params


class MetaPublisher(Publisher):
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        if asset.kind == INSTAGRAM_ACCOUNT:
            return await self._instagram(asset, token, draft)
        post_id = await self._page_post(asset.external_id, token.access_token, draft)
        return await self._finish(
            post_id, token, draft.first_comment, url=f"https://www.facebook.com/{post_id}"
        )

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        container = resume.get(_CONTAINER)
        if not container:
            raise ProviderError(META, "La publicación no tiene nada para retomar.")
        state = await self._graph.get(container, token.access_token, {"fields": "status_code,status"})
        code = as_str(state.get("status_code"))
        if code == _IN_PROGRESS:
            return Outcome(PublicationStatus.PENDING, resume=resume)
        if code == _ALREADY_PUBLISHED:
            # Un intento anterior publicó y se perdió la respuesta: salió, pero no se sabe con qué id.
            return Outcome(
                PublicationStatus.PUBLISHED_WITH_ERROR,
                error="Instagram ya la había publicado y no quedó registrado su id.",
            )
        if code != _FINISHED:
            detail = as_str(state.get("status")) or code or "sin estado"
            return Outcome(PublicationStatus.FAILED, error=f"Instagram no pudo procesarla: {detail}")
        published = await self._graph.post(
            f"{asset.external_id}/media_publish", token.access_token, json={"creation_id": container}
        )
        media_id = _created_id(published, "id")
        return await self._finish(
            media_id, token, resume.get(_FIRST_COMMENT), url=await self._permalink(media_id, token)
        )

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        await self._graph.delete(post_id, token.access_token)

    # ── Página ──────────────────────────────────────────────────────────────────────────────────

    async def _page_post(self, page_id: str, token: str, draft: Draft) -> str:
        if not draft.media:
            params: dict[str, object] = {"message": draft.text}
            if draft.link:
                params["link"] = draft.link
            return _created_id(await self._graph.post(f"{page_id}/feed", token, json=params), "id")
        first = draft.media[0]
        if first.kind is MediaKind.VIDEO:
            video = {"file_url": first.public_url, "description": draft.text}
            return _created_id(await self._graph.post_video(f"{page_id}/videos", token, json=video), "id")
        if len(draft.media) == 1:
            photo = {**_page_photo(first), "caption": draft.text}
            created = await self._graph.post(f"{page_id}/photos", token, json=photo)
            return _created_id(created, "post_id", "id")
        return await self._page_album(page_id, token, draft)

    async def _page_album(self, page_id: str, token: str, draft: Draft) -> str:
        """Varias fotos: cada una se sube sin publicar y después se adjuntan todas a un post."""
        attached: list[dict[str, str]] = []
        for media in draft.media:
            uploaded = await self._graph.post(
                f"{page_id}/photos", token, json={**_page_photo(media), "published": "false"}
            )
            attached.append({"media_fbid": _created_id(uploaded, "id")})
        post = {"message": draft.text, "attached_media": attached}
        return _created_id(await self._graph.post(f"{page_id}/feed", token, json=post), "id")

    # ── Instagram ───────────────────────────────────────────────────────────────────────────────

    async def _instagram(self, asset: Asset, token: Token, draft: Draft) -> Outcome:
        container = await self._container(asset.external_id, token.access_token, draft)
        resume = {_CONTAINER: container}
        if draft.first_comment:
            resume[_FIRST_COMMENT] = draft.first_comment
        try:
            # Una imagen suele estar lista enseguida: se intenta publicar sin hacer esperar a la app.
            return await self.resume(asset, token, resume=resume)
        except (ProviderError, TransportError):
            # El contenedor ya existe: lo que falló se reintenta al retomar, sin armar otro.
            return Outcome(PublicationStatus.PENDING, resume=resume)

    async def _container(self, account_id: str, token: str, draft: Draft) -> str:
        path = f"{account_id}/media"
        if len(draft.media) == 1:
            single = {**_instagram_media(draft.media[0], in_carousel=False), "caption": draft.text}
            return _created_id(await self._graph.post(path, token, json=single), "id")
        children = [
            _created_id(
                await self._graph.post(path, token, json=_instagram_media(media, in_carousel=True)), "id"
            )
            for media in draft.media
        ]
        carousel = {"media_type": "CAROUSEL", "children": ",".join(children), "caption": draft.text}
        return _created_id(await self._graph.post(path, token, json=carousel), "id")

    async def _permalink(self, media_id: str, token: Token) -> str | None:
        try:
            media = await self._graph.get(media_id, token.access_token, {"fields": "permalink"})
        except (ProviderError, TransportError):
            return None
        return as_str(media.get("permalink"))

    # ── Lo que viene después de publicar ────────────────────────────────────────────────────────

    async def _finish(
        self, post_id: str, token: Token, first_comment: str | None, *, url: str | None
    ) -> Outcome:
        """Ya salió. Si el primer comentario falla, no es un fracaso: repetir duplicaría la publicación."""
        if first_comment is None:
            return Outcome(PublicationStatus.PUBLISHED, post_id=post_id, url=url)
        try:
            await self._graph.post(f"{post_id}/comments", token.access_token, json={"message": first_comment})
        except (ProviderError, TransportError) as error:
            return Outcome(
                PublicationStatus.PUBLISHED_WITH_ERROR,
                post_id=post_id,
                url=url,
                error=f"El primer comentario no salió: {error}",
            )
        return Outcome(PublicationStatus.PUBLISHED, post_id=post_id, url=url)
