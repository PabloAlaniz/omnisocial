"""Publicar una novedad en una sede.

Es un solo pedido. Google puede dejar la novedad en revisión: en ese caso queda pendiente y al retomarla
se ve si salió o la rechazó.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from typing_extensions import override

from omnisocial.adapters.providers.google_business.client import (
    GoogleBusinessClient,
    api_error,
    as_str,
    unwrap,
)
from omnisocial.adapters.providers.google_business.config import GOOGLE_BUSINESS, GoogleBusinessOptions
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
_REJECTED, _PROCESSING = "REJECTED", "PROCESSING"


def _not_published(error: OmnisocialError, status: int | None = None) -> OmnisocialError:
    if isinstance(error, TokenRejected) or (isinstance(error, ProviderError) and error.kind in _SAYS_WHY):
        return error
    return NotPublished(GOOGLE_BUSINESS, str(error), status=status)


def _moment(moment: datetime) -> tuple[dict[str, int], dict[str, int]]:
    """La fecha y la hora, por separado, como las pide Google. Van en la hora de la sede, sin zona."""
    date = {"year": moment.year, "month": moment.month, "day": moment.day}
    return date, {"hours": moment.hour, "minutes": moment.minute}


def _event(options: GoogleBusinessOptions) -> dict[str, object] | None:
    if options.starts_at is None or options.ends_at is None or options.event_title is None:
        return None
    (start_date, start_time), (end_date, end_time) = _moment(options.starts_at), _moment(options.ends_at)
    schedule = {"startDate": start_date, "startTime": start_time, "endDate": end_date, "endTime": end_time}
    return {"title": options.event_title, "schedule": schedule}


def _offer(options: GoogleBusinessOptions) -> dict[str, object]:
    fields = {
        "couponCode": options.coupon_code,
        "redeemOnlineUrl": options.redeem_url,
        "termsConditions": options.terms,
    }
    return {name: value for name, value in fields.items() if value}


def local_post(draft: Draft, options: GoogleBusinessOptions, language: str) -> dict[str, object]:
    post: dict[str, object] = {
        "languageCode": options.language_code or language,
        "summary": draft.text,
        "topicType": options.topic,
    }
    if draft.media:
        post["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": media.public_url} for media in draft.media]
    # Una oferta no lleva botón: Google lo ignora.
    if options.action is not None and options.topic != "OFFER":
        action: dict[str, object] = {"actionType": options.action}
        if options.action_url is not None:
            action["url"] = options.action_url
        post["callToAction"] = action
    if (event := _event(options)) is not None and options.topic != "STANDARD":
        post["event"] = event
    if options.topic == "OFFER":
        post["offer"] = _offer(options)
    return post


def _outcome(post: Mapping[str, object]) -> Outcome:
    name = as_str(post.get("name"))
    if name is None:
        # Respondió bien: la novedad existe. No se puede decir que no salió.
        raise ProviderError(GOOGLE_BUSINESS, "Google creó la novedad pero no devolvió su nombre.")
    state, url = as_str(post.get("state")), as_str(post.get("searchUrl"))
    if state == _REJECTED:
        return Outcome(PublicationStatus.FAILED, post_id=name, error="Google rechazó la novedad.")
    if state == _PROCESSING:
        return Outcome(PublicationStatus.PENDING, post_id=name, resume={"name": name})
    return Outcome(PublicationStatus.PUBLISHED, post_id=name, url=url)


class GoogleBusinessPublisher(Publisher):
    def __init__(self, client: GoogleBusinessClient) -> None:
        self._client = client

    @override
    async def publish(self, asset: Asset, token: Token, *, draft: Draft) -> Outcome:
        options = (
            draft.options if isinstance(draft.options, GoogleBusinessOptions) else GoogleBusinessOptions()
        )
        config = self._client.config
        response = await self._client.call(
            "POST",
            f"{config.posts_base}/{asset.external_id}/localPosts",
            token.access_token,
            json=local_post(draft, options, config.language_code),
        )
        if _CLIENT_ERROR <= response.status < _SERVER_ERROR:
            # Un 4xx es un rechazo: Google no creó nada.
            raise _not_published(api_error(response), response.status)
        return _outcome(unwrap(response))

    @override
    async def resume(self, asset: Asset, token: Token, *, resume: Mapping[str, str]) -> Outcome:
        name = resume.get("name")
        if not name:
            raise ProviderError(GOOGLE_BUSINESS, "No hay con qué retomar esta publicación.")
        return _outcome(
            await self._client.get(f"{self._client.config.posts_base}/{name}", token.access_token)
        )

    @override
    async def delete(self, asset: Asset, token: Token, *, post_id: str) -> None:
        unwrap(
            await self._client.call(
                "DELETE", f"{self._client.config.posts_base}/{post_id}", token.access_token
            )
        )
