"""Lo que se lee de Google Business Profile: las sedes, sus novedades, sus reseñas y sus métricas."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from typing_extensions import override

from omnisocial.adapters.providers.google_business.client import (
    GoogleBusinessClient,
    as_dict,
    as_int,
    as_list,
    as_str,
    as_time,
    unwrap,
)
from omnisocial.adapters.providers.google_business.config import GOOGLE_BUSINESS, GOOGLE_BUSINESS_LOCATION
from omnisocial.adapters.providers.google_business.spec import LOCATION_CAPABILITIES
from omnisocial.application.ports import AssetDirectory, Clock, CommentGateway, ContentReader, InsightsReader
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.content import Comment, CommentAction, Post
from omnisocial.domain.errors import ErrorKind, ProviderError
from omnisocial.domain.metrics import (
    CanonicalMetric,
    CatalogEntry,
    MetricCatalog,
    MetricPoint,
    MetricSeries,
    Period,
)
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

IMPRESSIONS = "BUSINESS_IMPRESSIONS"
"""La suma de las cuatro métricas de impresiones (Maps y Búsqueda, en computadora y en celular). Google
no la da sumada: la calcula el adaptador."""
_IMPRESSION_PARTS = (
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
)
DAILY_METRICS = (
    *_IMPRESSION_PARTS,
    "BUSINESS_DIRECTION_REQUESTS",
    "CALL_CLICKS",
    "WEBSITE_CLICKS",
    "MESSAGING_CLICKS",
    "BUSINESS_BOOKINGS",
    "BUSINESS_FOOD_MENU_CLICKS",
)

DEFAULT_CATALOG = MetricCatalog(
    (CatalogEntry(GOOGLE_BUSINESS_LOCATION, CanonicalMetric.IMPRESSIONS, IMPRESSIONS),)
)

_READ_MASK = "name,title,storefrontAddress,websiteUri,metadata"
_STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
_OFFERED = frozenset({CommentAction.REPLY, CommentAction.DELETE})
_MAX_REPLY_BYTES = 4096
_DEFAULT_DAYS = 30
_REPLY = "/reply"


def location_id(asset: Asset) -> str:
    """`locations/456`, que es como la nombra la API de métricas."""
    return f"locations/{asset.external_id.rsplit('/', 1)[-1]}"


class GoogleBusinessAssetDirectory(AssetDirectory):
    def __init__(self, client: GoogleBusinessClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        """Las sedes de todas las cuentas que la persona administra (la personal y los grupos de sedes)."""
        config = self._client.config
        found: dict[str, DiscoveredAsset] = {}
        async for page in self._client.pages(
            f"{config.accounts_base}/accounts", token.access_token, "accounts", {"pageSize": 20}
        ):
            for account in as_list(page.get("accounts")):
                name = as_str(account.get("name"))
                if name is not None:
                    for location in await self._locations(token, name):
                        found.setdefault(location.external_id, location)
        return list(found.values())

    async def _locations(self, token: Token, account: str) -> list[DiscoveredAsset]:
        url = f"{self._client.config.information_base}/{account}/locations"
        params: dict[str, str | int] = {"readMask": _READ_MASK, "pageSize": 100}
        locations: list[DiscoveredAsset] = []
        async for page in self._client.pages(url, token.access_token, "locations", params):
            for location in as_list(page.get("locations")):
                name = as_str(location.get("name"))
                if name is None:
                    continue
                metadata = as_dict(location.get("metadata"))
                fields = {
                    "maps_uri": as_str(metadata.get("mapsUri")),
                    "new_review_uri": as_str(metadata.get("newReviewUri")),
                    "place_id": as_str(metadata.get("placeId")),
                    "website": as_str(location.get("websiteUri")),
                }
                locations.append(
                    DiscoveredAsset(
                        GOOGLE_BUSINESS_LOCATION,
                        # Las novedades y las reseñas se piden con la cuenta por delante.
                        f"{account}/locations/{name.rsplit('/', 1)[-1]}",
                        name=as_str(location.get("title")),
                        parent_external_id=account,
                        capabilities=LOCATION_CAPABILITIES,
                        metadata={key: value for key, value in fields.items() if value},
                    )
                )
        return locations


def to_post(item: dict[str, object], asset: Asset) -> Post:
    media = as_list(item.get("media"))
    first = media[0] if media else {}
    return Post(
        external_id=str(item["name"]),
        asset_external_id=asset.external_id,
        created_at=as_time(item.get("createTime")),
        text=as_str(item.get("summary")),
        permalink=as_str(item.get("searchUrl")),
        media_type=as_str(item.get("topicType")),
        media_url=as_str(first.get("googleUrl")) or as_str(first.get("sourceUrl")),
        raw=item,
    )


class GoogleBusinessContentReader(ContentReader):
    def __init__(self, client: GoogleBusinessClient) -> None:
        self._client = client

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        """Las novedades de la sede. Google no documenta el orden: no se corta al salir de la ventana."""
        url = f"{self._client.config.posts_base}/{asset.external_id}/localPosts"
        posts: list[Post] = []
        async for page in self._client.pages(url, token.access_token, "localPosts", {"pageSize": 100}):
            for item in as_list(page.get("localPosts")):
                if not as_str(item.get("name")):
                    continue
                post = to_post(item, asset)
                if window.contains(post.created_at):
                    posts.append(post)
                if limit is not None and len(posts) >= limit:
                    return posts
        return posts


def _review(item: dict[str, object], asset: Asset) -> Comment:
    name = str(item["name"])
    reviewer = as_dict(item.get("reviewer"))
    answer = as_dict(item.get("reviewReply"))
    replies: tuple[Comment, ...] = ()
    if as_str(answer.get("comment")):
        replies = (
            Comment(
                external_id=f"{name}{_REPLY}",
                object_external_id=name,
                created_at=as_time(answer.get("updateTime")),
                text=as_str(answer.get("comment")),
                author_name=asset.name,
            ),
        )
    return Comment(
        external_id=name,
        object_external_id=asset.external_id,
        created_at=as_time(item.get("createTime")),
        text=as_str(item.get("comment")),
        author_name=None if reviewer.get("isAnonymous") is True else as_str(reviewer.get("displayName")),
        rating=_STARS.get(as_str(item.get("starRating")) or ""),
        reply_count=len(replies),
        replies=replies,
        raw=item,
    )


class GoogleBusinessReviews(CommentGateway):
    """Las reseñas de una sede, como comentarios: se leen, se responden y la respuesta se puede borrar."""

    def __init__(self, client: GoogleBusinessClient) -> None:
        self._client = client

    def _url(self, review: str) -> str:
        return f"{self._client.config.posts_base}/{review.removesuffix(_REPLY)}{_REPLY}"

    @override
    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]:
        """Las reseñas son de la sede, no de una publicación: `object_id` no se usa. Vienen de la más
        reciente a la más vieja, cada una con sus estrellas y, si la tiene, la respuesta del negocio."""
        url = f"{self._client.config.posts_base}/{asset.external_id}/reviews"
        reviews: list[Comment] = []
        async for page in self._client.pages(url, token.access_token, "reviews", {"pageSize": 50}):
            reviews.extend(
                _review(item, asset) for item in as_list(page.get("reviews")) if as_str(item.get("name"))
            )
        return reviews

    @override
    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        """Responde una reseña. Una reseña tiene una sola respuesta: responder de nuevo la reemplaza."""
        if len(text.encode()) > _MAX_REPLY_BYTES:
            raise ProviderError(
                GOOGLE_BUSINESS,
                f"La respuesta a una reseña tiene hasta {_MAX_REPLY_BYTES} bytes.",
                kind=ErrorKind.INVALID_REQUEST,
            )
        url = self._url(comment_id)
        unwrap(await self._client.call("PUT", url, token.access_token, json={"comment": text}))
        return f"{comment_id.removesuffix(_REPLY)}{_REPLY}"

    @override
    async def delete(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        """Borra la respuesta del negocio. La reseña de un cliente no se puede borrar."""
        unwrap(await self._client.call("DELETE", self._url(comment_id), token.access_token))

    @override
    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None:
        raise ProviderError(GOOGLE_BUSINESS, "Una reseña no se puede ocultar.")

    @override
    async def like(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        raise ProviderError(GOOGLE_BUSINESS, "A una reseña no se le puede dar like.")

    @override
    def supports(self, asset: Asset, action: CommentAction) -> bool:
        return action in _OFFERED


def _day(date: dict[str, object]) -> datetime | None:
    year, month, day = (as_int(date.get(part)) for part in ("year", "month", "day"))
    if year is None or month is None or day is None:
        return None
    return datetime(year, month, day, tzinfo=UTC)


def _value(value: object) -> float:
    """Los valores vienen como texto, y un cero no viene."""
    try:
        return float(value) if isinstance(value, str | int | float) and not isinstance(value, bool) else 0.0
    except ValueError:
        return 0.0


class GoogleBusinessInsightsReader(InsightsReader):
    def __init__(
        self, client: GoogleBusinessClient, clock: Clock, catalog: MetricCatalog = DEFAULT_CATALOG
    ) -> None:
        self._client = client
        self._clock = clock
        self._catalog = catalog

    @property
    @override
    def catalog(self) -> MetricCatalog:
        return self._catalog

    @property
    @override
    def api_version(self) -> str:
        return "v1"

    @override
    async def read(
        self, asset: Asset, token: Token, *, metrics: Sequence[str], period: Period, window: TimeWindow
    ) -> Sequence[MetricSeries]:
        """Lee las métricas pedidas que existen y saltea las demás. Con período diario, un punto por día;
        si no, el total del tramo. Sin ventana, los últimos 30 días."""
        wanted = [name for name in (IMPRESSIONS, *DAILY_METRICS) if name in metrics]
        native = [name for name in DAILY_METRICS if name in wanted]
        if IMPRESSIONS in wanted:
            native = list(dict.fromkeys((*_IMPRESSION_PARTS, *native)))
        if not native:
            return []
        days = await self._fetch(asset, token, native, window)
        days[IMPRESSIONS] = _sum(days[part] for part in _IMPRESSION_PARTS if part in days)
        if period is Period.DAY:
            return [
                MetricSeries(
                    name, Period.DAY, tuple(MetricPoint(day, v) for day, v in sorted(days[name].items()))
                )
                for name in wanted
                if days.get(name)
            ]
        now = self._clock.now()
        return [
            MetricSeries(name, Period.LIFETIME, (MetricPoint(now, sum(days[name].values())),))
            for name in wanted
            if days.get(name)
        ]

    async def _fetch(
        self, asset: Asset, token: Token, native: Sequence[str], window: TimeWindow
    ) -> dict[str, dict[datetime, float]]:
        until = window.until or self._clock.now()
        since = window.since or until - timedelta(days=_DEFAULT_DAYS)
        # `dailyMetrics` se repite, una vez por métrica: la query se arma a mano.
        query = [("dailyMetrics", name) for name in native]
        for edge, moment in (("start_date", since), ("end_date", until)):
            query += [
                (f"dailyRange.{edge}.{part}", str(getattr(moment, part))) for part in ("year", "month", "day")
            ]
        url = (
            f"{self._client.config.performance_base}/{location_id(asset)}"
            f":fetchMultiDailyMetricsTimeSeries?{urlencode(query)}"
        )
        data = await self._client.get(url, token.access_token)
        days: dict[str, dict[datetime, float]] = {}
        for group in as_list(data.get("multiDailyMetricTimeSeries")):
            for series in as_list(group.get("dailyMetricTimeSeries")):
                name = as_str(series.get("dailyMetric"))
                if name is None:
                    continue
                for dated in as_list(as_dict(series.get("timeSeries")).get("datedValues")):
                    day = _day(as_dict(dated.get("date")))
                    if day is not None:
                        days.setdefault(name, {})[day] = _value(dated.get("value"))
        return days


def _sum(parts: Iterable[dict[datetime, float]]) -> dict[datetime, float]:
    total: dict[datetime, float] = {}
    for part in parts:
        for day, value in part.items():
            total[day] = total.get(day, 0.0) + value
    return total
