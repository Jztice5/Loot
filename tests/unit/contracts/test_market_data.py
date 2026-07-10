"""Market data contract tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from loot.contracts import Market, MarketBar, MarketSnapshot, Timeframe

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
        is_closed=True,
        received_at=bar_opened_at + timedelta(hours=1),
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

        snapshot = MarketSnapshot(
            id=uuid4(),
            market=Market.CRYPTO,
            instrument_id=instrument_id,
            timeframe=Timeframe.H1,
            source_provider="fake.crypto",
            as_of=aware_now() + timedelta(hours=2),
            bars=[first, second],
            snapshot_key="snapshot:1",
        )

        self.assertEqual(snapshot.bars[0].provider_event_id, "fake:1")

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
            MarketSnapshot(
                id=uuid4(),
                market=Market.CRYPTO,
                instrument_id=instrument_id,
                timeframe=Timeframe.H1,
                source_provider="fake.crypto",
                as_of=aware_now() + timedelta(hours=2),
                bars=[first, second],
                snapshot_key="snapshot:duplicate",
            )


if __name__ == "__main__":
    unittest.main()
