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
from loot.application.monitoring import (
    MonitoringConfigurationInactiveError,
    MonitoringFactConflictError,
    MonitoringInputChangedError,
    MonitoringLeaseLostError,
    MonitoringPersistenceError,
    MonitoringRunNotFoundError,
)
from loot.persistence.monitoring import (
    DEFAULT_AVAILABILITY_DELAY,
    DEFAULT_LEASE_DURATION,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CATCH_UP,
    DEFAULT_WORKFLOW_VERSION,
    PostgresMonitoringRepository,
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
    "PostgresMonitoringRepository",
    "PostgresSignalWorkflow",
    "ActiveWatchItemConflictError",
    "PostgresWatchlistRepository",
    "DEFAULT_AVAILABILITY_DELAY",
    "DEFAULT_LEASE_DURATION",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_CATCH_UP",
    "DEFAULT_WORKFLOW_VERSION",
    "MonitoringConfigurationInactiveError",
    "MonitoringFactConflictError",
    "MonitoringInputChangedError",
    "MonitoringLeaseLostError",
    "MonitoringPersistenceError",
    "MonitoringRunNotFoundError",
    "WatchItemNotFoundError",
    "WatchItemNotRunnableError",
    "WatchItemTransitionError",
    "WatchItemVersionConflictError",
    "WatchlistFactConflictError",
    "WatchlistPersistenceError",
    "create_postgres_engine",
]
