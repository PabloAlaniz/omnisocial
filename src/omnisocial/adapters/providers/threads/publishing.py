"""Publicar en Threads: un post o un hilo.

- Un post de texto sale en un paso.
- Uno con medios va en etapas: se arma un contenedor, Threads descarga y procesa los medios, y recién
  cuando está `FINISHED` se publica.
- En un hilo, cada parte responde a la anterior: no se puede armar una parte hasta que salió la que la
  precede. El estado de la publicación guarda el plan entero y por dónde va.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.providers.threads.client import (
    ThreadsClient,
    api_error,
    as_dict,
    as_list,
    as_str,
    unwrap,
)
from omnisocial.adapters.providers.threads.config import THREADS, ThreadsOptions
from omnisocial.application.ports import Publisher
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ErrorKind, NotPublished, OmnisocialError, ProviderError, TokenRejected
from omnisocial.domain.publishing import Draft, MediaKind, Outcome, PublicationStatus
from omnisocial.domain.token import Token

_CLIENT_ERROR = 400
_SERVER_ERROR = 500
_IN_PROGRESS = "IN_PROGRESS"
_FINISHED = "FINISHED"
_ALREADY_PUBLISHED = "PUBLISHED"
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
    return NotPublished(THREADS, str(error), status=status)


def _part(draft: Draft) -> dict[str, object]:
    media = [
        {"video": item.kind is MediaKind.VIDEO, "url": item.public_url, "alt": item.alt_text or ""}
        for item in draft.media
    ]
    return {"text": draft.text, "link": draft.link or "", "media": media}


@dataclass
class _State:
    """Por dónde va la publicación. Se guarda entre una llamada y la siguiente."""

    plan: list[dict[str, object]]
    extras: dict[str, str]
    """Lo que vale para la primera parte: a quién responde, quién puede responder y el tema."""
    index: int = 0
    previous: str = ""
    """El post al que responde la parte que sigue."""
    first: str = ""
    container: str = ""

    @classmethod
    def load(cls, resume: Mapping[str, str]) -> _State:
        plan = resume.get("plan")
        if not plan:
            raise ProviderError(THREADS, "La publicación no tiene nada para retomar.")
        extras = {str(k): str(v) for k, v in as_dict(json.loads(resume.get("extras", "{}"))).items()}
        return cls(
            plan=as_list(json.loads(plan)),
            extras=extras,
            index=int(resume.get("index", "0")),
            previous=resume.get("previous", ""),
            first=resume.get("first", ""),
            container=resume.get("container", ""),
        )

    def dump(self) -> dict[str, str]:
        return {
            "plan": json.dumps(self.plan),
            "extras": json.dumps(self.extras),
            "index": str(self.index),
            "previous": self.previous,
            "first": self.first,
            "container": self.container,
        }

    @property
    def number(self) -> int:
        """El número de la parte en curso, como lo lee una persona."""
        return self.index + 1

    def done(self, post_id: str) -> None:
        self.first = self.first or post_id
        self.previous = post_id
        self.container = ""
        self.index += 1

    def common(self) -> dict[str, str]:
        """Los campos que lleva cualquier contenedor de la parte en curso."""
        fields = {"text": str(self.plan[self.index].get("text") or "")}
        if self.previous:
            fields["reply_to_id"] = self.previous
        if self.index == 0:
            fields |= self.extras
        return fields


class ThreadsPublisher(Publisher):
    def __init__(self, client: ThreadsClient) -> None:
        self._client = client

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options if isinstance(draft.options, ThreadsOptions) else ThreadsOptions()
        extras = {"reply_control": options.reply_control or "", "topic_tag": options.topic_tag or ""}
        state = _State(
            plan=[_part(item) for item in (draft, *draft.thread)],
            extras={key: value for key, value in extras.items() if value},
            previous=options.reply_to or "",
        )
        return await self._advance(asset.external_id, token.access_token, state)

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        return await self._advance(asset.external_id, token.access_token, _State.load(resume))

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        await self._client.delete(post_id, token.access_token)

    # ── El avance ───────────────────────────────────────────────────────────────────────────────

    async def _advance(self, user: str, token: str, state: _State) -> Outcome:
        """Sigue desde donde quedó, hasta terminar o hasta tener que esperar a Threads."""
        while state.index < len(state.plan):
            try:
                waiting = await self._step(user, token, state)
            except (TokenRejected, ProviderError, TransportError) as error:
                if not state.first:
                    raise
                # El comienzo del hilo ya salió: no es un fracaso, y repetirlo lo duplicaría.
                return self._cut(state, str(error))
            if waiting is not None:
                return waiting
        return Outcome(
            PublicationStatus.PUBLISHED, post_id=state.first, url=await self._permalink(state.first, token)
        )

    async def _step(self, user: str, token: str, state: _State) -> Outcome | None:
        """Avanza una parte. Devuelve un resultado si hay que parar; `None` si se puede seguir."""
        if not state.container:
            published = await self._begin(user, token, state)
            if published:
                state.done(published)
                return None
        status = await self._status(token, state.container)
        if status is None or status[0] == _IN_PROGRESS:
            return Outcome(PublicationStatus.PENDING, post_id=state.first or None, resume=state.dump())
        if status[0] == _FINISHED:
            state.done(await self._publish(user, token, state.container))
            return None
        return self._stopped(state, status[0], status[1])

    def _stopped(self, state: _State, status: str, error: str | None) -> Outcome:
        """El contenedor no va a avanzar más."""
        if status == _ALREADY_PUBLISHED:
            # Un intento anterior publicó y se perdió la respuesta: salió, pero no se sabe con qué id.
            return Outcome(
                PublicationStatus.PUBLISHED_WITH_ERROR,
                post_id=state.first or None,
                error=f"Threads ya había publicado la parte {state.number} y no quedó registrado su id.",
            )
        detail = f"Threads no pudo procesarla: {error or status or 'sin estado'}"
        if state.first:
            return self._cut(state, detail)
        return Outcome(PublicationStatus.FAILED, error=detail)

    @staticmethod
    def _cut(state: _State, detail: str) -> Outcome:
        return Outcome(
            PublicationStatus.PUBLISHED_WITH_ERROR,
            post_id=state.first,
            error=f"El hilo quedó cortado en la parte {state.number}: {detail}",
        )

    # ── Los pasos ───────────────────────────────────────────────────────────────────────────────

    async def _create(self, user: str, token: str, fields: Mapping[str, str]) -> str:
        """Crea un contenedor (o un post de texto). Si falla, todavía no hay nada publicado."""
        try:
            response = await self._client.post(f"{user}/threads", token, fields)
        except TransportError as error:
            raise NotPublished(THREADS, f"No se pudo armar la publicación: {error}") from error
        if response.status >= _CLIENT_ERROR or "error" in as_dict(response.data):
            raise _not_published(api_error(response), response.status)
        created = as_str(as_dict(response.data).get("id"))
        if created is None:
            raise NotPublished(THREADS, "Threads no devolvió el id de lo que se creó.")
        return created

    async def _begin(self, user: str, token: str, state: _State) -> str | None:
        """Arma la parte en curso. Devuelve el id del post si salió en un paso (solo texto); si no, deja
        el contenedor en el estado y devuelve `None`."""
        part = state.plan[state.index]
        media = as_list(part.get("media"))
        common = state.common()
        if not media:
            fields = {**common, "media_type": "TEXT", "auto_publish_text": "true"}
            if part.get("link"):
                fields["link_attachment"] = str(part["link"])
            return await self._create(user, token, fields)
        if len(media) == 1:
            state.container = await self._create(user, token, {**common, **_media_fields(media[0])})
            return None
        children = [
            await self._create(user, token, {**_media_fields(item), "is_carousel_item": "true"})
            for item in media
        ]
        carousel = {**common, "media_type": "CAROUSEL", "children": ",".join(children)}
        state.container = await self._create(user, token, carousel)
        return None

    async def _status(self, token: str, container: str) -> tuple[str, str | None] | None:
        """El estado del contenedor y su error. `None` si no se pudo consultar: se reintenta al retomar."""
        try:
            data = await self._client.get(container, token, {"fields": "status,error_message"})
        except (ProviderError, TransportError):
            return None
        return as_str(data.get("status")) or "", as_str(data.get("error_message"))

    async def _publish(self, user: str, token: str, container: str) -> str:
        response: HttpResponse = await self._client.post(
            f"{user}/threads_publish", token, {"creation_id": container}
        )
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            # Un 4xx es un rechazo: Threads no publicó nada.
            raise _not_published(api_error(response), response.status)
        post_id = as_str(unwrap(response).get("id"))
        if post_id is None:
            # Respondió bien: el post existe. No se puede decir que no salió.
            raise ProviderError(THREADS, "Threads publicó pero no devolvió el id del post.")
        return post_id

    async def _permalink(self, post_id: str, token: str) -> str | None:
        try:
            data = await self._client.get(post_id, token, {"fields": "permalink"})
        except (ProviderError, TransportError):
            return None
        return as_str(data.get("permalink"))


def _media_fields(item: dict[str, object]) -> dict[str, str]:
    url = str(item.get("url") or "")
    fields = (
        {"media_type": "VIDEO", "video_url": url}
        if item.get("video") is True
        else {"media_type": "IMAGE", "image_url": url}
    )
    if item.get("alt"):
        fields["alt_text"] = str(item["alt"])
    return fields
