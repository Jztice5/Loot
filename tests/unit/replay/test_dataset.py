"""Historical market dataset contract and quality tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4, uuid5

from pydantic import ValidationError

from loot.contracts import Market, MarketBar, Timeframe
from loot.replay import (
    HistoricalBarDataset,
    HistoricalDatasetArtifactError,
    HistoricalDatasetQualityError,
    assess_historical_dataset_quality,
    load_historical_dataset,
    write_historical_dataset,
)


class HistoricalBarDatasetTest(unittest.TestCase):
    """Validate deterministic identity and strict dataset publication gates."""

    def setUp(self) -> None:
        self.instrument_id = uuid4()
        self.first_opened_at = datetime(2025, 8, 1, tzinfo=UTC)
        self.first_closed_at = self.first_opened_at + timedelta(hours=1)
        self.generated_at = datetime(2026, 8, 6, tzinfo=UTC)

    def test_complete_h1_range_builds_deterministic_manifest(self) -> None:
        bars = self._bars(3)

        dataset = self._build(bars)
        retried = self._build(
            tuple(
                MarketBar.model_validate(
                    {
                        **bar.model_dump(),
                        "received_at": bar.received_at + timedelta(days=1),
                    }
                )
                for bar in bars
            ),
            generated_at=self.generated_at + timedelta(days=1),
        )

        self.assertTrue(dataset.quality_report.passed)
        self.assertEqual(dataset.manifest.expected_bar_count, 3)
        self.assertEqual(dataset.manifest.actual_bar_count, 3)
        self.assertEqual(dataset.manifest.dataset_id, retried.manifest.dataset_id)
        self.assertEqual(dataset.manifest.content_hash, retried.manifest.content_hash)

    def test_market_fact_correction_changes_dataset_identity(self) -> None:
        bars = self._bars(3)
        corrected_last_bar = MarketBar.model_validate(
            {
                **bars[-1].model_dump(),
                "close_price": Decimal("104"),
            }
        )

        original = self._build(bars)
        corrected = self._build((*bars[:-1], corrected_last_bar))

        self.assertNotEqual(original.manifest.content_hash, corrected.manifest.content_hash)
        self.assertNotEqual(original.manifest.dataset_id, corrected.manifest.dataset_id)

    def test_quality_report_lists_missing_h1_boundary(self) -> None:
        bars = self._bars(3)

        report = self._assess((bars[0], bars[2]))

        self.assertFalse(report.passed)
        self.assertEqual(
            report.missing_bar_closed_at,
            (self.first_closed_at + timedelta(hours=1),),
        )
        with self.assertRaises(HistoricalDatasetQualityError) as captured:
            self._build((bars[0], bars[2]))
        self.assertEqual(captured.exception.report, report)

    def test_quality_report_lists_duplicate_event_and_close_time(self) -> None:
        bars = self._bars(3)
        duplicate_event = self._bar(
            index=1,
            provider_event_id=bars[0].provider_event_id,
        )
        duplicate_close = self._bar(
            index=1,
            provider_event_id="okx:BTC-USDT:1h:duplicate-close",
        )

        report = self._assess((bars[0], duplicate_event, duplicate_close, bars[2]))

        self.assertFalse(report.passed)
        self.assertEqual(
            report.duplicate_provider_event_ids,
            (bars[0].provider_event_id,),
        )
        self.assertEqual(
            report.duplicate_bar_closed_at,
            (self.first_closed_at + timedelta(hours=1),),
        )

    def test_quality_report_lists_unclosed_and_identity_mismatch(self) -> None:
        bars = self._bars(3)
        unclosed = MarketBar.model_validate(
            {
                **bars[0].model_dump(),
                "is_closed": False,
            }
        )
        wrong_provider = MarketBar.model_validate(
            {
                **bars[1].model_dump(),
                "provider": "other.provider",
            }
        )

        report = self._assess((unclosed, wrong_provider, bars[2]))

        self.assertFalse(report.passed)
        self.assertEqual(report.unclosed_provider_event_ids, (unclosed.provider_event_id,))
        self.assertEqual(
            report.identity_mismatch_provider_event_ids,
            (wrong_provider.provider_event_id,),
        )

    def test_build_rejects_out_of_order_input(self) -> None:
        bars = self._bars(3)

        with self.assertRaises(HistoricalDatasetQualityError) as captured:
            self._build((bars[1], bars[0], bars[2]))

        self.assertEqual(
            captured.exception.report.out_of_order_provider_event_ids,
            (bars[0].provider_event_id,),
        )

    def test_manifest_rejects_dataset_identity_mismatch(self) -> None:
        manifest = self._build(self._bars(3)).manifest

        with self.assertRaisesRegex(ValidationError, "dataset_id must match"):
            type(manifest).model_validate(
                {
                    **manifest.model_dump(),
                    "dataset_id": uuid4(),
                }
            )

    def test_dataset_artifact_round_trip_preserves_all_facts(self) -> None:
        dataset = self._build(self._bars(3))

        with tempfile.TemporaryDirectory() as temporary_directory:
            dataset_directory = write_historical_dataset(dataset, temporary_directory)
            loaded = load_historical_dataset(dataset_directory)

            self.assertEqual(
                {path.name for path in dataset_directory.iterdir()},
                {"manifest.json", "quality-report.json", "bars.jsonl"},
            )
            self.assertEqual(loaded, dataset)

    def test_dataset_artifact_rejects_tampered_bar_content(self) -> None:
        dataset = self._build(self._bars(3))

        with tempfile.TemporaryDirectory() as temporary_directory:
            dataset_directory = write_historical_dataset(dataset, temporary_directory)
            bars_path = dataset_directory / "bars.jsonl"
            rows = bars_path.read_text(encoding="utf-8").splitlines()
            tampered = json.loads(rows[-1])
            tampered["volume"] = "999"
            rows[-1] = json.dumps(tampered, ensure_ascii=True, sort_keys=True)
            bars_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(
                HistoricalDatasetArtifactError,
                "manifest does not match",
            ):
                load_historical_dataset(dataset_directory)

    def _build(
        self,
        bars: tuple[MarketBar, ...],
        *,
        generated_at: datetime | None = None,
    ) -> HistoricalBarDataset:
        return HistoricalBarDataset.build(
            provider="okx.public_rest",
            market=Market.CRYPTO,
            instrument_id=self.instrument_id,
            timeframe=Timeframe.H1,
            start_bar_closed_at=self.first_closed_at,
            end_bar_closed_at=self.first_closed_at + timedelta(hours=2),
            bars=bars,
            generated_at=generated_at or self.generated_at,
        )

    def _assess(self, bars: tuple[MarketBar, ...]):
        return assess_historical_dataset_quality(
            provider="okx.public_rest",
            market=Market.CRYPTO,
            instrument_id=self.instrument_id,
            timeframe=Timeframe.H1,
            start_bar_closed_at=self.first_closed_at,
            end_bar_closed_at=self.first_closed_at + timedelta(hours=2),
            bars=bars,
        )

    def _bars(self, count: int) -> tuple[MarketBar, ...]:
        return tuple(self._bar(index=index) for index in range(count))

    def _bar(
        self,
        *,
        index: int,
        provider_event_id: str | None = None,
    ) -> MarketBar:
        opened_at = self.first_opened_at + timedelta(hours=index)
        event_id = provider_event_id or f"okx:BTC-USDT:1h:{int(opened_at.timestamp())}"
        open_price = Decimal("100") + index
        return MarketBar(
            id=uuid5(UUID(int=0), event_id),
            provider="okx.public_rest",
            provider_event_id=event_id,
            market=Market.CRYPTO,
            instrument_id=self.instrument_id,
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


if __name__ == "__main__":
    unittest.main()
