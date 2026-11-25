"""La cuenta, sus publicaciones, las respuestas, los contadores y los perfiles públicos."""

from __future__ import annotations

from collections.abc import Sequence

from typing_extensions import override

from omnisocial.adapters.providers.mastodon.client import (
    MastodonClient,
    as_dict,
    as_int,
    as_list,
    as_str,
    parse_time,
    plain,
)
from omnisocial.adapters.providers.mastodon.oauth import own_account
from omnisocial.adapters.providers.mastodon.spec import ACCOUNT_CAPABILITIES
from omnisocial.application.ports import (
    AssetDirectory,
    Clock,
    CommentGateway,
    ContentReader,
    InsightsReader,
    ProfileLookup,
)
from omnisocial.domain.asset import Asset, DiscoveredAsset
from omnisocial.domain.content import Comment, CommentAction, Post
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.handles import Handle, Network
from omnisocial.domain.metrics import (
    CanonicalMetric,
    CatalogEntry,
    MetricCatalog,
    MetricPoint,
    MetricSeries,
    Period,
)
from omnisocial.domain.profile import PublicProfile
from omnisocial.domain.token import Token
from omnisocial.domain.window import TimeWindow

API_VERSION = "v1"
STATS = ("followers_count", "following_count", "statuses_count")
# Ocultar o borrar la respuesta de otra cuenta no existe en el protocolo.
_OFFERED = frozenset({CommentAction.REPLY, CommentAction.LIKE})
_NOT_FOUND = 404
_CLIENT_ERROR = 400


def catalog_for(account_kind: str) -> MetricCatalog:
    return MetricCatalog((CatalogEntry(account_kind, CanonicalMetric.FOLLOWERS, "followers_count"),))


class MastodonAssetDirectory(AssetDirectory):
    """El activo es la cuenta de quien autorizó."""

    def __init__(self, client: MastodonClient) -> None:
        self._client = client

    @override
    async def discover(self, token: Token) -> Sequence[DiscoveredAsset]:
        account = await own_account(self._client, token)
        server = self._client.server_of(token)
        username = as_str(account.get("username"))
        metadata = {"server": server, "acct": f"{username}@{server}" if username else ""}
        # Sin token propio: se usa el de la conexión, que es el de la cuenta y sabe de qué servidor es.
        return [
            DiscoveredAsset(
                self._client.flavor.account_kind,
                str(account["id"]),
                name=as_str(account.get("display_name")) or username,
                capabilities=ACCOUNT_CAPABILITIES,
                metadata={key: value for key, value in metadata.items() if value},
            )
        ]


def _post(status: dict[str, object], asset: Asset) -> Post:
    media = as_list(status.get("media_attachments"))
    return Post(
        external_id=str(status["id"]),
        asset_external_id=asset.external_id,
        created_at=parse_time(status.get("created_at")),
        text=plain(status.get("content")),
        permalink=as_str(status.get("url")) or as_str(status.get("uri")),
        media_type=as_str(media[0].get("type")) if media else "text",
        media_url=as_str(media[0].get("preview_url")) if media else None,
        like_count=as_int(status.get("favourites_count")),
        comment_count=as_int(status.get("replies_count")),
        share_count=as_int(status.get("reblogs_count")),
        raw=status,
    )


class MastodonContentReader(ContentReader):
    """Las publicaciones propias, sin respuestas ni impulsos."""

    def __init__(self, client: MastodonClient, page_size: int) -> None:
        self._client = client
        self._page_size = page_size

    @override
    async def list_posts(
        self, asset: Asset, token: Token, *, window: TimeWindow, limit: int | None
    ) -> Sequence[Post]:
        query: dict[str, str | int] = {
            "limit": self._page_size,
            "exclude_replies": "true",
            "exclude_reblogs": "true",
        }
        posts: list[Post] = []
        path = f"api/v1/accounts/{asset.external_id}/statuses"
        async for page in self._client.items(path, token, query):
            for post in (_post(status, asset) for status in page if status.get("id")):
                if window.is_before(post.created_at):
                    return posts
                if window.contains(post.created_at):
                    posts.append(post)
                if limit is not None and len(posts) >= limit:
                    return posts
        return posts


def _comment(status: dict[str, object], object_id: str) -> Comment:
    account = as_dict(status.get("account"))
    return Comment(
        external_id=str(status["id"]),
        object_external_id=as_str(status.get("in_reply_to_id")) or object_id,
        created_at=parse_time(status.get("created_at")),
        text=plain(status.get("content")),
        author_id=as_str(account.get("id")),
        author_name=as_str(account.get("acct")),
        like_count=as_int(status.get("favourites_count")),
        reply_count=as_int(status.get("replies_count")),
        raw=status,
    )


class MastodonCommentGateway(CommentGateway):
    def __init__(self, client: MastodonClient) -> None:
        self._client = client

    @override
    async def list_comments(self, asset: Asset, token: Token, *, object_id: str) -> Sequence[Comment]:
        """Todas las respuestas de la conversación, de cualquier nivel: cada una dice a cuál responde."""
        context = await self._client.get(f"api/v1/statuses/{object_id}/context", token)
        return [
            _comment(status, object_id)
            for status in as_list(context.get("descendants"))
            # Las de la propia cuenta (un hilo) no son comentarios.
            if status.get("id") and as_dict(status.get("account")).get("id") != asset.external_id
        ]

    @override
    async def reply(self, asset: Asset, token: Token, *, comment_id: str, text: str) -> str:
        body = {"status": text, "in_reply_to_id": comment_id}
        response = await self._client.call("POST", "api/v1/statuses", token, json=body)
        reply_id = as_str(self._client.unwrap(response).get("id"))
        if reply_id is None:
            raise ProviderError(
                self._client.flavor.provider, "El servidor no devolvió el id de la respuesta."
            )
        return reply_id

    @override
    async def set_hidden(self, asset: Asset, token: Token, *, comment_id: str, hidden: bool) -> None:
        raise ProviderError(self._client.flavor.provider, "El protocolo no permite ocultar una respuesta.")

    @override
    async def delete(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        raise ProviderError(
            self._client.flavor.provider, "El protocolo no permite borrar la respuesta de otra cuenta."
        )

    @override
    async def like(self, asset: Asset, token: Token, *, comment_id: str) -> None:
        response = await self._client.call(
            "POST",
            f"api/v1/statuses/{comment_id}/favourite",
            token,
            repeatable="marcar como favorita dos veces da lo mismo",
        )
        self._client.unwrap(response)

    @override
    def supports(self, asset: Asset, action: CommentAction) -> bool:
        return action in _OFFERED


class MastodonInsightsReader(InsightsReader):
    """Contadores de la cuenta. Son una foto del momento, sin historia."""

    def __init__(self, client: MastodonClient, clock: Clock, catalog: MetricCatalog) -> None:
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
        return API_VERSION

    @override
    async def read(
        self, asset: Asset, token: Token, *, metrics: Sequence[str], period: Period, window: TimeWindow
    ) -> Sequence[MetricSeries]:
        """Lee los contadores pedidos que existen y saltea los demás. `period` y `window` no aplican."""
        wanted = [name for name in STATS if name in metrics]
        if not wanted:
            return []
        account = await own_account(self._client, token)
        now = self._clock.now()
        return [
            MetricSeries(name, Period.LIFETIME, (MetricPoint(now, float(value)),))
            for name in wanted
            if (value := as_int(account.get(name))) is not None
        ]


class MastodonProfileLookup(ProfileLookup):
    """Perfiles públicos de cualquier cuenta, sin que nadie conecte: se le pregunta a su servidor."""

    def __init__(self, client: MastodonClient) -> None:
        self._client = client

    @property
    @override
    def networks(self) -> frozenset[Network]:
        return frozenset({Network.MASTODON})

    @override
    def viewer_kinds(self, network: Network) -> frozenset[str]:
        return frozenset()

    @override
    async def lookup(
        self, handle: Handle, *, viewer: Asset | None, token: Token | None
    ) -> PublicProfile | None:
        """`handle` es `nombre@servidor`, ya validado por `parse_handle`."""
        user, _, server = handle.value.partition("@")
        if not server:
            return None
        response = await self._client.transport.request(
            "GET", self._client.url(server, "api/v1/accounts/lookup"), params={"acct": user}
        )
        if response.status == _NOT_FOUND:
            return None
        account = self._client.unwrap(response)
        account_id = as_str(account.get("id"))
        if account_id is None:
            return None
        return PublicProfile(
            Network.MASTODON,
            f"{account_id}@{server}",
            username=handle.value,
            name=as_str(account.get("display_name")),
            followers=as_int(account.get("followers_count")),
            following=as_int(account.get("following_count")),
            posts=as_int(account.get("statuses_count")),
            bio=plain(account.get("note")),
            avatar_url=as_str(account.get("avatar")),
            url=as_str(account.get("url")),
            raw=account,
        )
