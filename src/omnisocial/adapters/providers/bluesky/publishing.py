"""Publicar en Bluesky: un post o un hilo.

1. Cada imagen o video se sube y queda una referencia. Hasta que un post la usa, no se ve.
2. Se crea el post, y cada parte del hilo como respuesta a la anterior.

Sale en una sola etapa: no hay nada que retomar.
"""

from __future__ import annotations

from collections.abc import Mapping

from typing_extensions import override

from omnisocial.adapters.http.transport import TransportError
from omnisocial.adapters.providers.bluesky.client import BlueskyClient, as_str, iso
from omnisocial.adapters.providers.bluesky.comments import BlueskyCommentGateway, reference
from omnisocial.adapters.providers.bluesky.config import BLUESKY, POST, BlueskyOptions, post_url, rkey
from omnisocial.adapters.providers.bluesky.richtext import facets
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
    if isinstance(error, TokenRejected) or (isinstance(error, ProviderError) and error.kind in _SAYS_WHY):
        return error
    return NotPublished(BLUESKY, str(error), status=status)


class BlueskyPublisher(Publisher):
    def __init__(self, client: BlueskyClient) -> None:
        self._client = client
        self._posts = BlueskyCommentGateway(client)

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options if isinstance(draft.options, BlueskyOptions) else BlueskyOptions()
        parts = (draft, *draft.thread)
        try:
            embeds = [await self._embed(token, part, options) for part in parts]
            reply = await self._reply_to(token, options.reply_to) if options.reply_to else None
        except TransportError as error:
            raise NotPublished(BLUESKY, f"La subida se cortó: {error}") from error
        except (TokenRejected, ProviderError) as error:
            raise _not_published(error) from error

        first = await self._create(asset, token, self._record(parts[0], options, embeds[0], reply))
        root = previous = first
        for number, part in enumerate(parts[1:], start=2):
            record = self._record(part, options, embeds[number - 1], {"root": root, "parent": previous})
            try:
                previous = await self._create(asset, token, record)
            except (TokenRejected, ProviderError, TransportError) as error:
                # El comienzo del hilo ya salió: no es un fracaso, y repetirlo lo duplicaría.
                return Outcome(
                    PublicationStatus.PUBLISHED_WITH_ERROR,
                    post_id=first["uri"],
                    url=post_url(asset.external_id, first["uri"]),
                    error=f"El hilo quedó cortado en la parte {number}: {error}",
                )
        return Outcome(
            PublicationStatus.PUBLISHED, post_id=first["uri"], url=post_url(asset.external_id, first["uri"])
        )

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        raise ProviderError(BLUESKY, "Bluesky publica en una sola etapa: no hay nada para retomar.")

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        body = {"repo": asset.external_id, "collection": POST, "rkey": rkey(post_id)}
        self._client.unwrap(await self._client.call("com.atproto.repo.deleteRecord", token, body))

    # ── El post ─────────────────────────────────────────────────────────────────────────────────

    def _record(
        self,
        part: Draft,
        options: BlueskyOptions,
        embed: dict[str, object] | None,
        reply: Mapping[str, object] | None,
    ) -> dict[str, object]:
        record: dict[str, object] = {
            "$type": POST,
            "text": part.text,
            "createdAt": iso(self._client.clock.now()),
        }
        marks = facets(part.text)
        if marks:
            record["facets"] = marks
        if options.langs:
            record["langs"] = list(options.langs)
        if embed:
            record["embed"] = embed
        if reply:
            record["reply"] = dict(reply)
        return record

    async def _create(self, asset: Asset, token: Token, record: dict[str, object]) -> dict[str, str]:
        body = {"repo": asset.external_id, "collection": POST, "record": record}
        response = await self._client.call("com.atproto.repo.createRecord", token, body)
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            # Un 4xx es un rechazo: Bluesky no creó nada.
            raise _not_published(self._client.error(response), response.status)
        created = self._client.unwrap(response)
        uri, cid = as_str(created.get("uri")), as_str(created.get("cid"))
        if uri is None or cid is None:
            # Respondió bien: el post existe. No se puede decir que no salió.
            raise ProviderError(BLUESKY, "Bluesky creó el post pero no devolvió su dirección.")
        return {"uri": uri, "cid": cid}

    async def _reply_to(self, token: Token, uri: str) -> dict[str, object]:
        """A quién responde la primera parte: la raíz de ese hilo y el post mismo."""
        parent = await self._posts.view(token, uri)
        record = parent.get("record")
        root = record.get("reply", {}).get("root") if isinstance(record, dict) else None
        return {"root": root or reference(parent), "parent": reference(parent)}

    # ── Lo que acompaña al texto ────────────────────────────────────────────────────────────────

    async def _embed(self, token: Token, part: Draft, options: BlueskyOptions) -> dict[str, object] | None:
        if part.link:
            external = {
                "uri": part.link,
                "title": options.link_title or part.link,
                "description": options.link_description or "",
            }
            return {"$type": "app.bsky.embed.external", "external": external}
        if not part.media:
            return None
        if part.media[0].kind is MediaKind.VIDEO:
            video = part.media[0]
            blob = await self._blob(token, video)
            embed: dict[str, object] = {"$type": "app.bsky.embed.video", "video": blob}
            if video.alt_text:
                embed["alt"] = video.alt_text
            return embed
        images = [
            {"alt": media.alt_text or "", "image": await self._blob(token, media)} for media in part.media
        ]
        return {"$type": "app.bsky.embed.images", "images": images}

    async def _blob(self, token: Token, media: Media) -> dict[str, object]:
        file = media.upload
        blob = await self._client.upload(token, await file.read(0, file.size), file.content_type)
        if not blob:
            raise ProviderError(BLUESKY, "Bluesky no devolvió la referencia del archivo.")
        return blob
