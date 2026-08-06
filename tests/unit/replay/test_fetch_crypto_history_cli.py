"""Crypto historical dataset CLI contract tests."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5

from loot.contracts import Market, MarketBar, Timeframe
from loot.domains.crypto import CryptoProviderError
from scripts import fetch_crypto_history


class _HistoricalProvider:
    """Return fixed MarketBar facts and capture the requested research range."""

    provider_name = "okx.public_rest"

    def __init__(self, bars: tuple[MarketBar, ...]) -> None:
        self.bars = bars
        self.calls: list[dict[str, object]] = []

    def fetch_historical_bars(self, instrument, timeframe, **kwargs):
        self.calls.append(
            {
                "instrument": instrument,
                "timeframe": timeframe,
                **kwargs,
            }
        )
        return self.bars


class _FailingHistoricalProvider:
    """Raise an arbitrary internal error to verify stable CLI redaction."""

    provider_name = "okx.public_rest"

    def fetch_historical_bars(self, instrument, timeframe, **kwargs):
        raise RuntimeError("secret provider implementation detail")


class _UnavailableHistoricalProvider:
    """Raise a Provider error to verify the public CLI category."""

    provider_name = "okx.public_rest"

    def fetch_historical_bars(self, instrument, timeframe, **kwargs):
        raise CryptoProviderError("secret upstream response")


class FetchCryptoHistoryCliTest(unittest.TestCase):
    """Validate explicit inputs and credential-free dataset summaries."""

    def setUp(self) -> None:
        self.first_opened_at = datetime(2025, 8, 1, tzinfo=UTC)
        self.first_closed_at = self.first_opened_at + timedelta(hours=1)
        self.generated_at = datetime(2026, 8, 6, tzinfo=UTC)
        self.instrument = fetch_crypto_history.default_btc_usdt_instrument()

    def test_cli_fetches_and_writes_complete_btc_h1_dataset(self) -> None:
        provider = _HistoricalProvider(self._bars(3))

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = fetch_crypto_history.main(
                    [
                        "--start-closed-at",
                        self.first_closed_at.isoformat(),
                        "--end-closed-at",
                        (self.first_closed_at + timedelta(hours=2)).isoformat(),
                        "--output-dir",
                        temporary_directory,
                    ],
                    provider=provider,
                    clock=lambda: self.generated_at,
                )

            payload = json.loads(output.getvalue())
            dataset_directory = Path(temporary_directory) / payload["dataset_id"]
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "COMPLETED")
            self.assertEqual(payload["symbol"], "BTC-USDT")
            self.assertEqual(payload["timeframe"], "1h")
            self.assertEqual(payload["bar_count"], 3)
            self.assertTrue(dataset_directory.is_dir())
            self.assertEqual(provider.calls[0]["instrument"], self.instrument)
            self.assertEqual(provider.calls[0]["timeframe"], Timeframe.H1)

    def test_cli_returns_quality_failure_for_missing_bar(self) -> None:
        bars = self._bars(3)
        provider = _HistoricalProvider((bars[0], bars[2]))

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = fetch_crypto_history.main(
                    [
                        "--start-closed-at",
                        self.first_closed_at.isoformat(),
                        "--end-closed-at",
                        (self.first_closed_at + timedelta(hours=2)).isoformat(),
                        "--output-dir",
                        temporary_directory,
                    ],
                    provider=provider,
                    clock=lambda: self.generated_at,
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertEqual(payload["reason"], "DATASET_QUALITY_FAILED")
            self.assertEqual(payload["missing_bar_count"], 1)
            self.assertEqual(list(Path(temporary_directory).iterdir()), [])

    def test_cli_maps_unexpected_failures_to_stable_error_category(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = fetch_crypto_history.main(
                [
                    "--start-closed-at",
                    self.first_closed_at.isoformat(),
                    "--end-closed-at",
                    self.first_closed_at.isoformat(),
                ],
                provider=_FailingHistoricalProvider(),
                clock=lambda: self.generated_at,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["error_type"], "UnexpectedError")
        self.assertNotIn("RuntimeError", output.getvalue())
        self.assertNotIn("secret", output.getvalue())

    def test_cli_maps_provider_failures_to_stable_error_category(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = fetch_crypto_history.main(
                [
                    "--start-closed-at",
                    self.first_closed_at.isoformat(),
                    "--end-closed-at",
                    self.first_closed_at.isoformat(),
                ],
                provider=_UnavailableHistoricalProvider(),
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["error_type"], "ProviderError")
        self.assertEqual(payload["reason"], "HISTORICAL_PROVIDER_FAILED")
        self.assertNotIn("secret", output.getvalue())

    def _bars(self, count: int) -> tuple[MarketBar, ...]:
        bars = []
        for index in range(count):
            opened_at = self.first_opened_at + timedelta(hours=index)
            event_id = f"okx:BTC-USDT:1h:{int(opened_at.timestamp())}"
            open_price = Decimal("100") + index
            bars.append(
                MarketBar(
                    id=uuid5(UUID(int=0), event_id),
                    provider="okx.public_rest",
                    provider_event_id=event_id,
                    market=Market.CRYPTO,
                    instrument_id=self.instrument.instrument_id,
                    venue="OKX",
                    symbol="BTC-USDT",
                    timeframe=Timeframe.H1,
                    opened_at=opened_at,
                    closed_at=opened_at + timedelta(hours=1),
                    open_price=open_price,
                    high_price=open_price + 2,
                    low_price=open_price - 2,
                    close_price=open_price + 1,
                    volume=Decimal("10") + index,
                    quote_volume=Decimal("1000") + index,
                    is_closed=True,
                    received_at=self.generated_at,
                )
            )
        return tuple(bars)


if __name__ == "__main__":
    unittest.main()
