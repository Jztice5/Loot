"""Crypto market data provider tests."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from loot.contracts import Instrument, InstrumentStatus, InstrumentType, Market, Timeframe
from loot.domains.crypto import (
    CryptoProviderError,
    CryptoTargetWindowUnavailableError,
    FakeCryptoProvider,
    OkxRestCryptoProvider,
)


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

    def test_fake_provider_uses_full_window_for_snapshot_identity(self) -> None:
        provider = FakeCryptoProvider(
            received_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
        )
        instrument = sample_crypto_instrument(venue="FAKE")

        two_bar_snapshot = provider.fetch_recent_bars(
            instrument,
            Timeframe.H1,
            limit=2,
        )
        three_bar_snapshot = provider.fetch_recent_bars(
            instrument,
            Timeframe.H1,
            limit=3,
        )

        self.assertNotEqual(
            two_bar_snapshot.snapshot_content_hash,
            three_bar_snapshot.snapshot_content_hash,
        )
        self.assertNotEqual(two_bar_snapshot.snapshot_key, three_bar_snapshot.snapshot_key)
        self.assertNotEqual(two_bar_snapshot.id, three_bar_snapshot.id)

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

    def test_fake_provider_returns_exact_target_window(self) -> None:
        target = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
        provider = FakeCryptoProvider(received_at=target + timedelta(minutes=5))

        snapshot = provider.fetch_bars_ending_at(
            sample_crypto_instrument(venue="FAKE"),
            Timeframe.H1,
            target_bar_closed_at=target,
            limit=4,
        )

        self.assertEqual(snapshot.bars[-1].closed_at, target)
        self.assertTrue(all(bar.is_closed for bar in snapshot.bars))


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
        self.assertIn("limit=3", captured[0][0])
        self.assertEqual(captured[0][1], 3.0)
        self.assertEqual(snapshot.source_provider, "okx.public_rest")
        self.assertEqual(snapshot.bars[0].open_price, 100)
        self.assertEqual(snapshot.bars[1].close_price, 109)
        self.assertTrue(snapshot.bars[0].is_closed)

    def test_okx_provider_filters_unclosed_bar_by_default(self) -> None:
        def fake_http_get(url: str, timeout: float) -> bytes:
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
                            "0",
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

        provider = OkxRestCryptoProvider(http_get=fake_http_get)
        snapshot = provider.fetch_recent_bars(
            sample_crypto_instrument(),
            Timeframe.H1,
            limit=2,
        )

        self.assertEqual(len(snapshot.bars), 1)
        self.assertEqual(snapshot.latest_closed_bar, snapshot.latest_bar)
        self.assertTrue(snapshot.latest_bar.is_closed)

    def test_okx_provider_can_include_unclosed_bar_explicitly(self) -> None:
        def fake_http_get(url: str, timeout: float) -> bytes:
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
                            "0",
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

        provider = OkxRestCryptoProvider(http_get=fake_http_get)
        snapshot = provider.fetch_recent_bars(
            sample_crypto_instrument(),
            Timeframe.H1,
            limit=2,
            include_unclosed=True,
        )

        self.assertEqual(len(snapshot.bars), 2)
        self.assertFalse(snapshot.latest_bar.is_closed)
        self.assertEqual(snapshot.latest_closed_bar.close_price, 105)

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

    def test_okx_provider_returns_exact_historical_target_window(self) -> None:
        captured: list[str] = []

        def fake_http_get(url: str, timeout: float) -> bytes:
            captured.append(url)
            return json.dumps(
                {
                    "code": "0",
                    "msg": "",
                    "data": [
                        ["1720573200000", "106", "112", "101", "109", "11", "11", "1199", "1"],
                        ["1720569600000", "100", "110", "95", "105", "10", "10", "1050", "1"],
                    ],
                }
            ).encode("utf-8")

        target = datetime(2024, 7, 10, 2, 0, tzinfo=UTC)
        snapshot = OkxRestCryptoProvider(http_get=fake_http_get).fetch_bars_ending_at(
            sample_crypto_instrument(),
            Timeframe.H1,
            target_bar_closed_at=target,
            limit=2,
        )

        self.assertIn("/api/v5/market/history-candles?", captured[0])
        self.assertIn("after=1720576800000", captured[0])
        self.assertEqual(snapshot.bars[-1].closed_at, target)

    def test_okx_provider_rejects_window_that_misses_target(self) -> None:
        def fake_http_get(url: str, timeout: float) -> bytes:
            return json.dumps(
                {
                    "code": "0",
                    "data": [
                        ["1720569600000", "100", "110", "95", "105", "10", "10", "1050", "1"]
                    ],
                }
            ).encode("utf-8")

        with self.assertRaises(CryptoTargetWindowUnavailableError):
            OkxRestCryptoProvider(http_get=fake_http_get).fetch_bars_ending_at(
                sample_crypto_instrument(),
                Timeframe.H1,
                target_bar_closed_at=datetime(2024, 7, 10, 2, 0, tzinfo=UTC),
                limit=1,
            )

    def test_okx_provider_fetches_complete_historical_range_across_pages(self) -> None:
        first_opened_at = datetime(2024, 7, 10, tzinfo=UTC)
        responses = [
            self._history_payload(first_opened_at, indexes=(3, 2)),
            self._history_payload(first_opened_at, indexes=(1, 0)),
        ]
        captured_urls: list[str] = []
        sleep_calls: list[float] = []

        def fake_http_get(url: str, timeout: float) -> bytes:
            captured_urls.append(url)
            return responses[len(captured_urls) - 1]

        provider = OkxRestCryptoProvider(
            http_get=fake_http_get,
            sleep=sleep_calls.append,
            history_request_interval_seconds=0.11,
        )
        bars = provider.fetch_historical_bars(
            sample_crypto_instrument(),
            Timeframe.H1,
            start_bar_closed_at=first_opened_at + timedelta(hours=1),
            end_bar_closed_at=first_opened_at + timedelta(hours=4),
            page_limit=2,
        )

        self.assertEqual([bar.opened_at for bar in bars], [
            first_opened_at + timedelta(hours=index) for index in range(4)
        ])
        first_query = parse_qs(urlparse(captured_urls[0]).query)
        second_query = parse_qs(urlparse(captured_urls[1]).query)
        self.assertEqual(
            first_query["after"],
            [str(int((first_opened_at + timedelta(hours=4)).timestamp() * 1000))],
        )
        self.assertEqual(
            second_query["after"],
            [str(int((first_opened_at + timedelta(hours=2)).timestamp() * 1000))],
        )
        self.assertEqual(sleep_calls, [0.11])

    def test_okx_provider_rejects_incomplete_historical_range(self) -> None:
        first_opened_at = datetime(2024, 7, 10, tzinfo=UTC)
        responses = [
            self._history_payload(first_opened_at, indexes=(3, 2)),
            json.dumps({"code": "0", "msg": "", "data": []}).encode("utf-8"),
        ]
        call_count = 0

        def fake_http_get(url: str, timeout: float) -> bytes:
            nonlocal call_count
            response = responses[call_count]
            call_count += 1
            return response

        provider = OkxRestCryptoProvider(http_get=fake_http_get, sleep=lambda seconds: None)

        with self.assertRaisesRegex(
            CryptoTargetWindowUnavailableError,
            "complete historical range",
        ):
            provider.fetch_historical_bars(
                sample_crypto_instrument(),
                Timeframe.H1,
                start_bar_closed_at=first_opened_at + timedelta(hours=1),
                end_bar_closed_at=first_opened_at + timedelta(hours=4),
                page_limit=2,
            )

    def test_okx_provider_rejects_historical_cursor_without_progress(self) -> None:
        first_opened_at = datetime(2024, 7, 10, tzinfo=UTC)
        repeated_page = self._history_payload(first_opened_at, indexes=(3, 2))
        provider = OkxRestCryptoProvider(
            http_get=lambda url, timeout: repeated_page,
            sleep=lambda seconds: None,
        )

        with self.assertRaisesRegex(CryptoProviderError, "cursor did not advance"):
            provider.fetch_historical_bars(
                sample_crypto_instrument(),
                Timeframe.H1,
                start_bar_closed_at=first_opened_at + timedelta(hours=1),
                end_bar_closed_at=first_opened_at + timedelta(hours=4),
                page_limit=2,
            )

    def test_okx_provider_deduplicates_identical_historical_page_overlap(self) -> None:
        first_opened_at = datetime(2024, 7, 10, tzinfo=UTC)
        responses = [
            self._history_payload(first_opened_at, indexes=(3, 2)),
            self._history_payload(first_opened_at, indexes=(2, 1)),
            self._history_payload(first_opened_at, indexes=(1, 0)),
        ]
        page_clocks = iter(
            datetime(2026, 8, 6, minute=index, tzinfo=UTC) for index in range(3)
        )
        call_count = 0

        def fake_http_get(url: str, timeout: float) -> bytes:
            nonlocal call_count
            response = responses[call_count]
            call_count += 1
            return response

        provider = OkxRestCryptoProvider(
            http_get=fake_http_get,
            sleep=lambda seconds: None,
            clock=lambda: next(page_clocks),
        )

        bars = provider.fetch_historical_bars(
            sample_crypto_instrument(),
            Timeframe.H1,
            start_bar_closed_at=first_opened_at + timedelta(hours=1),
            end_bar_closed_at=first_opened_at + timedelta(hours=4),
            page_limit=2,
        )

        self.assertEqual(len(bars), 4)
        self.assertEqual(len({bar.provider_event_id for bar in bars}), 4)

    def test_okx_provider_rejects_historical_error_response(self) -> None:
        provider = OkxRestCryptoProvider(
            http_get=lambda url, timeout: json.dumps(
                {"code": "50011", "msg": "rate limit"}
            ).encode("utf-8"),
        )
        boundary = datetime(2024, 7, 10, 1, 0, tzinfo=UTC)

        with self.assertRaisesRegex(CryptoProviderError, "rate limit"):
            provider.fetch_historical_bars(
                sample_crypto_instrument(),
                Timeframe.H1,
                start_bar_closed_at=boundary,
                end_bar_closed_at=boundary,
            )

    def test_okx_provider_wraps_historical_network_error(self) -> None:
        provider = OkxRestCryptoProvider(
            http_get=lambda url, timeout: (_ for _ in ()).throw(
                URLError("secret upstream host")
            ),
        )
        boundary = datetime(2024, 7, 10, 1, 0, tzinfo=UTC)

        with self.assertRaisesRegex(CryptoProviderError, "request failed"):
            provider.fetch_historical_bars(
                sample_crypto_instrument(),
                Timeframe.H1,
                start_bar_closed_at=boundary,
                end_bar_closed_at=boundary,
            )

    def test_okx_provider_rejects_unclosed_historical_range(self) -> None:
        first_opened_at = datetime(2024, 7, 10, tzinfo=UTC)
        provider = OkxRestCryptoProvider(
            http_get=lambda url, timeout: self._history_payload(
                first_opened_at,
                indexes=(0,),
                confirm="0",
            ),
        )

        with self.assertRaisesRegex(
            CryptoTargetWindowUnavailableError,
            "complete historical range",
        ):
            provider.fetch_historical_bars(
                sample_crypto_instrument(),
                Timeframe.H1,
                start_bar_closed_at=first_opened_at + timedelta(hours=1),
                end_bar_closed_at=first_opened_at + timedelta(hours=1),
            )

    def test_okx_provider_rejects_reversed_historical_range_before_request(self) -> None:
        provider = OkxRestCryptoProvider(
            http_get=lambda url, timeout: self.fail("must not request invalid range"),
        )
        boundary = datetime(2024, 7, 10, 1, 0, tzinfo=UTC)

        with self.assertRaisesRegex(ValueError, "must not be earlier"):
            provider.fetch_historical_bars(
                sample_crypto_instrument(),
                Timeframe.H1,
                start_bar_closed_at=boundary + timedelta(hours=1),
                end_bar_closed_at=boundary,
            )

    @staticmethod
    def _history_payload(
        first_opened_at: datetime,
        *,
        indexes: tuple[int, ...],
        confirm: str = "1",
    ) -> bytes:
        rows = []
        for index in indexes:
            opened_at = first_opened_at + timedelta(hours=index)
            open_price = 100 + index
            rows.append(
                [
                    str(int(opened_at.timestamp() * 1000)),
                    str(open_price),
                    str(open_price + 2),
                    str(open_price - 2),
                    str(open_price + 1),
                    "10",
                    "10",
                    "1000",
                    confirm,
                ]
            )
        return json.dumps({"code": "0", "msg": "", "data": rows}).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
