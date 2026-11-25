"""Lo que se lee de Pinterest: la cuenta, sus pines, sus tableros y sus métricas."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from typing_extensions import override

from omnisocial.adapters.providers.pinterest.client import (
    PinterestClient,
    as_dict,
    as_int,
    as_list,
    as_number,
    as_str,
    as_time,
)
from omnisocial.adapters.providers.pinterest.config import PINTEREST, PINTEREST_ACCOUNT
from omnisocial.adapters.providers.pinterest.spec import ACCOUNT_CAPABILITIES, BOARD_SECTIONS
from omnisocial.application.ports import AssetDirectory, Clock, ContentReader, InsightsReader, LookupReader
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.content import Post
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.lookup import Choice
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

FOLLOWERS = "follower_count"
ACCOUNT_METRICS = (
    "IMPRESSION",
    "ENGAGEMENT",
    "PIN_CLICK",
    "OUTBOUND_CLICK",
    "SAVE",
    "ENGAGEMENT_RATE",
    "PIN_CLICK_RATE",
    "OUTBOUND_CLICK_RATE",
    "SAVE_RATE",
)
"""Las terminadas en `_RATE` son tasas, no cantidades."""

DEFAULT_CATALOG = MetricCatalog(
    (
        CatalogEntry(PINTEREST_ACCOUNT, CanonicalMetric.FOLLOWERS, FOLLOWERS),
        CatalogEntry(PINTEREST_ACCOUNT, CanonicalMetric.IMPRESSIONS, "IMPRESSION"),
        CatalogEntry(PINTEREST_ACCOUNT, CanonicalMetric.ENGAGEMENTS, "ENGAGEMENT"),
    )
)

_MAX_DAYS = 90
_DEFAULT_DAYS = 30
_IMAGE_SIZES = ("1200x", "600x", "400x300", "150x150")


def pin_url(pin_id: str) -> str:
    """Pinterest no devuelve la dirección de un pin: se arma."""
    return f"https://www.pinterest.com/pin/{pin_id}/"


class PinterestAssetDirectory(AssetDirectory):
    def __init__(self, client: PinterestClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        account = await self._client.get("user_account", token.access_token)
        external_id = as_str(account.get("id"))
        if external_id is None:
            raise ProviderError(PINTEREST, "Pinterest no devolvió el id de la cuenta.")
        fields = {
            "username": as_str(account.get("username")),
            "account_type": as_str(account.get("account_type")),
        }
        return [
            DiscoveredAsset(
                PINTEREST_ACCOUNT,
                external_id,
                name=as_str(account.get("business_name")) or fields["username"],
                capabilities=ACCOUNT_CAPABILITIES,
                metadata={key: value for key, value in fields.items() if value},
            )
        ]


def _image(media: dict[str, object]) -> str | None:
    if cover := as_str(media.get("cover_image_url")):
        return cover
    images = as_dict(media.get("images"))
    return next((url for size in _IMAGE_SIZES if (url := as_str(as_dict(images.get(size)).get("url")))), None)


def _post(pin: dict[str, object], asset: Asset) -> Post:
    pin_id = str(pin["id"])
    media = as_dict(pin.get("media"))
    totals = as_dict(as_dict(pin.get("pin_metrics")).get("lifetime_metrics"))
    return Post(
        external_id=pin_id,
        asset_external_id=asset.external_id,
        created_at=as_time(pin.get("created_at")),
        text=as_str(pin.get("description")) or as_str(pin.get("title")),
        permalink=pin_url(pin_id),
        media_type=as_str(media.get("media_type")),
        media_url=_image(media),
        like_count=as_int(totals.get("reaction")),
        comment_count=as_int(totals.get("comment")),
        view_count=as_int(totals.get("impression")),
        raw=pin,
    )


class PinterestContentReader(ContentReader):
    def __init__(self, client: PinterestClient) -> None:
        self._client = client

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        """Los pines de la cuenta. Pinterest no documenta el orden: no se corta al salir de la ventana, se
        recorre hasta el tope de páginas."""
        posts: list[Post] = []
        async for page in self._client.pages("pins", token.access_token, {"pin_metrics": "true"}):
            for post in (_post(pin, asset) for pin in page if as_str(pin.get("id"))):
                if window.contains(post.created_at):
                    posts.append(post)
                if limit is not None and len(posts) >= limit:
                    return posts
        return posts


class PinterestLookups(LookupReader):
    def __init__(self, client: PinterestClient) -> None:
        self._client = client

    @override
    async def choices(
        self, asset: Asset, token: Token, *, lookup: str, query: str | None, parent: str | None
    ) -> Sequence[Choice]:
        path = f"boards/{parent}/sections" if lookup == BOARD_SECTIONS.name else "boards"
        found: list[Choice] = []
        async for page in self._client.pages(path, token.access_token):
            for item in page:
                item_id, name = as_str(item.get("id")), as_str(item.get("name"))
                if item_id is None or name is None:
                    continue
                privacy = as_str(item.get("privacy"))
                found.append(
                    Choice(
                        item_id,
                        name,
                        detail=as_str(item.get("description")),
                        data={"privacy": privacy} if privacy else {},
                    )
                )
        return found


class PinterestInsightsReader(InsightsReader):
    def __init__(
        self, client: PinterestClient, clock: Clock, catalog: MetricCatalog = DEFAULT_CATALOG
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
        return "v5"

    @override
    async def read(
        self, asset: Asset, token: Token, *, metrics: Sequence[str], period: Period, window: TimeWindow
    ) -> Sequence[MetricSeries]:
        """Lee las métricas pedidas que existen y saltea las demás. Con período diario, un punto por día;
        si no, el total del tramo. Pinterest guarda 90 días."""
        series: list[MetricSeries] = []
        if FOLLOWERS in metrics:
            account = await self._client.get("user_account", token.access_token)
            value = as_number(account.get(FOLLOWERS))
            if value is not None:
                point = MetricPoint(self._clock.now(), value)
                series.append(MetricSeries(FOLLOWERS, Period.LIFETIME, (point,)))
        wanted = [name for name in ACCOUNT_METRICS if name in metrics]
        if wanted:
            series.extend(await self._analytics(token, wanted, window, daily=period is Period.DAY))
        return series

    def _range(self, window: TimeWindow) -> tuple[str, str]:
        now = self._clock.now()
        until = min(window.until or now, now)
        oldest = now - timedelta(days=_MAX_DAYS - 1)
        since = max(window.since or until - timedelta(days=_DEFAULT_DAYS), oldest)
        return min(since, until).date().isoformat(), until.date().isoformat()

    async def _analytics(
        self, token: Token, wanted: Sequence[str], window: TimeWindow, *, daily: bool
    ) -> list[MetricSeries]:
        start, end = self._range(window)
        data = await self._client.get(
            "user_account/analytics",
            token.access_token,
            {"start_date": start, "end_date": end, "metric_types": ",".join(wanted)},
        )
        # La respuesta viene agrupada bajo una clave por corte (`all` cuando no se pide ninguno).
        group = next((as_dict(v) for v in data.values() if isinstance(v, dict)), {})
        if not daily:
            totals = as_dict(group.get("summary_metrics"))
            now = self._clock.now()
            return [
                MetricSeries(name, Period.LIFETIME, (MetricPoint(now, value),))
                for name in wanted
                if (value := as_number(totals.get(name))) is not None
            ]
        days = as_list(group.get("daily_metrics"))
        found: list[MetricSeries] = []
        for name in wanted:
            points = tuple(
                MetricPoint(as_time(day.get("date")), value)
                for day in days
                if (value := as_number(as_dict(day.get("metrics")).get(name))) is not None
            )
            if points:
                found.append(MetricSeries(name, Period.DAY, points))
        return found
