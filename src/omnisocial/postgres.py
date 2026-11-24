"""`pip install omnisocial[postgres]`"""

from omnisocial.adapters.stores.postgres import (
    SCHEMA,
    PostgresAssetRepository,
    PostgresAuthorizationStateStore,
    PostgresConnectionRepository,
    PostgresPublicationRepository,
    PostgresQuotaLedger,
    PostgresRateLimitStore,
    PostgresServerAppStore,
    create_schema,
)

__all__ = [
    "SCHEMA",
    "PostgresAssetRepository",
    "PostgresAuthorizationStateStore",
    "PostgresConnectionRepository",
    "PostgresPublicationRepository",
    "PostgresQuotaLedger",
    "PostgresRateLimitStore",
    "PostgresServerAppStore",
    "create_schema",
]
