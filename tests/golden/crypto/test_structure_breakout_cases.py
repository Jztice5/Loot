"""Executable expectations for Crypto structure breakout Golden Cases."""

from __future__ import annotations

import unittest

from loot.contracts import CandidateType, Direction, Market, Timeframe
from .cases import (
    CryptoGoldenCase,
    load_crypto_structure_golden_cases,
)


class CryptoStructureGoldenCaseTest(unittest.TestCase):
    """锁定 PreFilter 实现之前的 Crypto 结构突破产品判断。"""

    def test_required_directional_scenarios_are_present(self) -> None:
        cases = load_crypto_structure_golden_cases()

        self.assertEqual(
            {case.case_id for case in cases},
            {
                "insufficient-closed-history",
                "range-close-no-break",
                "closed-at-reference-high-no-break",
                "closed-at-reference-low-no-break",
                "closed-long-breakout",
                "closed-short-breakdown",
                "unclosed-long-breakout-ignored",
                "unclosed-short-breakdown-ignored",
            },
        )
        self.assertTrue(
            all(case.snapshot.market == Market.CRYPTO for case in cases)
        )
        self.assertTrue(
            all(case.snapshot.timeframe == Timeframe.H1 for case in cases)
        )

    def test_fixture_facts_match_business_expectations(self) -> None:
        for case in load_crypto_structure_golden_cases():
            with self.subTest(case_id=case.case_id):
                self._assert_business_expectation(case)

    def test_unclosed_breaks_are_not_the_evaluated_trigger(self) -> None:
        cases = {
            case.case_id: case
            for case in load_crypto_structure_golden_cases()
        }

        for case_id in {
            "unclosed-long-breakout-ignored",
            "unclosed-short-breakdown-ignored",
        }:
            with self.subTest(case_id=case_id):
                snapshot = cases[case_id].snapshot
                self.assertFalse(snapshot.latest_bar.is_closed)
                self.assertIsNot(snapshot.latest_bar, snapshot.latest_closed_bar)
                self.assertIsNone(cases[case_id].expectation.candidate_type)

    def test_loading_cases_reproduces_snapshot_identity(self) -> None:
        first_load = load_crypto_structure_golden_cases()
        second_load = load_crypto_structure_golden_cases()

        self.assertEqual(
            [case.snapshot.id for case in first_load],
            [case.snapshot.id for case in second_load],
        )
        self.assertEqual(
            [case.snapshot.snapshot_content_hash for case in first_load],
            [case.snapshot.snapshot_content_hash for case in second_load],
        )

    def _assert_business_expectation(self, case: CryptoGoldenCase) -> None:
        """按 Golden Case 规则直接核对固定事实，不调用未来 PreFilter。"""

        closed_bars = case.snapshot.closed_bars
        trigger_bar = closed_bars[-1]
        self.assertEqual(trigger_bar.close_price, case.expectation.trigger_close)

        if len(closed_bars) < case.lookback_bars + 1:
            self.assertIsNone(case.expectation.reference_high)
            self.assertIsNone(case.expectation.reference_low)
            self.assertIsNone(case.expectation.candidate_type)
            self.assertIsNone(case.expectation.direction)
            self.assertEqual(
                case.expectation.reason_code,
                "INSUFFICIENT_CLOSED_HISTORY",
            )
            return

        reference_bars = closed_bars[-(case.lookback_bars + 1) : -1]
        reference_high = max(bar.high_price for bar in reference_bars)
        reference_low = min(bar.low_price for bar in reference_bars)

        self.assertEqual(reference_high, case.expectation.reference_high)
        self.assertEqual(reference_low, case.expectation.reference_low)

        if trigger_bar.close_price > reference_high:
            actual_candidate_type = CandidateType.STRUCTURE_BREAKOUT
            actual_direction = Direction.LONG
            actual_reason_code = "CLOSED_ABOVE_REFERENCE_HIGH"
        elif trigger_bar.close_price < reference_low:
            actual_candidate_type = CandidateType.STRUCTURE_BREAKOUT
            actual_direction = Direction.SHORT
            actual_reason_code = "CLOSED_BELOW_REFERENCE_LOW"
        else:
            actual_candidate_type = None
            actual_direction = None
            latest_bar = case.snapshot.latest_bar
            unclosed_break = not latest_bar.is_closed and (
                latest_bar.close_price > reference_high
                or latest_bar.close_price < reference_low
            )
            actual_reason_code = (
                "UNCLOSED_BAR_IGNORED"
                if unclosed_break
                else "NO_CLOSED_STRUCTURE_BREAK"
            )

        self.assertEqual(actual_candidate_type, case.expectation.candidate_type)
        self.assertEqual(actual_direction, case.expectation.direction)
        self.assertEqual(actual_reason_code, case.expectation.reason_code)


if __name__ == "__main__":
    unittest.main()
