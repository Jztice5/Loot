"""Crypto Candidate to authorized Signal flow tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from loot.contracts import (
    Actionability,
    CandidateEvent,
    CandidateType,
    Direction,
    EvidenceSet,
    Market,
    PolicyOutcome,
    Priority,
    SignalState,
    SignalType,
    Timeframe,
)
from loot.domains.crypto import (
    CryptoDecisionContext,
    CryptoPolicyEvaluationRequest,
    CryptoPolicyGate,
    DeterministicDecisionBuilder,
    PolicyEvaluationConflictError,
    ProposalEvaluationFinalizedError,
)
from loot.signals import (
    InMemoryAuthorizationRepository,
    SignalAuthorizationContext,
    SignalInitializationRequest,
    SignalStateMachine,
)


def aware_now() -> datetime:
    """Return the canonical flow test timestamp."""

    return datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


def sample_candidate(
        *,
        watch_item_id: UUID,
        direction: Direction = Direction.LONG,
) -> CandidateEvent:
    """Build a stable Crypto structure Candidate."""

    return CandidateEvent(
        id=uuid4(),
        candidate_type=CandidateType.STRUCTURE_BREAKOUT,
        direction=direction,
        trigger_reason="CLOSED_ABOVE_REFERENCE_HIGH",
        snapshot_id=uuid4(),
        watch_item_id=watch_item_id,
        suggested_skill_group="crypto.market_structure_assessment",
        urgency=Priority.NORMAL,
        occurred_at=aware_now() - timedelta(minutes=5),
        expires_at=aware_now() + timedelta(hours=4),
        dedupe_key=f"candidate:{direction.value}:{uuid4()}",
    )


class CryptoDecisionFlowTest(unittest.TestCase):
    """Validate builder, Policy Gate and state machine as one authorization chain."""

    def setUp(self) -> None:
        """Initialize the shared Phase 0 runtime components."""

        self.repository = InMemoryAuthorizationRepository()
        self.state_machine = SignalStateMachine(self.repository)
        self.builder = DeterministicDecisionBuilder()
        self.policy_gate = CryptoPolicyGate(self.repository)
        self.watch_item_id = uuid4()
        self.signal = self.state_machine.initialize(
            SignalInitializationRequest(
                watch_item_id=self.watch_item_id,
                market=Market.CRYPTO,
                instrument_id=uuid4(),
                timeframe=Timeframe.H1,
                signal_type=SignalType.MARKET_STRUCTURE,
                direction=Direction.LONG,
                priority=Priority.HIGH,
                actionability=Actionability.WATCH_ONLY,
                setup_key="btc-structure-long-v1",
                initialized_at=aware_now() - timedelta(hours=1),
            )
        ).signal
        self.candidate = sample_candidate(watch_item_id=self.watch_item_id)
        self.decision_context = CryptoDecisionContext(
            candidate=self.candidate,
            signal=self.signal,
            watch_item_version=3,
            context_digest="crypto-context-v3",
        )

    def policy_request(
            self,
            *,
            evaluation_request_id: UUID | None = None,
            evaluated_at: datetime | None = None,
            data_quality_ready: bool = True,
            market_rule_allows: bool = True,
            defer_until: datetime | None = None,
            evidence: EvidenceSet | None = None,
    ) -> CryptoPolicyEvaluationRequest:
        """Build a Policy request from the current deterministic result."""

        build_result = self.builder.build(self.decision_context)
        selected_evidence = cast(
            EvidenceSet,
            evidence if evidence is not None else build_result.evidence,
        )
        return CryptoPolicyEvaluationRequest(
            evaluation_request_id=evaluation_request_id or uuid4(),
            proposal=build_result.proposal,
            evidence_sets=(selected_evidence,),
            signal=self.signal,
            current_context_digest="crypto-context-v3",
            watch_item_version=3,
            trading_plan_config_version=None,
            position_version=None,
            evaluated_at=evaluated_at or aware_now(),
            authorization_expires_at=aware_now() + timedelta(hours=2),
            data_quality_ready=data_quality_ready,
            market_rule_allows=market_rule_allows,
            defer_until=defer_until,
        )

    def test_builder_is_stable_and_preserves_direction(self) -> None:
        first = self.builder.build(self.decision_context)
        duplicate = self.builder.build(self.decision_context)

        self.assertEqual(duplicate, first)
        self.assertEqual(first.evidence.direction, self.candidate.direction)
        self.assertEqual(first.proposal.direction, self.candidate.direction)
        self.assertEqual(first.proposal.candidate_event_id, self.candidate.id)
        self.assertEqual(first.proposal.input_snapshot_id, self.candidate.snapshot_id)
        self.assertEqual(first.proposal.expected_signal_version, self.signal.version)
        self.assertEqual(first.proposal.suggested_transition, SignalState.ARMED)

    def test_builder_rejects_candidate_signal_direction_mismatch(self) -> None:
        short_candidate = sample_candidate(
            watch_item_id=self.watch_item_id,
            direction=Direction.SHORT,
        )

        with self.assertRaisesRegex(ValueError, "direction"):
            self.builder.build(
                replace(self.decision_context, candidate=short_candidate)
            )

    def test_policy_approves_idempotently_and_issues_one_ticket(self) -> None:
        request_id = uuid4()
        request = self.policy_request(evaluation_request_id=request_id)

        first = self.policy_gate.evaluate(request)
        duplicate = self.policy_gate.evaluate(request)
        later_request = replace(
            request,
            evaluation_request_id=uuid4(),
            evaluated_at=aware_now() + timedelta(minutes=1),
        )
        after_approval = self.policy_gate.evaluate(later_request)

        self.assertEqual(first.evaluation.outcome, PolicyOutcome.APPROVED)
        self.assertIsNotNone(first.ticket)
        self.assertFalse(first.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertTrue(after_approval.duplicate)
        first_ticket = first.ticket
        duplicate_ticket = duplicate.ticket
        after_approval_ticket = after_approval.ticket
        assert first_ticket is not None
        assert duplicate_ticket is not None
        assert after_approval_ticket is not None
        self.assertEqual(duplicate_ticket.id, first_ticket.id)
        self.assertEqual(after_approval_ticket.id, first_ticket.id)
        self.assertEqual(first_ticket.direction, request.proposal.direction)
        self.assertEqual(
            first_ticket.proposal_digest,
            request.proposal.content_digest(),
        )

    def test_approved_proposal_id_cannot_be_reused_with_changed_payload(self) -> None:
        request = self.policy_request()
        self.policy_gate.evaluate(request)
        changed_proposal = request.proposal.model_validate(
            {
                **request.proposal.model_dump(),
                "position_impact": "CHANGED_IMPACT",
            }
        )

        with self.assertRaises(PolicyEvaluationConflictError):
            self.policy_gate.evaluate(
                replace(
                    request,
                    evaluation_request_id=uuid4(),
                    proposal=changed_proposal,
                    evaluated_at=aware_now() + timedelta(minutes=1),
                )
            )

    def test_policy_rejects_without_ticket_and_finalizes_proposal(self) -> None:
        request = self.policy_request(market_rule_allows=False)

        decision = self.policy_gate.evaluate(request)

        self.assertEqual(decision.evaluation.outcome, PolicyOutcome.REJECTED)
        self.assertIn("MARKET_RULE_REJECTED", decision.evaluation.reason_codes)
        self.assertIsNone(decision.ticket)
        with self.assertRaises(ProposalEvaluationFinalizedError):
            self.policy_gate.evaluate(
                replace(
                    request,
                    evaluation_request_id=uuid4(),
                    evaluated_at=aware_now() + timedelta(minutes=1),
                )
            )

    def test_deferred_proposal_can_be_approved_when_data_recovers(self) -> None:
        deferred_request = self.policy_request(
            data_quality_ready=False,
            defer_until=aware_now() + timedelta(minutes=30),
        )
        deferred = self.policy_gate.evaluate(deferred_request)
        recovered_request = replace(
            deferred_request,
            evaluation_request_id=uuid4(),
            evaluated_at=aware_now() + timedelta(minutes=5),
            data_quality_ready=True,
            defer_until=None,
        )

        approved = self.policy_gate.evaluate(recovered_request)

        self.assertEqual(deferred.evaluation.outcome, PolicyOutcome.DEFERRED)
        self.assertIsNone(deferred.ticket)
        self.assertEqual(approved.evaluation.outcome, PolicyOutcome.APPROVED)
        self.assertEqual(approved.evaluation.attempt_number, 2)
        self.assertIsNotNone(approved.ticket)

    def test_policy_rejects_direction_inconsistent_evidence(self) -> None:
        build_result = self.builder.build(self.decision_context)
        wrong_direction_evidence = EvidenceSet.model_validate(
            {
                **build_result.evidence.model_dump(),
                "direction": Direction.SHORT,
            }
        )

        decision = self.policy_gate.evaluate(
            self.policy_request(evidence=wrong_direction_evidence)
        )

        self.assertEqual(decision.evaluation.outcome, PolicyOutcome.REJECTED)
        self.assertIn("DIRECTION_MISMATCH", decision.evaluation.reason_codes)
        self.assertIsNone(decision.ticket)

    def test_duplicate_candidate_chain_produces_one_signal_event(self) -> None:
        first_build = self.builder.build(self.decision_context)
        duplicate_build = self.builder.build(self.decision_context)
        evaluation_request_id = uuid4()
        request = self.policy_request(
            evaluation_request_id=evaluation_request_id,
            evidence=first_build.evidence,
        )
        first_policy = self.policy_gate.evaluate(request)
        duplicate_policy = self.policy_gate.evaluate(
            replace(
                request,
                proposal=duplicate_build.proposal,
                evidence_sets=(duplicate_build.evidence,),
            )
        )
        authorization_context = SignalAuthorizationContext(
            watch_item_version=3,
            context_digest="crypto-context-v3",
        )
        first_ticket = first_policy.ticket
        duplicate_ticket = duplicate_policy.ticket
        assert first_ticket is not None
        assert duplicate_ticket is not None
        first_transition = self.state_machine.apply(
            self.signal,
            first_ticket,
            authorization_context,
            occurred_at=aware_now(),
        )
        duplicate_transition = self.state_machine.apply(
            first_transition.signal,
            duplicate_ticket,
            authorization_context,
            occurred_at=aware_now() + timedelta(minutes=1),
        )

        self.assertEqual(first_build.proposal, duplicate_build.proposal)
        self.assertTrue(duplicate_policy.duplicate)
        self.assertTrue(duplicate_transition.duplicate)
        first_event = first_transition.event
        duplicate_event = duplicate_transition.event
        assert first_event is not None
        assert duplicate_event is not None
        self.assertEqual(
            duplicate_event.event_id,
            first_event.event_id,
        )
        self.assertEqual(self.state_machine.applied_decision_count(), 1)
        self.assertEqual(first_event.candidate_event_id, self.candidate.id)


if __name__ == "__main__":
    unittest.main()
