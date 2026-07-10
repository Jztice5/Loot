"""Crypto market data provider tests."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from uuid import uuid4

from loot.contracts import Instrument, InstrumentStatus, InstrumentType, Market, Timeframe
from loot.domains.crypto import CryptoProviderError, FakeCryptoProvider, OkxRestCryptoProvider


def sample_crypto_instrument(*, venue: str = "OKX") -> Instrument:
    """Build a BTC-USDT crypto instrument for provider tests."""

    return Instrument(
        instrument_id=uuid4(),
        market=Market.CRYPTO,
        venue=venue,
        symbol="BTC-USDT",
        instrument_type=InstrumentType.SPOT,
        quote_currency="USDT",
        timezone="UTC",
        price_scale=2,
        status=InstrumentStatus.ACTIVE,
    )


class FakeCryptoProviderTest(unittest.TestCase):
    """Validate deterministic fake crypto bars."""

    def test_fake_provider_returns_stable_ordered_snapshot(self) -> None:
        provider = FakeCryptoProvider(
            received_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
        )
        instrument = sample_crypto_instrument(venue="FAKE")

        snapshot = provider.fetch_recent_bars(
            instrument,
            Timeframe.H1,
            limit=3,
        )

        self.assertEqual(snapshot.source_provider, "fake.crypto")
        self.assertEqual(len(snapshot.bars), 3)
        self.assertLess(snapshot.bars[0].opened_at, snapshot.bars[1].opened_at)
        self.assertTrue(all(bar.is_closed for bar in snapshot.bars))
        self.assertEqual(snapshot.bars[-1].close_price, snapshot.bars[0].close_price + 2)

    def test_fake_provider_rejects_non_crypto_instrument(self) -> None:
        provider = FakeCryptoProvider()
        instrument = Instrument(
            instrument_id=uuid4(),
            market=Market.A_SHARE,
            venue="SSE",
            symbol="600000",
            instrument_type=InstrumentType.STOCK,
            quote_currency="CNY",
            timezone="Asia/Shanghai",
            price_scale=2,
            status=InstrumentStatus.ACTIVE,
        )

        with self.assertRaises(ValueError):
            provider.fetch_recent_bars(instrument, Timeframe.H1, limit=1)


class OkxRestCryptoProviderTest(unittest.TestCase):
    """Validate OKX public REST normalization without real network calls."""

    def test_okx_provider_parses_public_candles_response(self) -> None:
        captured: list[tuple[str, float]] = []

        def fake_http_get(url: str, timeout: float) -> bytes:
            captured.append((url, timeout))
            return json.dumps(
                {
                    "code": "0",
                    "msg": "",
                    "data": [
                        [
                            "1720573200000",
                            "106",
                            "112",
                            "101",
                            "109",
                            "11",
                            "11",
                            "1199",
                            "1",
                        ],
                        [
                            "1720569600000",
                            "100",
                            "110",
                            "95",
                            "105",
                            "10",
                            "10",
                            "1050",
                            "1",
                        ],
                    ],
                }
            ).encode("utf-8")

        provider = OkxRestCryptoProvider(
            base_url="https://www.okx.com",
            timeout_seconds=3.0,
            http_get=fake_http_get,
        )
        snapshot = provider.fetch_recent_bars(
            sample_crypto_instrument(),
            Timeframe.H1,
            limit=2,
        )

        self.assertEqual(len(captured), 1)
        self.assertIn("/api/v5/market/candles?", captured[0][0])
        self.assertIn("instId=BTC-USDT", captured[0][0])
        self.assertIn("bar=1H", captured[0][0])
        self.assertEqual(captured[0][1], 3.0)
        self.assertEqual(snapshot.source_provider, "okx.public_rest")
        self.assertEqual(snapshot.bars[0].open_price, 100)
        self.assertEqual(snapshot.bars[1].close_price, 109)
        self.assertTrue(snapshot.bars[0].is_closed)

    def test_okx_provider_rejects_error_response(self) -> None:
        def fake_http_get(url: str, timeout: float) -> bytes:
            return json.dumps({"code": "51001", "msg": "Instrument ID does not exist"}).encode(
                "utf-8"
            )

        provider = OkxRestCryptoProvider(http_get=fake_http_get)

        with self.assertRaises(CryptoProviderError):
            provider.fetch_recent_bars(
                sample_crypto_instrument(),
                Timeframe.H1,
                limit=1,
            )

    def test_okx_provider_rejects_non_okx_venue(self) -> None:
        provider = OkxRestCryptoProvider(http_get=lambda url, timeout: b"{}")

        with self.assertRaises(ValueError):
            provider.fetch_recent_bars(
                sample_crypto_instrument(venue="BINANCE"),
                Timeframe.H1,
                limit=1,
            )


if __name__ == "__main__":
    unittest.main()
