"""PostgreSQL integration tests for REQ-0014 Crypto WatchItems."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from loot.application import (
    ChangeWatchItemStatusCommand,
    CreateCryptoWatchItemCommand,
    CryptoWatchlistService,
)
from loot.contracts import (
    Instrument,
    InstrumentStatus,
    InstrumentType,
    Market,
    MonitoringSubscriptionStatus,
    WatchItemStatus,
)
from loot.persistence import (
    ActiveWatchItemConflictError,
    PostgresWatchlistRepository,
    WatchItemNotRunnableError,
    WatchItemTransitionError,
    WatchItemVersionConflictError,
    WatchlistFactConflictError,
    create_postgres_engine,
)
from loot.persistence.config import load_local_setting
from loot.persistence.schema import (
    inbox_messages,
    instruments,
    monitoring_subscriptions,
    outbox_events,
    watch_items,
)
from loot.watchlist import WatchItemAction

_DATABASE_URL = load_local_setting("LOOT_TEST_DATABASE_URL")
_CONSUMER_NAME = "loot.application.crypto_watchlist.v1"


@unittest.skipUnless(
    _DATABASE_URL,
    "LOOT_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
class CryptoWatchlistIntegrationTest(unittest.TestCase):
    """Validate transactional lifecycle and restart-safe idempotency."""

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
                    for name in (
                        "instruments",
                        "watch_items",
                        "monitoring_subscriptions",
                    )
                )
        except OperationalError:
            cls.engine.dispose()
            raise RuntimeError(
                "loot_test connection failed; verify local credentials"
            ) from None
        if database_name != "loot_test":
            cls.engine.dispose()
            raise RuntimeError("integration tests must connect to loot_test")
        if not tables_exist:
            cls.engine.dispose()
            raise unittest.SkipTest(
                "run 20260727_0002_crypto_watchlist_monitoring.sql first"
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.repository = PostgresWatchlistRepository(self.engine)
        self.service = CryptoWatchlistService(self.repository)
        self.now = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)
        self.request_ids: set[UUID] = set()
        self.watch_item_ids: set[UUID] = set()
        self.instrument_ids: set[UUID] = set()

    def tearDown(self) -> None:
        with self.engine.begin() as connection:
            if self.request_ids:
                connection.execute(
                    sa.delete(outbox_events).where(
                        outbox_events.c.correlation_id.in_(self.request_ids)
                    )
                )
                connection.execute(
                    sa.delete(inbox_messages).where(
                        inbox_messages.c.consumer_name == _CONSUMER_NAME,
                        inbox_messages.c.message_id.in_(self.request_ids),
                    )
                )
            if self.watch_item_ids:
                connection.execute(
                    sa.delete(monitoring_subscriptions).where(
                        monitoring_subscriptions.c.watch_item_id.in_(
                            self.watch_item_ids
                        )
                    )
                )
                connection.execute(
                    sa.delete(watch_items).where(
                        watch_items.c.id.in_(self.watch_item_ids)
                    )
                )
            if self.instrument_ids:
                connection.execute(
                    sa.delete(instruments).where(
                        instruments.c.instrument_id.in_(self.instrument_ids)
                    )
                )

    def test_create_and_duplicate_load_runnable_configuration(self) -> None:
        request_id = self._request_id()
        watch_item_id = self._watch_item_id()
        instrument = self._instrument()
        command = self._create_command(
            request_id=request_id,
            watch_item_id=watch_item_id,
            user_id=uuid4(),
            instrument=instrument,
        )

        created = self.service.create(command)
        duplicate = self.service.create(command)
        run_configuration = self.service.load_run_configuration(watch_item_id)

        self.assertFalse(created.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.watch_item, created.watch_item)
        self.assertEqual(run_configuration.watch_item.id, watch_item_id)
        self.assertEqual(
            run_configuration.subscription.status,
            MonitoringSubscriptionStatus.ACTIVE,
        )
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    sa.select(sa.func.count()).select_from(watch_items).where(
                        watch_items.c.id == watch_item_id
                    )
                ).scalar_one(),
                1,
            )
            self.assertEqual(
                connection.execute(
                    sa.select(sa.func.count()).select_from(outbox_events).where(
                        outbox_events.c.correlation_id == request_id
                    )
                ).scalar_one(),
                2,
            )

    def test_pause_resume_archive_and_duplicate_return_first_projection(self) -> None:
        created = self.service.create(
            self._create_command(
                request_id=self._request_id(),
                watch_item_id=self._watch_item_id(),
                user_id=uuid4(),
                instrument=self._instrument(),
            )
        )
        pause_command = ChangeWatchItemStatusCommand(
            request_id=self._request_id(),
            watch_item_id=created.watch_item.id,
            expected_version=0,
            action=WatchItemAction.PAUSE,
            occurred_at=self.now + timedelta(minutes=1),
        )
        paused = self.service.change_status(pause_command)
        with self.assertRaises(WatchItemNotRunnableError):
            self.service.load_run_configuration(created.watch_item.id)

        resumed = self.service.change_status(
            ChangeWatchItemStatusCommand(
                request_id=self._request_id(),
                watch_item_id=created.watch_item.id,
                expected_version=1,
                action=WatchItemAction.RESUME,
                occurred_at=self.now + timedelta(minutes=2),
            )
        )
        duplicate_pause = self.service.change_status(pause_command)
        archived = self.service.change_status(
            ChangeWatchItemStatusCommand(
                request_id=self._request_id(),
                watch_item_id=created.watch_item.id,
                expected_version=2,
                action=WatchItemAction.ARCHIVE,
                occurred_at=self.now + timedelta(minutes=3),
            )
        )

        self.assertEqual(paused.watch_item.status, WatchItemStatus.PAUSED)
        self.assertEqual(resumed.watch_item.status, WatchItemStatus.ACTIVE)
        self.assertTrue(duplicate_pause.duplicate)
        self.assertEqual(duplicate_pause.watch_item.status, WatchItemStatus.PAUSED)
        self.assertEqual(duplicate_pause.watch_item.version, 1)
        self.assertEqual(archived.watch_item.status, WatchItemStatus.ARCHIVED)
        with self.assertRaises(WatchItemTransitionError):
            self.service.change_status(
                ChangeWatchItemStatusCommand(
                    request_id=self._request_id(),
                    watch_item_id=created.watch_item.id,
                    expected_version=3,
                    action=WatchItemAction.RESUME,
                    occurred_at=self.now + timedelta(minutes=4),
                )
            )

    def test_resume_rejects_another_active_identity(self) -> None:
        user_id = uuid4()
        instrument = self._instrument()
        first = self.service.create(
            self._create_command(
                request_id=self._request_id(),
                watch_item_id=self._watch_item_id(),
                user_id=user_id,
                instrument=instrument,
            )
        )
        self.service.change_status(
            ChangeWatchItemStatusCommand(
                request_id=self._request_id(),
                watch_item_id=first.watch_item.id,
                expected_version=0,
                action=WatchItemAction.PAUSE,
                occurred_at=self.now + timedelta(minutes=1),
            )
        )
        self.service.create(
            self._create_command(
                request_id=self._request_id(),
                watch_item_id=self._watch_item_id(),
                user_id=user_id,
                instrument=instrument,
                occurred_at=self.now + timedelta(minutes=2),
            )
        )

        with self.assertRaises(ActiveWatchItemConflictError):
            self.service.change_status(
                ChangeWatchItemStatusCommand(
                    request_id=self._request_id(),
                    watch_item_id=first.watch_item.id,
                    expected_version=1,
                    action=WatchItemAction.RESUME,
                    occurred_at=self.now + timedelta(minutes=3),
                )
            )

    def test_stale_version_and_request_payload_conflict_are_rejected(self) -> None:
        request_id = self._request_id()
        watch_item_id = self._watch_item_id()
        instrument = self._instrument()
        created = self.service.create(
            self._create_command(
                request_id=request_id,
                watch_item_id=watch_item_id,
                user_id=uuid4(),
                instrument=instrument,
            )
        )

        stale_request_id = self._request_id()
        with self.assertRaises(WatchItemVersionConflictError):
            self.service.change_status(
                ChangeWatchItemStatusCommand(
                    request_id=stale_request_id,
                    watch_item_id=created.watch_item.id,
                    expected_version=9,
                    action=WatchItemAction.PAUSE,
                    occurred_at=self.now + timedelta(minutes=1),
                )
            )
        retried = self.service.change_status(
            ChangeWatchItemStatusCommand(
                request_id=stale_request_id,
                watch_item_id=created.watch_item.id,
                expected_version=0,
                action=WatchItemAction.PAUSE,
                occurred_at=self.now + timedelta(minutes=1),
            )
        )
        self.assertEqual(retried.watch_item.status, WatchItemStatus.PAUSED)
        self.assertFalse(retried.duplicate)
        with self.assertRaises(WatchlistFactConflictError):
            self.service.create(
                self._create_command(
                    request_id=request_id,
                    watch_item_id=watch_item_id,
                    user_id=uuid4(),
                    instrument=instrument,
                )
            )

    def test_instrument_id_and_natural_identity_cannot_diverge(self) -> None:
        """同一自然身份或稳定 ID 不得绑定另一份 Instrument 事实。"""

        first = self._instrument()
        self.service.create(
            self._create_command(
                request_id=self._request_id(),
                watch_item_id=self._watch_item_id(),
                user_id=uuid4(),
                instrument=first,
            )
        )
        conflicting_id = uuid4()
        self.instrument_ids.add(conflicting_id)
        conflicting = Instrument(
            **{
                **first.model_dump(),
                "instrument_id": conflicting_id,
            }
        )

        with self.assertRaises(WatchlistFactConflictError):
            self.service.create(
                self._create_command(
                    request_id=self._request_id(),
                    watch_item_id=self._watch_item_id(),
                    user_id=uuid4(),
                    instrument=conflicting,
                )
            )

    def _request_id(self) -> UUID:
        value = uuid4()
        self.request_ids.add(value)
        return value

    def _watch_item_id(self) -> UUID:
        value = uuid4()
        self.watch_item_ids.add(value)
        return value

    def _instrument(self) -> Instrument:
        instrument_id = uuid4()
        self.instrument_ids.add(instrument_id)
        return Instrument(
            instrument_id=instrument_id,
            market=Market.CRYPTO,
            venue="OKX",
            symbol=f"TEST-{str(instrument_id)[:8]}-USDT",
            instrument_type=InstrumentType.SPOT,
            quote_currency="USDT",
            timezone="UTC",
            price_scale=4,
            status=InstrumentStatus.ACTIVE,
        )

    def _create_command(
            self,
            *,
            request_id: UUID,
            watch_item_id: UUID,
            user_id: UUID,
            instrument: Instrument,
            occurred_at: datetime | None = None,
    ) -> CreateCryptoWatchItemCommand:
        return CreateCryptoWatchItemCommand(
            request_id=request_id,
            watch_item_id=watch_item_id,
            user_id=user_id,
            instrument=instrument,
            occurred_at=occurred_at or self.now,
        )


if __name__ == "__main__":
    unittest.main()
