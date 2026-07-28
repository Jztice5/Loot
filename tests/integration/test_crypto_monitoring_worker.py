"""REQ-0015 MonitoringRun PostgreSQL concurrency and recovery tests."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from loot.application import (
    ChangeWatchItemStatusCommand,
    CreateCryptoWatchItemCommand,
    CryptoWatchlistService,
    WatchlistMutationResult,
    default_btc_usdt_instrument,
)
from loot.contracts import (
    Instrument,
    MonitoringAttemptStatus,
    MonitoringRunOutcome,
    MonitoringRunPhase,
    MonitoringRunStatus,
)
from loot.domains.crypto import FakeCryptoProvider
from loot.persistence import (
    MonitoringLeaseLostError,
    PostgresMonitoringRepository,
    PostgresWatchlistRepository,
    create_postgres_engine,
)
from loot.persistence.config import load_local_setting
from loot.persistence.schema import (
    inbox_messages,
    instruments,
    monitoring_run_attempts,
    monitoring_runs,
    monitoring_subscriptions,
    outbox_events,
    watch_items,
)
from loot.watchlist import WatchItemAction

_DATABASE_URL = load_local_setting("LOOT_TEST_DATABASE_URL")
_WATCHLIST_CONSUMER = "loot.application.crypto_watchlist.v1"


@unittest.skipUnless(
    _DATABASE_URL,
    "LOOT_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
class CryptoMonitoringWorkerIntegrationTest(unittest.TestCase):
    """验证真实 PostgreSQL 唯一约束、SKIP LOCKED、租约和恢复语义。"""

    @classmethod
    def setUpClass(cls) -> None:
        assert _DATABASE_URL is not None
        cls.engine = create_postgres_engine(_DATABASE_URL)
        try:
            with cls.engine.connect() as connection:
                database_name = connection.execute(
                    sa.text("SELECT current_database()")
                ).scalar_one()
                tables_exist = all(
                    sa.inspect(connection).has_table(name, schema="loot")
                    for name in ("monitoring_runs", "monitoring_run_attempts")
                )
        except OperationalError:
            cls.engine.dispose()
            raise RuntimeError("loot_test connection failed; verify local credentials") from None
        if database_name != "loot_test":
            cls.engine.dispose()
            raise RuntimeError("monitoring integration tests must connect to loot_test")
        if not tables_exist:
            cls.engine.dispose()
            raise unittest.SkipTest(
                "run 20260728_0003_crypto_monitoring_runs.sql first"
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.now = datetime(2026, 7, 28, 8, 2, tzinfo=UTC)
        self.workflow_version = f"test.crypto.monitoring.{uuid4()}"
        self.request_ids: set[UUID] = set()
        self.watch_item_ids: set[UUID] = set()
        self.instrument_ids: set[UUID] = set()
        self.run_ids: set[UUID] = set()
        self.watchlist = CryptoWatchlistService(PostgresWatchlistRepository(self.engine))
        self.repository = PostgresMonitoringRepository(self.engine)

    def tearDown(self) -> None:
        with self.engine.begin() as connection:
            related_run_ids = set(self.run_ids)
            if self.watch_item_ids:
                related_run_ids.update(
                    connection.execute(
                        sa.select(monitoring_runs.c.id).where(
                            monitoring_runs.c.watch_item_id.in_(self.watch_item_ids)
                        )
                    ).scalars()
                )
            if related_run_ids:
                connection.execute(
                    sa.delete(outbox_events).where(
                        outbox_events.c.aggregate_id.in_(related_run_ids)
                    )
                )
                connection.execute(
                    sa.delete(monitoring_runs).where(
                        monitoring_runs.c.id.in_(related_run_ids)
                    )
                )
            if self.request_ids:
                connection.execute(
                    sa.delete(outbox_events).where(
                        outbox_events.c.correlation_id.in_(self.request_ids)
                    )
                )
                connection.execute(
                    sa.delete(inbox_messages).where(
                        inbox_messages.c.consumer_name == _WATCHLIST_CONSUMER,
                        inbox_messages.c.message_id.in_(self.request_ids),
                    )
                )
            if self.watch_item_ids:
                connection.execute(
                    sa.delete(monitoring_subscriptions).where(
                        monitoring_subscriptions.c.watch_item_id.in_(self.watch_item_ids)
                    )
                )
                connection.execute(
                    sa.delete(watch_items).where(watch_items.c.id.in_(self.watch_item_ids))
                )
            if self.instrument_ids:
                connection.execute(
                    sa.delete(instruments).where(
                        instruments.c.instrument_id.in_(self.instrument_ids)
                    )
                )

    def test_duplicate_materialization_concurrent_claim_and_lease_recovery(self) -> None:
        """同一周期一个 Run；一个 lease owner；过期后新 Attempt 接管。"""

        watch = self._create_watch_item()
        subscription_ids = (watch.subscriptions[0].id,)
        created = self.repository.materialize_due_runs(
            now=self.now,
            workflow_version=self.workflow_version,
            subscription_ids=subscription_ids,
        )
        duplicate = self.repository.materialize_due_runs(
            now=self.now,
            workflow_version=self.workflow_version,
            subscription_ids=subscription_ids,
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(duplicate, ())
        run = created[0]
        self.run_ids.add(run.id)

        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = tuple(
                executor.map(
                    lambda worker_id: self.repository.claim_due_run(
                        worker_id=worker_id,
                        now=self.now,
                        workflow_version=self.workflow_version,
                    ),
                    ("worker-a", "worker-b"),
                )
            )
        claimed = next(item for item in claims if item is not None)
        self.assertEqual(sum(item is not None for item in claims), 1)
        assert claimed.lease_token is not None

        reclaimed = self.repository.claim_due_run(
            worker_id="worker-c",
            now=self.now + timedelta(minutes=6),
            workflow_version=self.workflow_version,
        )
        assert reclaimed is not None
        assert reclaimed.lease_token is not None
        self.assertEqual(reclaimed.attempt_count, 2)
        self.assertNotEqual(reclaimed.lease_token, claimed.lease_token)
        with self.assertRaises(MonitoringLeaseLostError):
            self.repository.record_failure(
                run_id=claimed.id,
                lease_token=claimed.lease_token,
                expected_version=claimed.version,
                error_code="STALE_OWNER",
                retryable=False,
                now=self.now + timedelta(minutes=6),
            )

        snapshot = FakeCryptoProvider(
            received_at=self.now + timedelta(minutes=6)
        ).fetch_bars_ending_at(
            self.repository.load_bound_instrument(reclaimed),
            reclaimed.timeframe,
            target_bar_closed_at=reclaimed.target_bar_closed_at,
            limit=4,
        )
        bound = self.repository.bind_input(
            run_id=reclaimed.id,
            lease_token=reclaimed.lease_token,
            expected_version=reclaimed.version,
            snapshot=snapshot,
            evaluated_at=self.now + timedelta(minutes=6),
            now=self.now + timedelta(minutes=6),
        )
        checkpoint = self.repository.record_checkpoint(
            run_id=bound.id,
            lease_token=reclaimed.lease_token,
            expected_version=bound.version,
            phase=MonitoringRunPhase.PREFILTERED,
            now=self.now + timedelta(minutes=6),
        )
        completed = self.repository.complete_run(
            run_id=checkpoint.id,
            lease_token=reclaimed.lease_token,
            expected_version=checkpoint.version,
            outcome=MonitoringRunOutcome.NO_CANDIDATE,
            now=self.now + timedelta(minutes=6),
        )
        attempts = self.repository.list_attempts(completed.id)

        self.assertEqual(completed.status, MonitoringRunStatus.COMPLETED)
        self.assertEqual(
            tuple(item.status for item in attempts),
            (MonitoringAttemptStatus.ABANDONED, MonitoringAttemptStatus.COMPLETED),
        )

    def test_retry_is_not_claimable_before_next_attempt(self) -> None:
        watch = self._create_watch_item()
        run = self.repository.materialize_due_runs(
            now=self.now,
            workflow_version=self.workflow_version,
            subscription_ids=(watch.subscriptions[0].id,),
        )[0]
        self.run_ids.add(run.id)
        claimed = self.repository.claim_due_run(
            worker_id="worker-a",
            now=self.now,
            workflow_version=self.workflow_version,
        )
        assert claimed is not None
        assert claimed.lease_token is not None
        retry_at = self.now + timedelta(seconds=30)

        waiting = self.repository.record_failure(
            run_id=claimed.id,
            lease_token=claimed.lease_token,
            expected_version=claimed.version,
            error_code="PROVIDER_UNAVAILABLE",
            retryable=True,
            next_attempt_at=retry_at,
            now=self.now,
        )

        self.assertEqual(waiting.status, MonitoringRunStatus.RETRY_WAIT)
        self.assertIsNone(
            self.repository.claim_due_run(
                worker_id="worker-b",
                now=retry_at - timedelta(microseconds=1),
                workflow_version=self.workflow_version,
            )
        )
        retried = self.repository.claim_due_run(
            worker_id="worker-b",
            now=retry_at,
            workflow_version=self.workflow_version,
        )
        self.assertIsNotNone(retried)
        assert retried is not None
        self.assertEqual(retried.attempt_count, 2)

    def test_pause_after_materialization_cancels_before_provider(self) -> None:
        created = self._create_watch_item()
        run = self.repository.materialize_due_runs(
            now=self.now,
            workflow_version=self.workflow_version,
            subscription_ids=(created.subscriptions[0].id,),
        )[0]
        self.run_ids.add(run.id)
        request_id = uuid4()
        self.request_ids.add(request_id)
        self.watchlist.change_status(
            ChangeWatchItemStatusCommand(
                request_id=request_id,
                watch_item_id=created.watch_item.id,
                expected_version=created.watch_item.version,
                action=WatchItemAction.PAUSE,
                occurred_at=self.now + timedelta(seconds=1),
            )
        )

        claimed = self.repository.claim_due_run(
            worker_id="worker-a",
            now=self.now + timedelta(seconds=2),
            workflow_version=self.workflow_version,
        )

        self.assertIsNone(claimed)
        canceled = self.repository.get_run(run.id)
        self.assertEqual(canceled.status, MonitoringRunStatus.CANCELED)
        self.assertEqual(canceled.last_error_code, "CONFIGURATION_INACTIVE")
        with self.engine.connect() as connection:
            attempt_count = connection.execute(
                sa.select(sa.func.count()).select_from(monitoring_run_attempts).where(
                    monitoring_run_attempts.c.run_id == run.id
                )
            ).scalar_one()
        self.assertEqual(attempt_count, 0)

    def _create_watch_item(self) -> WatchlistMutationResult:
        request_id = uuid4()
        watch_item_id = uuid4()
        source = default_btc_usdt_instrument()
        instrument = Instrument.model_validate(
            {
                **source.model_dump(),
                "instrument_id": uuid4(),
                "symbol": f"TEST-{str(uuid4())[:8]}-USDT",
            }
        )
        self.request_ids.add(request_id)
        self.watch_item_ids.add(watch_item_id)
        self.instrument_ids.add(instrument.instrument_id)
        return self.watchlist.create(
            CreateCryptoWatchItemCommand(
                request_id=request_id,
                watch_item_id=watch_item_id,
                user_id=uuid4(),
                instrument=instrument,
                occurred_at=self.now - timedelta(minutes=1),
            )
        )


if __name__ == "__main__":
    unittest.main()
