"""PostgreSQL persistence adapters for Loot."""

from loot.persistence.analysis import (
    AnalysisFactConflictError,
    AnalysisPersistenceError,
    AnalysisRecordResult,
    InboxMessageConflictError,
    PostgresAnalysisRepository,
)
from loot.persistence.authorization import PostgresAuthorizationRepository
from loot.persistence.database import create_postgres_engine
from loot.persistence.outbox import (
    OutboxConflictError,
    OutboxMessage,
    PostgresOutboxRepository,
)
from loot.persistence.signal_workflow import PostgresSignalWorkflow
from loot.persistence.watchlist import (
    ActiveWatchItemConflictError,
    PostgresWatchlistRepository,
    WatchItemNotFoundError,
    WatchItemNotRunnableError,
    WatchItemTransitionError,
    WatchItemVersionConflictError,
    WatchlistFactConflictError,
    WatchlistPersistenceError,
)

__all__ = [
    "AnalysisFactConflictError",
    "AnalysisPersistenceError",
    "AnalysisRecordResult",
    "InboxMessageConflictError",
    "OutboxConflictError",
    "OutboxMessage",
    "PostgresAnalysisRepository",
    "PostgresAuthorizationRepository",
    "PostgresOutboxRepository",
    "PostgresSignalWorkflow",
    "ActiveWatchItemConflictError",
    "PostgresWatchlistRepository",
    "WatchItemNotFoundError",
    "WatchItemNotRunnableError",
    "WatchItemTransitionError",
    "WatchItemVersionConflictError",
    "WatchlistFactConflictError",
    "WatchlistPersistenceError",
    "create_postgres_engine",
]
