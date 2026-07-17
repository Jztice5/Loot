"""Signal State Machine authorization and lifecycle tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

from loot.contracts import (
    Actionability,
    DecisionProposal,
    DecisionTicket,
    Direction,
    Market,
    PolicyEvaluation,
    PolicyGuardResult,
    PolicyOutcome,
    Priority,
    SignalInstance,
    SignalState,
    SignalType,
    Timeframe,
)
from loot.signals import (
    DuplicateDecisionConflictError,
    ExpiredDecisionTicketError,
    ExpiredSignalTransitionError,
    InMemoryAuthorizationRepository,
    InvalidSignalTransitionError,
    SignalAuthorizationContext,
    SignalContextConflictError,
    SignalInitializationConflictError,
    SignalInitializationRequest,
    SignalStateMachine,
    SignalTransitionMismatchError,
    SignalTransitionTimeError,
    SignalVersionConflictError,
    UntrustedDecisionTicketError,
)


def aware_now() -> datetime:
    """Return the canonical timestamp used by state machine tests."""

    return datetime(2026, 7, 10, 9, 0, tzinfo=UTC)


def sample_context() -> SignalAuthorizationContext:
    """Build the current business version context."""

    return SignalAuthorizationContext(
        watch_item_version=1,
        context_digest="context-v1",
    )


def initialize_signal(
        state_machine: SignalStateMachine,
        *,
        direction: Direction = Direction.LONG,
        initialized_at: datetime | None = None,
        expires_at: datetime | None = None,
        setup_key: str = "btc-structure-1",
        watch_item_id: UUID | None = None,
        instrument_id: UUID | None = None,
) -> SignalInstance:
    """Initialize an OBSERVING signal through the only legal entry point."""

    result = state_machine.initialize(
        SignalInitializationRequest(
            watch_item_id=watch_item_id or uuid4(),
            market=Market.CRYPTO,
            instrument_id=instrument_id or uuid4(),
            timeframe=Timeframe.H1,
            signal_type=SignalType.MARKET_STRUCTURE,
            direction=direction,
            priority=Priority.HIGH,
            actionability=Actionability.WATCH_ONLY,
            setup_key=setup_key,
            initialized_at=initialized_at or aware_now() - timedelta(hours=1),
            expires_at=expires_at,
        )
    )
    return result.signal


def record_authorization(
        repository: InMemoryAuthorizationRepository,
        signal: SignalInstance,
        *,
        target_state: SignalState,
        direction: Direction | None = None,
        expected_signal_version: int | None = None,
        issued_at: datetime | None = None,
        expires_at: datetime | None = None,
) -> tuple[DecisionProposal, PolicyEvaluation, DecisionTicket]:
    """Record a complete APPROVED authorization chain for a transition test."""

    authorization_direction = direction or signal.direction
    issue_time = issued_at or aware_now() - timedelta(minutes=1)
    expiry_time = expires_at or aware_now() + timedelta(hours=1)
    candidate_event_id = uuid4()
    snapshot_id = uuid4()
    proposal = DecisionProposal(
        id=uuid4(),
        candidate_event_id=candidate_event_id,
        market=signal.market,
        instrument_id=signal.instrument_id,
        timeframe=signal.timeframe,
        signal_type=signal.signal_type,
        direction=authorization_direction,
        signal_id=signal.id,
        suggested_transition=target_state,
        evidence_refs=(uuid4(),),
        skill_versions={"crypto.decision": "1.0.0"},
        rule_version="crypto.decision.v1",
        actionability=Actionability.ACTIONABLE_NOW,
        position_impact="WATCHLIST_SIGNAL",
        input_snapshot_id=snapshot_id,
        expected_signal_version=(
            signal.version
            if expected_signal_version is None
            else expected_signal_version
        ),
        watch_item_version=1,
        context_digest="context-v1",
        decision_summary="Structure is ready",
        created_at=issue_time - timedelta(minutes=1),
        dedupe_key=f"proposal:{uuid4()}",
    )
    proposal_digest = proposal.content_digest()
    evaluation = PolicyEvaluation(
        id=uuid4(),
        evaluation_request_id=uuid4(),
        proposal_id=proposal.id,
        outcome=PolicyOutcome.APPROVED,
        policy_version="crypto.policy.v1",
        proposal_digest=proposal_digest,
        evaluation_context_digest=f"evaluation:{uuid4()}",
        attempt_number=1,
        guard_results=(
            PolicyGuardResult(
                guard_id="test.authorization",
                passed=True,
                reason_code="PASS",
            ),
        ),
        evaluated_at=issue_time,
        expires_at=expiry_time,
        dedupe_key=f"evaluation:{uuid4()}",
    )
    ticket = DecisionTicket(
        id=uuid4(),
        proposal_id=proposal.id,
        policy_evaluation_id=evaluation.id,
        policy_version=evaluation.policy_version,
        proposal_digest=proposal_digest,
        market=proposal.market,
        instrument_id=proposal.instrument_id,
        timeframe=proposal.timeframe,
        direction=proposal.direction,
        signal_id=proposal.signal_id,
        authorized_transition=proposal.suggested_transition,
        actionability=proposal.actionability,
        position_impact=proposal.position_impact,
        input_snapshot_id=proposal.input_snapshot_id,
        expected_signal_version=proposal.expected_signal_version,
        watch_item_version=proposal.watch_item_version,
        context_digest=proposal.context_digest,
        issued_at=issue_time,
        expires_at=expiry_time,
        dedupe_key=f"ticket:{uuid4()}",
    )
    repository.record_policy_result(proposal, evaluation, ticket)
    return proposal, evaluation, ticket


class SignalStateMachineTest(unittest.TestCase):
    """Validate authorized Signal State Machine v0.1 behavior."""

    def setUp(self) -> None:
        """Create an isolated authorization repository and state machine."""

        self.repository = InMemoryAuthorizationRepository()
        self.state_machine = SignalStateMachine(self.repository)

    def test_initialize_is_idempotent_and_blocks_parallel_active_setup(self) -> None:
        watch_item_id = uuid4()
        instrument_id = uuid4()
        request = SignalInitializationRequest(
            watch_item_id=watch_item_id,
            market=Market.CRYPTO,
            instrument_id=instrument_id,
            timeframe=Timeframe.H1,
            signal_type=SignalType.MARKET_STRUCTURE,
            direction=Direction.LONG,
            priority=Priority.HIGH,
            actionability=Actionability.WATCH_ONLY,
            setup_key="setup-1",
            initialized_at=aware_now() - timedelta(hours=1),
        )

        first = self.state_machine.initialize(request)
        duplicate = self.state_machine.initialize(request)

        self.assertTrue(first.created)
        self.assertFalse(duplicate.created)
        self.assertEqual(duplicate.signal, first.signal)
        with self.assertRaises(SignalInitializationConflictError):
            self.state_machine.initialize(replace(request, setup_key="setup-2"))

    def test_database_projection_can_be_restored_for_authorized_transition(self) -> None:
        signal = initialize_signal(self.state_machine)
        _, _, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
        )
        restarted_state_machine = SignalStateMachine(self.repository)

        restarted_state_machine.restore_projection(
            SignalInstance.model_validate(signal.model_dump())
        )
        result = restarted_state_machine.apply(
            signal,
            ticket,
            sample_context(),
            occurred_at=aware_now(),
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.signal.state, SignalState.ARMED)
        self.assertEqual(result.signal.version, 1)

    def test_build_initial_signal_rejects_invalid_generation(self) -> None:
        request = SignalInitializationRequest(
            watch_item_id=uuid4(),
            market=Market.CRYPTO,
            instrument_id=uuid4(),
            timeframe=Timeframe.H1,
            signal_type=SignalType.MARKET_STRUCTURE,
            direction=Direction.LONG,
            priority=Priority.NORMAL,
            actionability=Actionability.WATCH_ONLY,
            setup_key="setup-invalid-generation",
            initialized_at=aware_now(),
        )

        with self.assertRaisesRegex(ValueError, "generation"):
            SignalStateMachine.build_initial_signal(request, generation=0)

    def test_terminal_signal_allows_next_generation(self) -> None:
        signal = initialize_signal(self.state_machine)
        _, _, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.EXPIRED,
        )
        terminal = self.state_machine.apply(
            signal,
            ticket,
            sample_context(),
            occurred_at=aware_now(),
        ).signal

        next_generation = self.state_machine.initialize(
            SignalInitializationRequest(
                watch_item_id=signal.watch_item_id,
                market=signal.market,
                instrument_id=signal.instrument_id,
                timeframe=signal.timeframe,
                signal_type=signal.signal_type,
                direction=signal.direction,
                priority=signal.priority,
                actionability=signal.actionability,
                setup_key="btc-structure-2",
                initialized_at=aware_now() + timedelta(minutes=1),
            )
        )

        self.assertEqual(terminal.state, SignalState.EXPIRED)
        self.assertEqual(next_generation.signal.generation, 2)
        self.assertNotEqual(next_generation.signal.id, signal.id)

    def test_legal_transition_creates_traced_event(self) -> None:
        signal = initialize_signal(self.state_machine)
        proposal, evaluation, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
        )
        event_id = uuid4()

        result = self.state_machine.apply(
            signal,
            ticket,
            sample_context(),
            occurred_at=aware_now(),
            event_id=event_id,
        )

        self.assertTrue(result.changed)
        self.assertFalse(result.duplicate)
        self.assertEqual(result.signal.state, SignalState.ARMED)
        self.assertEqual(result.signal.latest_decision_ticket_id, ticket.id)
        self.assertEqual(result.signal.version, signal.version + 1)
        event = result.event
        assert event is not None
        self.assertEqual(event.event_id, event_id)
        self.assertEqual(event.direction, Direction.LONG)
        self.assertEqual(event.candidate_event_id, proposal.candidate_event_id)
        self.assertEqual(event.decision_proposal_id, proposal.id)
        self.assertEqual(event.policy_evaluation_id, evaluation.id)
        self.assertEqual(event.decision_ticket_id, ticket.id)
        self.assertEqual(event.input_snapshot_id, proposal.input_snapshot_id)

    def test_invalid_transition_is_rejected(self) -> None:
        signal = initialize_signal(self.state_machine)
        _, _, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.CONFIRMED,
        )

        with self.assertRaises(InvalidSignalTransitionError):
            self.state_machine.apply(
                signal,
                ticket,
                sample_context(),
                occurred_at=aware_now(),
            )

    def test_duplicate_ticket_returns_first_result(self) -> None:
        signal = initialize_signal(self.state_machine)
        _, _, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
        )
        event_id = uuid4()
        first = self.state_machine.apply(
            signal,
            ticket,
            sample_context(),
            occurred_at=aware_now(),
            event_id=event_id,
        )

        duplicate = self.state_machine.apply(
            first.signal,
            ticket,
            sample_context(),
            occurred_at=aware_now() + timedelta(minutes=10),
            event_id=uuid4(),
        )

        self.assertTrue(duplicate.duplicate)
        duplicate_event = duplicate.event
        assert duplicate_event is not None
        self.assertEqual(duplicate_event.event_id, event_id)
        self.assertEqual(duplicate.signal.version, first.signal.version)
        self.assertEqual(self.state_machine.applied_decision_count(), 1)

    def test_duplicate_ticket_with_changed_payload_is_rejected(self) -> None:
        signal = initialize_signal(self.state_machine)
        _, _, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
        )
        first = self.state_machine.apply(
            signal,
            ticket,
            sample_context(),
            occurred_at=aware_now(),
        )
        changed_ticket = DecisionTicket.model_validate(
            {
                **ticket.model_dump(),
                "position_impact": "DIFFERENT_IMPACT",
            }
        )

        with self.assertRaises(DuplicateDecisionConflictError):
            self.state_machine.apply(
                first.signal,
                changed_ticket,
                sample_context(),
                occurred_at=aware_now() + timedelta(minutes=10),
            )

    def test_same_state_authorization_is_noop_without_event(self) -> None:
        signal = initialize_signal(self.state_machine)
        _, _, arm_ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
        )
        armed_signal = self.state_machine.apply(
            signal,
            arm_ticket,
            sample_context(),
            occurred_at=aware_now(),
        ).signal
        _, _, noop_ticket = record_authorization(
            self.repository,
            armed_signal,
            target_state=SignalState.ARMED,
            issued_at=aware_now() + timedelta(minutes=1),
        )

        result = self.state_machine.apply(
            armed_signal,
            noop_ticket,
            sample_context(),
            occurred_at=aware_now() + timedelta(minutes=1),
        )

        self.assertFalse(result.changed)
        self.assertFalse(result.duplicate)
        self.assertIsNone(result.event)
        self.assertEqual(result.signal, armed_signal)

    def test_unregistered_ticket_is_rejected(self) -> None:
        signal = initialize_signal(self.state_machine)
        _, _, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
        )
        unknown_ticket = DecisionTicket.model_validate(
            {**ticket.model_dump(), "id": uuid4()}
        )

        with self.assertRaises(UntrustedDecisionTicketError):
            self.state_machine.apply(
                signal,
                unknown_ticket,
                sample_context(),
                occurred_at=aware_now(),
            )

    def test_expired_ticket_is_rejected(self) -> None:
        signal = initialize_signal(self.state_machine)
        _, _, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
            issued_at=aware_now() - timedelta(hours=2),
            expires_at=aware_now() - timedelta(minutes=1),
        )

        with self.assertRaises(ExpiredDecisionTicketError):
            self.state_machine.apply(
                signal,
                ticket,
                sample_context(),
                occurred_at=aware_now(),
            )

    def test_signal_version_and_context_conflicts_are_rejected(self) -> None:
        signal = initialize_signal(self.state_machine)
        _, _, stale_ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
            expected_signal_version=signal.version + 1,
        )

        with self.assertRaises(SignalVersionConflictError):
            self.state_machine.apply(
                signal,
                stale_ticket,
                sample_context(),
                occurred_at=aware_now(),
            )

        repository = InMemoryAuthorizationRepository()
        state_machine = SignalStateMachine(repository)
        fresh_signal = initialize_signal(state_machine)
        _, _, fresh_ticket = record_authorization(
            repository,
            fresh_signal,
            target_state=SignalState.ARMED,
        )
        with self.assertRaises(SignalContextConflictError):
            state_machine.apply(
                fresh_signal,
                fresh_ticket,
                SignalAuthorizationContext(
                    watch_item_version=2,
                    context_digest="context-v2",
                ),
                occurred_at=aware_now(),
            )

    def test_direction_mismatch_is_rejected(self) -> None:
        signal = initialize_signal(self.state_machine, direction=Direction.LONG)
        _, _, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
            direction=Direction.SHORT,
        )

        with self.assertRaises(SignalTransitionMismatchError):
            self.state_machine.apply(
                signal,
                ticket,
                sample_context(),
                occurred_at=aware_now(),
            )

    def test_signal_expiry_and_backwards_time_are_rejected(self) -> None:
        signal = initialize_signal(
            self.state_machine,
            initialized_at=aware_now() - timedelta(hours=1),
            expires_at=aware_now() - timedelta(minutes=30),
        )
        _, _, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
        )
        with self.assertRaises(ExpiredSignalTransitionError):
            self.state_machine.apply(
                signal,
                ticket,
                sample_context(),
                occurred_at=aware_now(),
            )

        repository = InMemoryAuthorizationRepository()
        state_machine = SignalStateMachine(repository)
        current_signal = initialize_signal(
            state_machine,
            initialized_at=aware_now(),
        )
        _, _, current_ticket = record_authorization(
            repository,
            current_signal,
            target_state=SignalState.ARMED,
            issued_at=aware_now() - timedelta(hours=1),
        )
        with self.assertRaises(SignalTransitionTimeError):
            state_machine.apply(
                current_signal,
                current_ticket,
                sample_context(),
                occurred_at=aware_now() - timedelta(seconds=1),
            )

    def test_transition_time_is_normalized_to_utc(self) -> None:
        signal = initialize_signal(self.state_machine)
        _, _, ticket = record_authorization(
            self.repository,
            signal,
            target_state=SignalState.ARMED,
        )
        china_time = datetime(
            2026,
            7,
            10,
            17,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        )

        result = self.state_machine.apply(
            signal,
            ticket,
            sample_context(),
            occurred_at=china_time,
        )

        self.assertEqual(result.signal.last_transition_at, aware_now())
        event = result.event
        assert event is not None
        self.assertEqual(event.occurred_at, aware_now())


if __name__ == "__main__":
    unittest.main()
