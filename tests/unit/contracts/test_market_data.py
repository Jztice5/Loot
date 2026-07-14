"""Market data contract tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from loot.contracts import (
    Market,
    MarketBar,
    MarketBarClosedEvent,
    MarketSnapshot,
    Timeframe,
)

from tests.unit.contracts.test_contracts import RaisesValidationError


def aware_now() -> datetime:
    """Return the canonical timestamp used by market data tests."""

    return datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


def sample_bar(
    *,
    instrument_id=None,
    timeframe: Timeframe = Timeframe.H1,
    opened_at: datetime | None = None,
    provider_event_id: str = "fake:BTC-USDT:h1:1",
    is_closed: bool = True,
    received_at: datetime | None = None,
) -> MarketBar:
    """Build a valid MarketBar with stable defaults."""

    bar_opened_at = opened_at or aware_now()
    return MarketBar(
        id=uuid4(),
        provider="fake.crypto",
        provider_event_id=provider_event_id,
        market=Market.CRYPTO,
        instrument_id=instrument_id or uuid4(),
        venue="FAKE",
        symbol="BTC-USDT",
        timeframe=timeframe,
        opened_at=bar_opened_at,
        closed_at=bar_opened_at + timedelta(hours=1),
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("95"),
        close_price=Decimal("105"),
        volume=Decimal("12"),
        quote_volume=Decimal("1260"),
        is_closed=is_closed,
        received_at=received_at or bar_opened_at + timedelta(hours=1),
    )


class MarketDataContractTest(unittest.TestCase):
    """Validate MarketBar and MarketSnapshot business invariants."""

    def test_market_bar_requires_timezone_aware_open_time(self) -> None:
        with RaisesValidationError("datetime must include timezone"):
            sample_bar(opened_at=datetime(2026, 7, 10, 8, 0))

    def test_market_bar_rejects_invalid_ohlc_shape(self) -> None:
        with RaisesValidationError("high_price must cover"):
            bar = sample_bar()
            MarketBar(
                **bar.model_dump(exclude={"high_price"}),
                high_price=Decimal("99"),
            )

    def test_market_bar_rejects_closed_state_before_real_close_time(self) -> None:
        opened_at = aware_now()

        with RaisesValidationError("closed bar received_at must not be earlier"):
            sample_bar(
                opened_at=opened_at,
                is_closed=True,
                received_at=opened_at + timedelta(minutes=59),
            )

    def test_market_snapshot_requires_ordered_unique_bars(self) -> None:
        instrument_id = uuid4()
        first = sample_bar(
            instrument_id=instrument_id,
            opened_at=aware_now(),
            provider_event_id="fake:1",
        )
        second = sample_bar(
            instrument_id=instrument_id,
            opened_at=aware_now() + timedelta(hours=1),
            provider_event_id="fake:2",
        )

        snapshot = MarketSnapshot.from_bars(
            market=Market.CRYPTO,
            instrument_id=instrument_id,
            timeframe=Timeframe.H1,
            source_provider="fake.crypto",
            as_of=aware_now() + timedelta(hours=2),
            bars=[first, second],
        )

        self.assertEqual(snapshot.bars[0].provider_event_id, "fake:1")
        self.assertIsInstance(snapshot.bars, tuple)
        self.assertEqual(snapshot.latest_bar, second)
        self.assertEqual(snapshot.latest_closed_bar, second)

    def test_market_snapshot_exposes_latest_closed_bar(self) -> None:
        instrument_id = uuid4()
        closed_bar = sample_bar(
            instrument_id=instrument_id,
            opened_at=aware_now(),
            provider_event_id="fake:closed",
            is_closed=True,
        )
        unclosed_bar = sample_bar(
            instrument_id=instrument_id,
            opened_at=aware_now() + timedelta(hours=1),
            provider_event_id="fake:unclosed",
            is_closed=False,
        )

        snapshot = MarketSnapshot.from_bars(
            market=Market.CRYPTO,
            instrument_id=instrument_id,
            timeframe=Timeframe.H1,
            source_provider="fake.crypto",
            as_of=aware_now() + timedelta(hours=1, minutes=30),
            bars=[closed_bar, unclosed_bar],
        )

        self.assertEqual(snapshot.latest_bar, unclosed_bar)
        self.assertEqual(snapshot.latest_closed_bar, closed_bar)
        self.assertEqual(snapshot.closed_bars, (closed_bar,))

    def test_market_snapshot_rejects_duplicate_provider_event_ids(self) -> None:
        instrument_id = uuid4()
        first = sample_bar(
            instrument_id=instrument_id,
            opened_at=aware_now(),
            provider_event_id="fake:duplicate",
        )
        second = sample_bar(
            instrument_id=instrument_id,
            opened_at=aware_now() + timedelta(hours=1),
            provider_event_id="fake:duplicate",
        )

        with RaisesValidationError("provider_event_id must be unique"):
            MarketSnapshot.from_bars(
                market=Market.CRYPTO,
                instrument_id=instrument_id,
                timeframe=Timeframe.H1,
                source_provider="fake.crypto",
                as_of=aware_now() + timedelta(hours=2),
                bars=[first, second],
            )

    def test_market_snapshot_rejects_as_of_before_closed_bar_end(self) -> None:
        bar = sample_bar(opened_at=aware_now())

        with RaisesValidationError("as_of must not be earlier than any closed bar"):
            MarketSnapshot.from_bars(
                market=bar.market,
                instrument_id=bar.instrument_id,
                timeframe=bar.timeframe,
                source_provider=bar.provider,
                as_of=bar.closed_at - timedelta(minutes=1),
                bars=[bar],
            )

    def test_snapshot_content_hash_changes_with_bar_facts(self) -> None:
        bar = sample_bar(opened_at=aware_now())
        changed_volume = MarketBar.model_validate(
            {
                **bar.model_dump(),
                "volume": Decimal("13"),
            }
        )
        changed_closed_state = MarketBar.model_validate(
            {
                **bar.model_dump(),
                "is_closed": False,
            }
        )

        snapshots = [
            MarketSnapshot.from_bars(
                market=bar.market,
                instrument_id=bar.instrument_id,
                timeframe=bar.timeframe,
                source_provider=bar.provider,
                as_of=bar.closed_at,
                bars=[candidate],
            )
            for candidate in (bar, changed_volume, changed_closed_state)
        ]

        self.assertEqual(len({item.snapshot_content_hash for item in snapshots}), 3)
        self.assertEqual(len({item.snapshot_key for item in snapshots}), 3)
        self.assertEqual(len({item.id for item in snapshots}), 3)

    def test_market_snapshot_rejects_mismatched_content_hash(self) -> None:
        bar = sample_bar()
        snapshot = MarketSnapshot.from_bars(
            market=bar.market,
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            source_provider=bar.provider,
            as_of=bar.closed_at,
            bars=[bar],
        )

        with RaisesValidationError("snapshot_content_hash must match"):
            MarketSnapshot.model_validate(
                {
                    **snapshot.model_dump(),
                    "snapshot_content_hash": "0" * 64,
                }
            )

    def test_bar_closed_event_rejects_unclosed_bar(self) -> None:
        bar = sample_bar(is_closed=False)

        with RaisesValidationError("bar must be closed"):
            MarketBarClosedEvent(
                id=uuid4(),
                market=bar.market,
                instrument_id=bar.instrument_id,
                timeframe=bar.timeframe,
                bar=bar,
                occurred_at=bar.closed_at,
                dedupe_key="bar:unclosed",
            )


if __name__ == "__main__":
    unittest.main()
