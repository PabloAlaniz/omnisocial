"""`pip install omnisocial[postgres]`"""

from omnisocial.adapters.stores.postgres import (
    SCHEMA,
    PostgresAssetRepository,
    PostgresAuthorizationStateStore,
    PostgresConnectionRepository,
    PostgresPublicationRepository,
    PostgresQuotaLedger,
    create_schema,
)

__all__ = [
    "SCHEMA",
    "PostgresAssetRepository",
    "PostgresAuthorizationStateStore",
    "PostgresConnectionRepository",
    "PostgresPublicationRepository",
    "PostgresQuotaLedger",
    "create_schema",
]
