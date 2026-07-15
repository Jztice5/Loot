"""Crypto structure PreFilter tests backed by versioned Golden Cases."""

from __future__ import annotations

import unittest
from uuid import UUID

from loot.contracts import CandidateType, Direction, Market, MarketBar, MarketSnapshot
from loot.domains.crypto import (
    CryptoPreFilterInput,
    CryptoPreFilterReason,
    CryptoStructurePreFilter,
)
from tests.golden.crypto.cases import (
    CryptoGoldenCase,
    load_crypto_structure_golden_cases,
)

_WATCH_ITEM_ID = UUID("8e5d2df5-b630-5c4f-84de-9afbfae09a77")


class CryptoStructurePreFilterTest(unittest.TestCase):
    """验证 Crypto PreFilter 与 Golden Case 产品判断完全一致。"""

    def setUp(self) -> None:
        """为每个测试创建无状态确定性筛选器。"""

        self.prefilter = CryptoStructurePreFilter()
        self.cases = load_crypto_structure_golden_cases()

    def test_prefilter_matches_all_golden_cases(self) -> None:
        for case in self.cases:
            with self.subTest(case_id=case.case_id):
                result = self.prefilter.evaluate(
                    CryptoPreFilterInput(
                        snapshot=case.snapshot,
                        watch_item_id=_WATCH_ITEM_ID,
                    )
                )

                self.assertEqual(result.rule_version, "crypto.structure-breakout.v1")
                self.assertEqual(result.reason.value, case.expectation.reason_code)
                self.assertEqual(result.reference_high, case.expectation.reference_high)
                self.assertEqual(result.reference_low, case.expectation.reference_low)

                candidate = result.candidate
                if case.expectation.candidate_type is None:
                    self.assertIsNone(candidate)
                    continue

                self.assertIsNotNone(candidate)
                assert candidate is not None
                self.assertEqual(candidate.candidate_type, case.expectation.candidate_type)
                self.assertEqual(candidate.direction, case.expectation.direction)
                self.assertEqual(candidate.snapshot_id, case.snapshot.id)
                self.assertEqual(candidate.watch_item_id, _WATCH_ITEM_ID)
                self.assertEqual(candidate.urgency.value, "NORMAL")
                self.assertEqual(
                    candidate.occurred_at,
                    case.snapshot.latest_closed_bar.closed_at,
                )
                self.assertTrue(
                    candidate.trigger_reason.startswith(case.expectation.reason_code)
                )
                self.assertEqual(
                    candidate.suggested_skill_group,
                    "crypto.market_structure_assessment",
                )
                self.assertGreater(candidate.expires_at, case.snapshot.as_of)

    def test_duplicate_input_returns_same_candidate_identity(self) -> None:
        case = self._case("closed-long-breakout")
        input_context = CryptoPreFilterInput(
            snapshot=case.snapshot,
            watch_item_id=_WATCH_ITEM_ID,
        )

        first = self.prefilter.evaluate(input_context).candidate
        second = self.prefilter.evaluate(input_context).candidate

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.dedupe_key, second.dedupe_key)

    def test_long_and_short_candidates_do_not_share_identity(self) -> None:
        long_candidate = self.prefilter.evaluate(
            CryptoPreFilterInput(
                snapshot=self._case("closed-long-breakout").snapshot,
                watch_item_id=_WATCH_ITEM_ID,
            )
        ).candidate
        short_candidate = self.prefilter.evaluate(
            CryptoPreFilterInput(
                snapshot=self._case("closed-short-breakdown").snapshot,
                watch_item_id=_WATCH_ITEM_ID,
            )
        ).candidate

        self.assertIsNotNone(long_candidate)
        self.assertIsNotNone(short_candidate)
        assert long_candidate is not None and short_candidate is not None
        self.assertEqual(long_candidate.direction, Direction.LONG)
        self.assertEqual(short_candidate.direction, Direction.SHORT)
        self.assertNotEqual(long_candidate.id, short_candidate.id)
        self.assertNotEqual(long_candidate.dedupe_key, short_candidate.dedupe_key)

    def test_position_id_is_context_only_and_does_not_change_market_direction(self) -> None:
        case = self._case("closed-short-breakdown")
        position_id = UUID("875c7217-639d-5082-9475-cd7ba5ea9c48")

        without_position = self.prefilter.evaluate(
            CryptoPreFilterInput(
                snapshot=case.snapshot,
                watch_item_id=_WATCH_ITEM_ID,
            )
        ).candidate
        result = self.prefilter.evaluate(
            CryptoPreFilterInput(
                snapshot=case.snapshot,
                watch_item_id=_WATCH_ITEM_ID,
                position_id=position_id,
            )
        )

        self.assertEqual(result.reason, CryptoPreFilterReason.CLOSED_BELOW_REFERENCE_LOW)
        self.assertIsNotNone(result.candidate)
        assert result.candidate is not None
        self.assertEqual(result.candidate.direction, Direction.SHORT)
        self.assertEqual(result.candidate.position_id, position_id)
        self.assertIsNotNone(without_position)
        assert without_position is not None
        self.assertNotEqual(result.candidate.id, without_position.id)
        self.assertNotEqual(result.candidate.dedupe_key, without_position.dedupe_key)

    def test_prefilter_rejects_non_crypto_snapshot(self) -> None:
        case = self._case("closed-long-breakout")
        bars = tuple(
            MarketBar.model_validate(
                {
                    **bar.model_dump(),
                    "market": Market.A_SHARE,
                }
            )
            for bar in case.snapshot.bars
        )
        snapshot = MarketSnapshot.from_bars(
            market=Market.A_SHARE,
            instrument_id=case.snapshot.instrument_id,
            timeframe=case.snapshot.timeframe,
            source_provider=case.snapshot.source_provider,
            as_of=case.snapshot.as_of,
            bars=bars,
        )

        with self.assertRaisesRegex(ValueError, "only accepts CRYPTO"):
            self.prefilter.evaluate(
                CryptoPreFilterInput(
                    snapshot=snapshot,
                    watch_item_id=_WATCH_ITEM_ID,
                )
            )

    def _case(self, case_id: str) -> CryptoGoldenCase:
        """按稳定 case_id 返回 Golden Case。"""

        return next(case for case in self.cases if case.case_id == case_id)


if __name__ == "__main__":
    unittest.main()
