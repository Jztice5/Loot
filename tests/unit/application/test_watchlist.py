"""Verify REQ-0014 WatchItem application and lifecycle rules."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from loot.application import (
    ChangeWatchItemStatusCommand,
    CreateCryptoWatchItemCommand,
    CryptoRunConfiguration,
    CryptoWatchlistService,
    WatchlistMutationResult,
    default_btc_usdt_instrument,
)
from loot.contracts import (
    Market,
    MonitoringSubscription,
    MonitoringSubscriptionStatus,
    PriceZone,
    Timeframe,
    WatchItemStatus,
)
from loot.watchlist import WatchItemAction, transition_watch_item


class _MemoryWatchlistRepository:
    """Capture application facts without reproducing PostgreSQL behavior."""

    def __init__(self) -> None:
        self.creation: dict[str, Any] | None = None

    def record_creation(self, **kwargs: Any) -> WatchlistMutationResult:
        self.creation = kwargs
        return WatchlistMutationResult(
            instrument=kwargs["instrument"],
            watch_item=kwargs["watch_item"],
            subscriptions=kwargs["subscriptions"],
            duplicate=False,
        )

    def record_transition(
            self,
            command: ChangeWatchItemStatusCommand,
    ) -> WatchlistMutationResult:
        raise NotImplementedError

    def load_run_configuration(
            self,
            watch_item_id: UUID,
            timeframe: Timeframe,
    ) -> CryptoRunConfiguration:
        raise NotImplementedError


class CryptoWatchlistServiceTest(unittest.TestCase):
    """Ensure application commands build stable platform facts."""

    def setUp(self) -> None:
        self.now = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)
        self.repository = _MemoryWatchlistRepository()
        self.service = CryptoWatchlistService(self.repository)

    def test_create_builds_active_h1_subscription(self) -> None:
        watch_item_id = uuid4()
        result = self.service.create(
            CreateCryptoWatchItemCommand(
                request_id=uuid4(),
                watch_item_id=watch_item_id,
                user_id=uuid4(),
                instrument=default_btc_usdt_instrument(),
                occurred_at=self.now,
            )
        )

        self.assertEqual(result.watch_item.status, WatchItemStatus.ACTIVE)
        self.assertEqual(result.watch_item.version, 0)
        self.assertEqual(len(result.subscriptions), 1)
        subscription = result.subscriptions[0]
        self.assertEqual(subscription.watch_item_id, watch_item_id)
        self.assertEqual(subscription.status, MonitoringSubscriptionStatus.ACTIVE)
        self.assertEqual(subscription.config_version, 1)
        self.assertEqual(
            subscription.route_key,
            f"crypto:{result.instrument.instrument_id}:1h",
        )

    def test_create_rejects_non_h1_timeframe(self) -> None:
        with self.assertRaisesRegex(ValueError, "only supports the H1"):
            CreateCryptoWatchItemCommand(
                request_id=uuid4(),
                watch_item_id=uuid4(),
                user_id=uuid4(),
                instrument=default_btc_usdt_instrument(),
                occurred_at=self.now,
                timeframes=(Timeframe.H4,),
            )

    def test_lifecycle_synchronizes_watch_item_and_subscription(self) -> None:
        created = self.service.create(
            CreateCryptoWatchItemCommand(
                request_id=uuid4(),
                watch_item_id=uuid4(),
                user_id=uuid4(),
                instrument=default_btc_usdt_instrument(),
                occurred_at=self.now,
            )
        )

        paused_watch, paused_subscriptions = transition_watch_item(
            created.watch_item,
            created.subscriptions,
            action=WatchItemAction.PAUSE,
            expected_version=0,
            occurred_at=self.now + timedelta(minutes=1),
        )
        resumed_watch, resumed_subscriptions = transition_watch_item(
            paused_watch,
            paused_subscriptions,
            action=WatchItemAction.RESUME,
            expected_version=1,
            occurred_at=self.now + timedelta(minutes=2),
        )
        archived_watch, archived_subscriptions = transition_watch_item(
            resumed_watch,
            resumed_subscriptions,
            action=WatchItemAction.ARCHIVE,
            expected_version=2,
            occurred_at=self.now + timedelta(minutes=3),
        )

        self.assertEqual(archived_watch.status, WatchItemStatus.ARCHIVED)
        self.assertEqual(archived_watch.version, 3)
        self.assertEqual(
            archived_subscriptions[0].status,
            MonitoringSubscriptionStatus.ARCHIVED,
        )
        self.assertEqual(archived_subscriptions[0].config_version, 4)

    def test_archived_watch_item_cannot_resume(self) -> None:
        created = self.service.create(
            CreateCryptoWatchItemCommand(
                request_id=uuid4(),
                watch_item_id=uuid4(),
                user_id=uuid4(),
                instrument=default_btc_usdt_instrument(),
                occurred_at=self.now,
            )
        )
        archived_watch, archived_subscriptions = transition_watch_item(
            created.watch_item,
            created.subscriptions,
            action=WatchItemAction.ARCHIVE,
            expected_version=0,
            occurred_at=self.now + timedelta(minutes=1),
        )

        with self.assertRaisesRegex(ValueError, "not allowed from ARCHIVED"):
            transition_watch_item(
                archived_watch,
                archived_subscriptions,
                action=WatchItemAction.RESUME,
                expected_version=1,
                occurred_at=self.now + timedelta(minutes=2),
            )

    def test_stale_version_is_rejected(self) -> None:
        created = self.service.create(
            CreateCryptoWatchItemCommand(
                request_id=uuid4(),
                watch_item_id=uuid4(),
                user_id=uuid4(),
                instrument=default_btc_usdt_instrument(),
                occurred_at=self.now,
            )
        )

        with self.assertRaisesRegex(ValueError, "expected_version"):
            transition_watch_item(
                created.watch_item,
                created.subscriptions,
                action=WatchItemAction.PAUSE,
                expected_version=1,
                occurred_at=self.now + timedelta(minutes=1),
            )

    def test_create_rejects_duplicate_custom_zones(self) -> None:
        """重复价格区不得形成含糊的 WatchItem 配置。"""

        zone = PriceZone(
            lower_price=Decimal("100"),
            upper_price=Decimal("110"),
            label="support",
        )

        with self.assertRaisesRegex(ValueError, "custom_zones"):
            self.service.create(
                CreateCryptoWatchItemCommand(
                    request_id=uuid4(),
                    watch_item_id=uuid4(),
                    user_id=uuid4(),
                    instrument=default_btc_usdt_instrument(),
                    occurred_at=self.now,
                    custom_zones=(zone, zone),
                )
            )

    def test_non_crypto_subscription_does_not_assume_route_format(self) -> None:
        """共享契约不提前固化尚未设计的其他市场路由格式。"""

        subscription = MonitoringSubscription(
            id=uuid4(),
            watch_item_id=uuid4(),
            market=Market.US_EQUITY,
            instrument_id=uuid4(),
            timeframe=Timeframe.H1,
            route_key="us-equity-provider-specific-route",
            status=MonitoringSubscriptionStatus.ACTIVE,
            config_version=1,
            created_at=self.now,
            updated_at=self.now,
        )

        self.assertEqual(
            subscription.route_key,
            "us-equity-provider-specific-route",
        )


if __name__ == "__main__":
    unittest.main()
