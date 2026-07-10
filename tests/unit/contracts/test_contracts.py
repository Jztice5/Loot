"""Contract model tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from types import TracebackType
from uuid import uuid4

from pydantic import ValidationError

from loot.contracts import (
    Actionability,
    CandidateEvent,
    CandidateType,
    DecisionTicket,
    EventEnvelope,
    EvidenceSet,
    ExitMode,
    InstrumentType,
    Market,
    Position,
    PositionEvent,
    PositionEventType,
    PositionSide,
    PositionStatus,
    Priority,
    SignalEvent,
    SignalInstance,
    SignalState,
    SignalType,
    Timeframe,
    TradingPlan,
    TradingPlanStatus,
    VersionedCondition,
)


def aware_now() -> datetime:
    """Return the canonical timestamp used by contract tests."""

    return datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


class RaisesValidationError:
    """Assertion helper that avoids a hard pytest dependency for Phase 0."""

    def __init__(self, expected_text: str) -> None:
        self.expected_text = expected_text

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            raise AssertionError("ValidationError was not raised")
        if not issubclass(exc_type, ValidationError):
            return False
        if exc_value is None or self.expected_text not in str(exc_value):
            raise AssertionError(
                f"expected validation text {self.expected_text!r}, got {exc_value!r}"
            )
        return True


class ContractModelTest(unittest.TestCase):
    """Validate the first batch of cross-module contracts."""

    def test_event_envelope_requires_timezone_aware_datetime(self) -> None:
        with RaisesValidationError("datetime must include timezone"):
            EventEnvelope(
                event_id=uuid4(),
                event_type="watch_item.created",
                event_version=1,
                occurred_at=datetime(2026, 7, 10, 8, 0),
                producer="platform.watchlist",
                correlation_id=uuid4(),
                partition_key="watch_item:1",
            )

    def test_event_envelope_normalizes_datetime_to_utc(self) -> None:
        event = EventEnvelope(
            event_id=uuid4(),
            event_type="watch_item.created",
            event_version=1,
            occurred_at=datetime(2026, 7, 10, 16, 0, tzinfo=timezone(timedelta(hours=8))),
            producer="platform.watchlist",
            correlation_id=uuid4(),
            partition_key="watch_item:1",
        )

        self.assertEqual(event.occurred_at, aware_now())

    def test_trading_plan_contract_is_immutable(self) -> None:
        plan = TradingPlan(
            id=uuid4(),
            watch_item_id=uuid4(),
            direction="LONG",
            primary_timeframe=Timeframe.H1,
            thesis="Breakout continuation",
            entry_conditions=VersionedCondition(expression="Close above resistance"),
            invalidation=VersionedCondition(expression="Close below invalidation"),
            max_risk_r=Decimal("1.5"),
            exit_mode=ExitMode.STRUCTURE_TRAILING,
            status=TradingPlanStatus.ACTIVE,
            config_version=1,
            created_at=aware_now(),
            updated_at=aware_now(),
            version=0,
        )

        with RaisesValidationError("Instance is frozen"):
            plan.thesis = "Mutated"

    def test_trading_plan_rejects_updated_before_created(self) -> None:
        with RaisesValidationError("updated_at must not be earlier than created_at"):
            TradingPlan(
                id=uuid4(),
                watch_item_id=uuid4(),
                direction="LONG",
                primary_timeframe=Timeframe.H1,
                thesis="Breakout continuation",
                entry_conditions=VersionedCondition(expression="Close above resistance"),
                invalidation=VersionedCondition(expression="Close below invalidation"),
                exit_mode=ExitMode.STRUCTURE_TRAILING,
                status=TradingPlanStatus.ACTIVE,
                config_version=1,
                created_at=aware_now(),
                updated_at=aware_now() - timedelta(minutes=1),
                version=0,
            )

    def test_position_rejects_closed_before_opened(self) -> None:
        with RaisesValidationError("closed_at must not be earlier than opened_at"):
            Position(
                id=uuid4(),
                trading_plan_id=uuid4(),
                instrument_id=uuid4(),
                market=Market.CRYPTO,
                instrument_type=InstrumentType.SPOT,
                side=PositionSide.LONG,
                quantity=Decimal("1"),
                average_entry_price=Decimal("100"),
                status=PositionStatus.CLOSED,
                opened_at=aware_now(),
                closed_at=aware_now() - timedelta(minutes=1),
                version=1,
            )

    def test_position_event_requires_idempotency_key(self) -> None:
        with RaisesValidationError("must not be empty"):
            PositionEvent(
                id=uuid4(),
                position_id=uuid4(),
                event_type=PositionEventType.OPEN,
                quantity_delta=Decimal("1"),
                execution_price=Decimal("100"),
                occurred_at=aware_now(),
                idempotency_key=" ",
                created_at=aware_now(),
            )

    def test_move_stop_event_requires_new_stop(self) -> None:
        with RaisesValidationError("new_stop is required"):
            PositionEvent(
                id=uuid4(),
                position_id=uuid4(),
                event_type=PositionEventType.MOVE_STOP,
                occurred_at=aware_now(),
                idempotency_key="position-1-move-stop-1",
                created_at=aware_now(),
            )

    def test_signal_event_must_represent_state_change(self) -> None:
        with RaisesValidationError("state change"):
            SignalEvent(
                event_id=uuid4(),
                signal_id=uuid4(),
                market=Market.A_SHARE,
                instrument_id=uuid4(),
                signal_type=SignalType.VOLUME_BREAKOUT,
                from_state=SignalState.ARMED,
                to_state=SignalState.ARMED,
                priority=Priority.HIGH,
                actionable_now=False,
                position_impact="PROFIT_PROTECTION",
                decision_ticket_id=uuid4(),
                occurred_at=aware_now(),
                dedupe_key="same-state",
            )

    def test_candidate_event_requires_expiry_after_occurrence(self) -> None:
        with RaisesValidationError("expires_at must be later than occurred_at"):
            CandidateEvent(
                id=uuid4(),
                candidate_type=CandidateType.PRICE_ZONE_APPROACH,
                trigger_reason="Near resistance",
                snapshot_id=uuid4(),
                watch_item_id=uuid4(),
                suggested_skill_group="crypto.structure",
                urgency=Priority.NORMAL,
                occurred_at=aware_now(),
                expires_at=aware_now(),
                dedupe_key="candidate-1",
            )

    def test_evidence_set_requires_expiry_after_observed(self) -> None:
        with RaisesValidationError("expires_at must be later than observed_at"):
            EvidenceSet(
                id=uuid4(),
                skill_run_id=uuid4(),
                skill_id="crypto.pa",
                skill_version="1.0.0",
                input_snapshot_id=uuid4(),
                quality=Decimal("0.8"),
                observed_at=aware_now(),
                expires_at=aware_now(),
            )

    def test_signal_instance_rejects_expiry_before_transition(self) -> None:
        with RaisesValidationError(
            "expires_at must not be earlier than last_transition_at"
        ):
            SignalInstance(
                id=uuid4(),
                watch_item_id=uuid4(),
                market=Market.CRYPTO,
                instrument_id=uuid4(),
                timeframe=Timeframe.H1,
                signal_type=SignalType.MARKET_STRUCTURE,
                state=SignalState.ARMED,
                priority=Priority.HIGH,
                actionability=Actionability.WATCH_ONLY,
                latest_decision_ticket_id=uuid4(),
                dedupe_key="signal-1",
                last_transition_at=aware_now(),
                expires_at=aware_now() - timedelta(minutes=1),
                version=0,
            )

    def test_decision_ticket_requires_evidence_refs_and_skill_versions(self) -> None:
        with RaisesValidationError("List should have at least 1 item"):
            DecisionTicket(
                id=uuid4(),
                market=Market.CRYPTO,
                instrument_id=uuid4(),
                timeframe=Timeframe.H1,
                suggested_transition=SignalState.TRIGGERED,
                evidence_refs=[],
                skill_versions={"crypto.signal_decision": "1.0.0"},
                rule_version="1.0.0",
                actionability=Actionability.WATCH_ONLY,
                position_impact="NONE",
                input_snapshot_id=uuid4(),
                decision_summary="Candidate confirmed",
                created_at=aware_now(),
            )


if __name__ == "__main__":
    unittest.main()
