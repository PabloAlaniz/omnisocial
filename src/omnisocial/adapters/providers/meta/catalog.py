"""Traducción de los nombres comunes de métricas a los de Meta.

Meta da de baja y renombra métricas seguido. Este catálogo cubre lo más usado y se puede reemplazar por
uno propio (`MetaConfig` + `meta_provider(..., catalog=...)`). Antes de depender de una entrada, conviene
confirmarla contra la referencia de la versión que se usa. Ver `docs/meta.md`.
"""

from __future__ import annotations

from omnisocial.adapters.providers.meta.config import FACEBOOK_PAGE, INSTAGRAM_ACCOUNT
from omnisocial.domain.metrics import CanonicalMetric, CatalogEntry, MetricCatalog

DEFAULT_CATALOG = MetricCatalog(
    (
        # Páginas de Facebook.
        CatalogEntry(FACEBOOK_PAGE, CanonicalMetric.FOLLOWERS, "page_follows"),
        CatalogEntry(FACEBOOK_PAGE, CanonicalMetric.REACH, "page_impressions_unique"),
        CatalogEntry(FACEBOOK_PAGE, CanonicalMetric.IMPRESSIONS, "page_impressions"),
        CatalogEntry(FACEBOOK_PAGE, CanonicalMetric.ENGAGEMENTS, "page_post_engagements"),
        CatalogEntry(FACEBOOK_PAGE, CanonicalMetric.VIEWS, "page_views_total"),
        # Cuentas de Instagram. `follower_count` son seguidores nuevos por día, no el total, así que no
        # se traduce a FOLLOWERS: se pide por su nombre propio.
        CatalogEntry(INSTAGRAM_ACCOUNT, CanonicalMetric.REACH, "reach"),
        CatalogEntry(INSTAGRAM_ACCOUNT, CanonicalMetric.IMPRESSIONS, "impressions", until="v22.0"),
        CatalogEntry(INSTAGRAM_ACCOUNT, CanonicalMetric.VIEWS, "views", since="v22.0"),
        CatalogEntry(INSTAGRAM_ACCOUNT, CanonicalMetric.ENGAGEMENTS, "total_interactions"),
    )
)

INSTAGRAM_TOTAL_VALUE_METRICS = frozenset(
    {
        "views",
        "accounts_engaged",
        "total_interactions",
        "likes",
        "comments",
        "shares",
        "saves",
        "replies",
        "profile_links_taps",
        "follows_and_unfollows",
    }
)
"""Métricas de cuenta de Instagram que solo existen como total del período (`metric_type=total_value`)."""
