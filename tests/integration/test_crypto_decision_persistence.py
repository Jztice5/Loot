"""PostgreSQL Crypto decision persistence end-to-end tests."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa

from loot.contracts import (
    Actionability,
    CandidateEvent,
    CandidateType,
    DecisionTicket,
    Direction,
    Market,
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
)
from loot.persistence import (
    PostgresAnalysisRepository,
    PostgresAuthorizationRepository,
    PostgresOutboxRepository,
    PostgresSignalWorkflow,
    create_postgres_engine,
)
from loot.persistence.schema import (
    decision_proposal_evidence,
    decision_proposals,
    decision_ticket_consumptions,
    decision_tickets,
    evidence_sets,
    inbox_messages,
    outbox_events,
    policy_evaluations,
    signal_instances,
    signal_transitions,
)
from loot.signals import (
    DuplicateDecisionConflictError,
    SignalAuthorizationContext,
    SignalInitializationRequest,
)

_DATABASE_URL = os.environ.get("LOOT_TEST_DATABASE_URL")
_INTEGRATION_CONSUMER = "integration.crypto-candidate"


@unittest.skipUnless(
    _DATABASE_URL,
    "LOOT_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
class CryptoDecisionPersistenceIntegrationTest(unittest.TestCase):
    """Validate restart idempotency and atomic facts against loot_test."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create repositories only for an explicitly configured test database."""

        assert _DATABASE_URL is not None
        cls.engine = create_postgres_engine(_DATABASE_URL)
        with cls.engine.connect() as connection:
            database_name = connection.execute(
                sa.text("SELECT current_database()")
            ).scalar_one()
        if database_name != "loot_test":
            raise RuntimeError("integration tests must connect to loot_test")

    @classmethod
    def tearDownClass(cls) -> None:
        """Dispose PostgreSQL connections after the test class."""

        cls.engine.dispose()

    def setUp(self) -> None:
        """Allocate unique identities and persistence adapters."""

        self._delete_stale_inbox_messages()
        self.signal_workflow = PostgresSignalWorkflow(self.engine)
        self.authorization_repository = PostgresAuthorizationRepository(self.engine)
        self.analysis_repository = PostgresAnalysisRepository(self.engine)
        self.outbox_repository = PostgresOutboxRepository(self.engine)
        self.watch_item_id = uuid4()
        self.correlation_ids: set[UUID] = set()
        self.signal_id: UUID | None = None
        self.proposal_id: UUID | None = None
        self.evidence_id: UUID | None = None
        self.evaluation_id: UUID | None = None
        self.ticket_id: UUID | None = None

    def tearDown(self) -> None:
        """Delete only facts created by this test in foreign-key-safe order."""

        with self.engine.begin() as connection:
            if self.signal_id is not None:
                connection.execute(
                    sa.update(signal_instances)
                    .where(signal_instances.c.id == self.signal_id)
                    .values(latest_decision_ticket_id=None)
                )
            if self.ticket_id is not None:
                connection.execute(
                    sa.delete(decision_ticket_consumptions).where(
                        decision_ticket_consumptions.c.decision_ticket_id
                        == self.ticket_id
                    )
                )
                connection.execute(
                    sa.delete(signal_transitions).where(
                        signal_transitions.c.decision_ticket_id == self.ticket_id
                    )
                )
                connection.execute(
                    sa.delete(decision_tickets).where(
                        decision_tickets.c.id == self.ticket_id
                    )
                )
            if self.evaluation_id is not None:
                connection.execute(
                    sa.delete(policy_evaluations).where(
                        policy_evaluations.c.id == self.evaluation_id
                    )
                )
            if self.proposal_id is not None:
                connection.execute(
                    sa.delete(decision_proposal_evidence).where(
                        decision_proposal_evidence.c.proposal_id == self.proposal_id
                    )
                )
                connection.execute(
                    sa.delete(decision_proposals).where(
                        decision_proposals.c.id == self.proposal_id
                    )
                )
            if self.evidence_id is not None:
                connection.execute(
                    sa.delete(evidence_sets).where(
                        evidence_sets.c.id == self.evidence_id
                    )
                )
            if self.correlation_ids:
                connection.execute(
                    sa.delete(outbox_events).where(
                        outbox_events.c.correlation_id.in_(self.correlation_ids)
                    )
                )
            if self.signal_id is not None:
                connection.execute(
                    sa.delete(signal_instances).where(
                        signal_instances.c.id == self.signal_id
                    )
                )
            connection.execute(
                sa.delete(inbox_messages).where(
                    inbox_messages.c.consumer_name == _INTEGRATION_CONSUMER
                )
            )

    def _delete_stale_inbox_messages(self) -> None:
        """Remove records left by an interrupted prior integration test run."""

        with self.engine.begin() as connection:
            connection.execute(
                sa.delete(inbox_messages).where(
                    inbox_messages.c.consumer_name == _INTEGRATION_CONSUMER
                )
            )

    def test_authorization_transition_and_restart_duplicate(self) -> None:
        now = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
        initialization_correlation = uuid4()
        self.correlation_ids.add(initialization_correlation)
        initialized = self.signal_workflow.initialize(
            SignalInitializationRequest(
                watch_item_id=self.watch_item_id,
                market=Market.CRYPTO,
                instrument_id=uuid4(),
                timeframe=Timeframe.H1,
                signal_type=SignalType.MARKET_STRUCTURE,
                direction=Direction.LONG,
                priority=Priority.HIGH,
                actionability=Actionability.WATCH_ONLY,
                setup_key=f"integration-{uuid4()}",
                initialized_at=now - timedelta(hours=1),
            ),
            correlation_id=initialization_correlation,
        )
        signal = initialized.signal
        self.signal_id = signal.id

        candidate = CandidateEvent(
            id=uuid4(),
            candidate_type=CandidateType.STRUCTURE_BREAKOUT,
            direction=Direction.LONG,
            trigger_reason="CLOSED_ABOVE_REFERENCE_HIGH",
            snapshot_id=uuid4(),
            watch_item_id=self.watch_item_id,
            suggested_skill_group="crypto.market_structure_assessment",
            urgency=Priority.HIGH,
            occurred_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(hours=2),
            dedupe_key=f"integration-candidate:{uuid4()}",
        )
        build_result = DeterministicDecisionBuilder().build(
            CryptoDecisionContext(
                candidate=candidate,
                signal=signal,
                watch_item_version=1,
                context_digest="integration-context-v1",
            )
        )
        self.proposal_id = build_result.proposal.id
        self.evidence_id = build_result.evidence.id
        message_id = uuid4()
        self.correlation_ids.add(message_id)
        first_analysis = self.analysis_repository.record_analysis_result(
            consumer_name=_INTEGRATION_CONSUMER,
            message_id=message_id,
            message_payload={"candidate": candidate.model_dump(mode="json")},
            received_at=now - timedelta(minutes=4),
            processed_at=now - timedelta(minutes=3),
            evidence=(build_result.evidence,),
            proposal=build_result.proposal,
        )
        duplicate_analysis = self.analysis_repository.record_analysis_result(
            consumer_name=_INTEGRATION_CONSUMER,
            message_id=message_id,
            message_payload={"candidate": candidate.model_dump(mode="json")},
            received_at=now - timedelta(minutes=4),
            processed_at=now - timedelta(minutes=2),
            evidence=(build_result.evidence,),
            proposal=build_result.proposal,
        )
        self.assertFalse(first_analysis.duplicate)
        self.assertTrue(duplicate_analysis.duplicate)

        evaluation_request_id = uuid4()
        self.correlation_ids.add(evaluation_request_id)
        policy_decision = CryptoPolicyGate(
            self.authorization_repository
        ).evaluate(
            CryptoPolicyEvaluationRequest(
                evaluation_request_id=evaluation_request_id,
                proposal=build_result.proposal,
                evidence_sets=(build_result.evidence,),
                signal=signal,
                current_context_digest="integration-context-v1",
                watch_item_version=1,
                trading_plan_config_version=None,
                position_version=None,
                evaluated_at=now,
                authorization_expires_at=now + timedelta(hours=1),
                data_quality_ready=True,
                market_rule_allows=True,
            )
        )
        ticket = policy_decision.ticket
        assert ticket is not None
        self.evaluation_id = policy_decision.evaluation.id
        self.ticket_id = ticket.id

        transition_correlation = uuid4()
        self.correlation_ids.add(transition_correlation)
        context = SignalAuthorizationContext(
            watch_item_version=1,
            context_digest="integration-context-v1",
        )
        first_transition = self.signal_workflow.apply(
            ticket,
            context,
            correlation_id=transition_correlation,
            occurred_at=now + timedelta(minutes=1),
        )
        restarted_workflow = PostgresSignalWorkflow(self.engine)
        duplicate_transition = restarted_workflow.apply(
            ticket,
            context,
            correlation_id=uuid4(),
            occurred_at=now + timedelta(minutes=2),
        )

        self.assertTrue(first_transition.changed)
        self.assertEqual(first_transition.signal.state, SignalState.ARMED)
        self.assertTrue(duplicate_transition.duplicate)
        self.assertEqual(duplicate_transition.event, first_transition.event)
        with self.assertRaises(DuplicateDecisionConflictError):
            restarted_workflow.apply(
                DecisionTicket.model_validate(
                    {
                        **ticket.model_dump(),
                        "dedupe_key": f"changed:{ticket.dedupe_key}",
                    }
                ),
                context,
                correlation_id=uuid4(),
                occurred_at=now + timedelta(minutes=2),
            )

        unpublished = self.outbox_repository.list_unpublished(
            limit=20,
            available_at=now + timedelta(hours=1),
        )
        correlated_types = {
            message.event.event_type
            for message in unpublished
            if message.event.correlation_id in self.correlation_ids
        }
        self.assertIn("loot.crypto.SignalInitialized", correlated_types)
        self.assertIn("loot.crypto.DecisionProposalRecorded", correlated_types)
        self.assertIn("loot.crypto.PolicyEvaluationRecorded", correlated_types)
        self.assertIn("loot.crypto.DecisionTicketIssued", correlated_types)
        self.assertIn("loot.crypto.SignalTransitioned", correlated_types)


if __name__ == "__main__":
    unittest.main()
