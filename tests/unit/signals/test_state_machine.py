"""Signal State Machine unit tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

from loot.contracts import (
    Actionability,
    DecisionTicket,
    Market,
    Priority,
    SignalInstance,
    SignalState,
    SignalType,
    Timeframe,
)
from loot.signals import (
    DuplicateDecisionConflictError,
    ExpiredSignalTransitionError,
    InvalidSignalTransitionError,
    SignalStateMachine,
    SignalTransitionTimeError,
    SignalTransitionMismatchError,
)


def aware_now() -> datetime:
    """Return the canonical timestamp used by state machine tests."""

    return datetime(2026, 7, 10, 9, 0, tzinfo=UTC)


def sample_signal(
    *,
    state: SignalState = SignalState.OBSERVING,
    market: Market = Market.CRYPTO,
    instrument_id: UUID | None = None,
    last_transition_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> SignalInstance:
    """Build a SignalInstance with stable defaults."""

    instrument_uuid = instrument_id or uuid4()
    return SignalInstance(
        id=uuid4(),
        watch_item_id=uuid4(),
        market=market,
        instrument_id=instrument_uuid,
        timeframe=Timeframe.H1,
        signal_type=SignalType.MARKET_STRUCTURE,
        state=state,
        priority=Priority.HIGH,
        actionability=Actionability.WATCH_ONLY,
        generation=1,
        setup_key=f"setup:{instrument_uuid}:h1:structure:1",
        latest_decision_ticket_id=(
            None if state == SignalState.OBSERVING else uuid4()
        ),
        dedupe_key=f"signal:{instrument_uuid}:h1:structure",
        last_transition_at=last_transition_at or aware_now(),
        expires_at=expires_at,
        version=0 if state == SignalState.OBSERVING else 3,
    )


def sample_ticket(
    signal: SignalInstance,
    *,
    target_state: SignalState,
    ticket_id: UUID | None = None,
    market: Market | None = None,
) -> DecisionTicket:
    """Build a DecisionTicket that matches the given signal by default."""

    return DecisionTicket(
        id=ticket_id or uuid4(),
        market=market or signal.market,
        instrument_id=signal.instrument_id,
        timeframe=signal.timeframe,
        suggested_transition=target_state,
        evidence_refs=[uuid4()],
        skill_versions={"crypto.signal_decision": "1.0.0"},
        rule_version="1.0.0",
        actionability=Actionability.ACTIONABLE_NOW,
        position_impact="WATCHLIST_SIGNAL",
        input_snapshot_id=uuid4(),
        decision_summary="Structure is ready",
        created_at=aware_now(),
    )


class SignalStateMachineTest(unittest.TestCase):
    """Validate Signal State Machine v0.1 behavior."""

    def test_legal_transition_creates_event_and_updates_signal(self) -> None:
        state_machine = SignalStateMachine()
        signal = sample_signal()
        ticket = sample_ticket(signal, target_state=SignalState.ARMED)
        event_id = uuid4()

        result = state_machine.apply(
            signal,
            ticket,
            occurred_at=aware_now(),
            event_id=event_id,
        )

        self.assertTrue(result.changed)
        self.assertFalse(result.duplicate)
        self.assertIsNotNone(result.event)
        self.assertEqual(result.signal.state, SignalState.ARMED)
        self.assertEqual(result.signal.latest_decision_ticket_id, ticket.id)
        self.assertEqual(result.signal.actionability, ticket.actionability)
        self.assertEqual(result.signal.version, signal.version + 1)
        self.assertEqual(result.event.event_id, event_id)
        self.assertEqual(result.event.from_state, SignalState.OBSERVING)
        self.assertEqual(result.event.to_state, SignalState.ARMED)
        self.assertEqual(result.event.decision_ticket_id, ticket.id)

    def test_invalid_transition_is_rejected(self) -> None:
        state_machine = SignalStateMachine()
        signal = sample_signal()
        ticket = sample_ticket(signal, target_state=SignalState.CONFIRMED)

        with self.assertRaises(InvalidSignalTransitionError):
            state_machine.apply(signal, ticket, occurred_at=aware_now())

    def test_duplicate_decision_ticket_returns_existing_result(self) -> None:
        state_machine = SignalStateMachine()
        signal = sample_signal()
        ticket = sample_ticket(signal, target_state=SignalState.ARMED)
        event_id = uuid4()

        first = state_machine.apply(
            signal,
            ticket,
            occurred_at=aware_now(),
            event_id=event_id,
        )
        duplicate = state_machine.apply(
            first.signal,
            ticket,
            occurred_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
            event_id=uuid4(),
        )

        self.assertTrue(duplicate.duplicate)
        self.assertTrue(duplicate.changed)
        self.assertEqual(duplicate.event.event_id, event_id)
        self.assertEqual(duplicate.signal.version, first.signal.version)
        self.assertEqual(state_machine.applied_decision_count(), 1)

    def test_duplicate_ticket_with_changed_payload_is_rejected(self) -> None:
        state_machine = SignalStateMachine()
        signal = sample_signal()
        ticket = sample_ticket(signal, target_state=SignalState.ARMED)
        first = state_machine.apply(signal, ticket, occurred_at=aware_now())
        changed_ticket = DecisionTicket.model_validate(
            {
                **ticket.model_dump(),
                "position_impact": "DIFFERENT_IMPACT",
            }
        )

        with self.assertRaises(DuplicateDecisionConflictError):
            state_machine.apply(
                first.signal,
                changed_ticket,
                occurred_at=aware_now() + timedelta(hours=1),
            )

    def test_transition_after_signal_expiry_is_rejected(self) -> None:
        state_machine = SignalStateMachine()
        signal = sample_signal(
            last_transition_at=aware_now() - timedelta(hours=1),
            expires_at=aware_now() - timedelta(minutes=30),
        )
        ticket = sample_ticket(signal, target_state=SignalState.ARMED)

        with self.assertRaises(ExpiredSignalTransitionError):
            state_machine.apply(signal, ticket, occurred_at=aware_now())

        self.assertEqual(state_machine.applied_decision_count(), 0)

    def test_transition_time_is_normalized_to_utc(self) -> None:
        state_machine = SignalStateMachine()
        signal = sample_signal()
        ticket = sample_ticket(signal, target_state=SignalState.ARMED)
        china_time = datetime(
            2026,
            7,
            10,
            17,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        )

        result = state_machine.apply(signal, ticket, occurred_at=china_time)

        self.assertEqual(result.signal.last_transition_at, aware_now())
        self.assertEqual(result.event.occurred_at, aware_now())

    def test_transition_time_cannot_move_backwards(self) -> None:
        state_machine = SignalStateMachine()
        signal = sample_signal()
        ticket = sample_ticket(signal, target_state=SignalState.ARMED)

        with self.assertRaises(SignalTransitionTimeError):
            state_machine.apply(
                signal,
                ticket,
                occurred_at=aware_now() - timedelta(seconds=1),
            )

    def test_same_state_ticket_is_noop_without_event(self) -> None:
        state_machine = SignalStateMachine()
        signal = sample_signal(state=SignalState.ARMED)
        ticket = sample_ticket(signal, target_state=SignalState.ARMED)

        result = state_machine.apply(signal, ticket, occurred_at=aware_now())

        self.assertFalse(result.changed)
        self.assertFalse(result.duplicate)
        self.assertIsNone(result.event)
        self.assertEqual(result.signal, signal)
        self.assertEqual(result.signal.version, signal.version)

    def test_decision_ticket_must_match_signal_identity(self) -> None:
        state_machine = SignalStateMachine()
        signal = sample_signal()
        ticket = sample_ticket(
            signal,
            target_state=SignalState.ARMED,
            market=Market.A_SHARE,
        )

        with self.assertRaises(SignalTransitionMismatchError):
            state_machine.apply(signal, ticket, occurred_at=aware_now())


if __name__ == "__main__":
    unittest.main()
