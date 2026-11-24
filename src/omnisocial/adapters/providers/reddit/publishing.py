"""Publicar en una comunidad: un texto o un link, con su título.

Es un solo pedido. Reddit responde 200 también cuando rechaza, con el motivo en el cuerpo: un rechazo es
certeza de que no salió. Si no responde, o responde sin decir qué creó, queda en duda.
"""

from __future__ import annotations

from collections.abc import Mapping

from typing_extensions import override

from omnisocial.adapters.providers.reddit.client import RedditClient, api_error, as_dict, as_str, refusal
from omnisocial.adapters.providers.reddit.config import REDDIT, RedditOptions, community
from omnisocial.application.ports import Publisher
from omnisocial.domain.asset import Asset
from omnisocial.domain.errors import ErrorKind, NotPublished, OmnisocialError, ProviderError, TokenRejected
from omnisocial.domain.publishing import Draft, Outcome, PublicationStatus
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
    return NotPublished(REDDIT, str(error), status=status)


def _form(draft: Draft, options: RedditOptions) -> dict[str, str]:
    form = {
        "sr": community(options.subreddit),
        "title": options.title,
        "kind": "link" if draft.link else "self",
    }
    flags = {
        "nsfw": options.nsfw,
        "spoiler": options.spoiler,
        "sendreplies": options.send_replies,
        "resubmit": options.resubmit,
    }
    form.update({name: str(value).lower() for name, value in flags.items()})
    if draft.link:
        form["url"] = draft.link
    else:
        form["text"] = draft.text
    if options.flair_id:
        form["flair_id"] = options.flair_id
    if options.flair_text:
        form["flair_text"] = options.flair_text
    return form


class RedditPublisher(Publisher):
    def __init__(self, client: RedditClient) -> None:
        self._client = client

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = draft.options
        if not isinstance(options, RedditOptions):
            raise ProviderError(
                REDDIT,
                "En Reddit se publica en una comunidad y con un título: faltan las opciones.",
                kind=ErrorKind.INVALID_REQUEST,
            )
        response = await self._client.post("api/submit", token.access_token, _form(draft, options))
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            raise _not_published(api_error(response), response.status)
        if response.status >= _SERVER_ERROR:
            raise api_error(response)
        body = as_dict(response.data)
        refused = refusal(body)
        if refused is not None:
            # Reddit dijo que no: no creó nada.
            raise _not_published(refused)
        created = as_dict(as_dict(body.get("json")).get("data"))
        name = as_str(created.get("name"))
        if name is None:
            raise ProviderError(REDDIT, "Reddit aceptó la publicación pero no devolvió su id.")
        return Outcome(PublicationStatus.PUBLISHED, post_id=name, url=as_str(created.get("url")))

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        raise ProviderError(REDDIT, "Reddit publica en una sola etapa: no hay nada para retomar.")

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        name = post_id if post_id.startswith("t3_") else f"t3_{post_id}"
        await self._client.act("api/del", token.access_token, {"id": name})
