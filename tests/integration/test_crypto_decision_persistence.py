"""PostgreSQL Crypto decision persistence end-to-end tests."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from loot.contracts import (
    Actionability,
    CandidateEvent,
    CandidateType,
    DecisionProposal,
    DecisionTicket,
    Direction,
    Market,
    PolicyEvaluation,
    PolicyOutcome,
    Priority,
    SignalState,
    SignalInstance,
    SignalType,
    Timeframe,
)
from loot.domains.crypto import (
    CryptoDecisionContext,
    CryptoDecisionBuildResult,
    CryptoPolicyEvaluationRequest,
    CryptoPolicyDecision,
    CryptoPolicyGate,
    DeterministicDecisionBuilder,
)
from loot.persistence import (
    PostgresAnalysisRepository,
    PostgresAuthorizationRepository,
    OutboxConflictError,
    PostgresOutboxRepository,
    PostgresSignalWorkflow,
    create_postgres_engine,
)
from loot.persistence.config import load_local_setting
from loot.persistence.outbox import build_outbox_message, insert_outbox_message
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
    metadata,
)
from loot.signals import (
    AuthorizationConflictError,
    DuplicateDecisionConflictError,
    PolicyRecordResult,
    SignalAuthorizationContext,
    SignalInitializationRequest,
    SignalVersionConflictError,
)

_DATABASE_URL = load_local_setting("LOOT_TEST_DATABASE_URL")
_INTEGRATION_CONSUMER = "integration.crypto-candidate"


class _BarrierAuthorizationRepository(PostgresAuthorizationRepository):
    """Synchronize concurrent Policy writes after both attempts are built."""

    def __init__(self, engine: sa.Engine, barrier: Barrier) -> None:
        super().__init__(engine)
        self._barrier = barrier

    def record_policy_result(
            self,
            proposal: DecisionProposal,
            evaluation: PolicyEvaluation,
            ticket: DecisionTicket | None,
    ) -> PolicyRecordResult:
        """Release both requests together so PostgreSQL resolves the stale attempt."""

        self._barrier.wait(timeout=10)
        return super().record_policy_result(proposal, evaluation, ticket)


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
        try:
            with cls.engine.connect() as connection:
                database_name = connection.execute(
                    sa.text("SELECT current_database()")
                ).scalar_one()
        except OperationalError:
            cls.engine.dispose()
            raise RuntimeError(
                "loot_test connection failed; verify the local loot_app credentials"
            ) from None
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
        self.signal_ids: set[UUID] = set()
        self.proposal_ids: set[UUID] = set()
        self.evidence_ids: set[UUID] = set()
        self.evaluation_ids: set[UUID] = set()
        self.ticket_ids: set[UUID] = set()

    def tearDown(self) -> None:
        """Delete only facts created by this test in foreign-key-safe order."""

        with self.engine.begin() as connection:
            if self.signal_ids:
                connection.execute(
                    sa.update(signal_instances)
                    .where(signal_instances.c.id.in_(self.signal_ids))
                    .values(latest_decision_ticket_id=None)
                )
            if self.ticket_ids:
                connection.execute(
                    sa.delete(decision_ticket_consumptions).where(
                        decision_ticket_consumptions.c.decision_ticket_id.in_(
                            self.ticket_ids
                        )
                    )
                )
                connection.execute(
                    sa.delete(signal_transitions).where(
                        signal_transitions.c.decision_ticket_id.in_(self.ticket_ids)
                    )
                )
                connection.execute(
                    sa.delete(decision_tickets).where(
                        decision_tickets.c.id.in_(self.ticket_ids)
                    )
                )
            if self.signal_ids:
                connection.execute(
                    sa.delete(signal_transitions).where(
                        signal_transitions.c.signal_id.in_(self.signal_ids)
                    )
                )
            if self.evaluation_ids:
                connection.execute(
                    sa.delete(policy_evaluations).where(
                        policy_evaluations.c.id.in_(self.evaluation_ids)
                    )
                )
            if self.proposal_ids:
                connection.execute(
                    sa.delete(decision_proposal_evidence).where(
                        decision_proposal_evidence.c.proposal_id.in_(self.proposal_ids)
                    )
                )
                connection.execute(
                    sa.delete(decision_proposals).where(
                        decision_proposals.c.id.in_(self.proposal_ids)
                    )
                )
            if self.evidence_ids:
                connection.execute(
                    sa.delete(evidence_sets).where(
                        evidence_sets.c.id.in_(self.evidence_ids)
                    )
                )
            if self.correlation_ids:
                connection.execute(
                    sa.delete(outbox_events).where(
                        outbox_events.c.correlation_id.in_(self.correlation_ids)
                    )
                )
            if self.signal_ids:
                connection.execute(
                    sa.delete(signal_instances).where(
                        signal_instances.c.id.in_(self.signal_ids)
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

    def _initialize_signal(self, now: datetime) -> SignalInstance:
        """Initialize and track one unique Crypto Signal."""

        correlation_id = uuid4()
        self.correlation_ids.add(correlation_id)
        result = self.signal_workflow.initialize(
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
            correlation_id=correlation_id,
        )
        self.signal_ids.add(result.signal.id)
        return result.signal

    def _build_decision(
            self,
            signal: SignalInstance,
            now: datetime,
    ) -> tuple[CandidateEvent, CryptoDecisionBuildResult]:
        """Build one unique Candidate, Evidence and Proposal set."""

        candidate = CandidateEvent(
            id=uuid4(),
            candidate_type=CandidateType.STRUCTURE_BREAKOUT,
            direction=signal.direction,
            trigger_reason="CLOSED_ABOVE_REFERENCE_HIGH",
            snapshot_id=uuid4(),
            watch_item_id=signal.watch_item_id,
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
        self.proposal_ids.add(build_result.proposal.id)
        self.evidence_ids.add(build_result.evidence.id)
        return candidate, build_result

    def _record_analysis(
            self,
            candidate: CandidateEvent,
            build_result: CryptoDecisionBuildResult,
            now: datetime,
    ) -> None:
        """Persist and track one Analysis transaction."""

        message_id = uuid4()
        self.correlation_ids.add(message_id)
        self.analysis_repository.record_analysis_result(
            consumer_name=_INTEGRATION_CONSUMER,
            message_id=message_id,
            message_payload={"candidate": candidate.model_dump(mode="json")},
            received_at=now - timedelta(minutes=4),
            processed_at=now - timedelta(minutes=3),
            evidence=(build_result.evidence,),
            proposal=build_result.proposal,
        )

    def _approve(
            self,
            signal: SignalInstance,
            build_result: CryptoDecisionBuildResult,
            now: datetime,
    ) -> CryptoPolicyDecision:
        """Approve and track the persisted authorization facts."""

        evaluation_request_id = uuid4()
        self.correlation_ids.add(evaluation_request_id)
        decision = CryptoPolicyGate(self.authorization_repository).evaluate(
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
        self.evaluation_ids.add(decision.evaluation.id)
        if decision.ticket is not None:
            self.ticket_ids.add(decision.ticket.id)
        return decision

    def test_schema_metadata_and_runtime_role_boundaries_match_database(self) -> None:
        """Verify the live loot_test schema and loot_app permission contract."""

        inspector = sa.inspect(self.engine)
        expected_tables = {table.name: table for table in metadata.sorted_tables}
        self.assertEqual(
            set(inspector.get_table_names(schema="loot")),
            set(expected_tables),
        )

        for table_name, table in expected_tables.items():
            actual_columns = inspector.get_columns(table_name, schema="loot")
            self.assertEqual(
                [column["name"] for column in actual_columns],
                [column.name for column in table.columns],
            )
            for actual, expected in zip(actual_columns, table.columns, strict=True):
                self.assertEqual(actual["nullable"], expected.nullable)
                if isinstance(expected.type, sa.DateTime):
                    actual_type = actual["type"]
                    self.assertIsInstance(actual_type, sa.DateTime)
                    assert isinstance(actual_type, sa.DateTime)
                    self.assertEqual(
                        actual_type.timezone,
                        expected.type.timezone,
                    )
                else:
                    self.assertEqual(
                        str(actual["type"]).upper(),
                        str(expected.type.compile(dialect=self.engine.dialect)).upper(),
                    )

            actual_constraint_names = {
                inspector.get_pk_constraint(table_name, schema="loot")["name"],
                *(
                    item["name"]
                    for item in inspector.get_unique_constraints(
                        table_name,
                        schema="loot",
                    )
                ),
                *(
                    item["name"]
                    for item in inspector.get_foreign_keys(table_name, schema="loot")
                ),
                *(
                    item["name"]
                    for item in inspector.get_check_constraints(
                        table_name,
                        schema="loot",
                    )
                ),
            }
            expected_constraint_names = {
                constraint.name
                for constraint in table.constraints
                if constraint.name is not None
            }
            self.assertEqual(actual_constraint_names, expected_constraint_names)

            actual_indexes = {
                item["name"]: item
                for item in inspector.get_indexes(table_name, schema="loot")
                if not item.get("duplicates_constraint")
            }
            expected_indexes = {index.name: index for index in table.indexes}
            self.assertEqual(set(actual_indexes), set(expected_indexes))
            for index_name, expected_index in expected_indexes.items():
                self.assertEqual(
                    actual_indexes[index_name]["unique"],
                    expected_index.unique,
                )
                actual_options = actual_indexes[index_name].get(
                    "dialect_options",
                    {},
                )
                self.assertEqual(
                    "postgresql_where" in actual_options,
                    expected_index.dialect_options["postgresql"].get("where")
                    is not None,
                )

        with self.engine.connect() as connection:
            role_row = connection.execute(
                sa.text(
                    """
                    SELECT current_database() AS database_name,
                           current_user AS role_name,
                           has_schema_privilege(current_user, 'loot', 'USAGE')
                               AS schema_usage,
                           has_schema_privilege(current_user, 'loot', 'CREATE')
                               AS schema_create,
                           (SELECT bool_and(
                                       has_table_privilege(
                                           current_user,
                                           c.oid,
                                           'SELECT,INSERT,UPDATE,DELETE'
                                       )
                                   )
                              FROM pg_class c
                              JOIN pg_namespace n ON n.oid = c.relnamespace
                             WHERE n.nspname = 'loot' AND c.relkind = 'r')
                               AS all_dml,
                           (SELECT bool_or(
                                       has_table_privilege(
                                           current_user,
                                           c.oid,
                                           'TRUNCATE'
                                       )
                                   )
                              FROM pg_class c
                              JOIN pg_namespace n ON n.oid = c.relnamespace
                             WHERE n.nspname = 'loot' AND c.relkind = 'r')
                               AS any_truncate
                    """
                )
            ).mappings().one()

        self.assertEqual(role_row["database_name"], "loot_test")
        self.assertEqual(role_row["role_name"], "loot_app")
        self.assertTrue(role_row["schema_usage"])
        self.assertFalse(role_row["schema_create"])
        self.assertTrue(role_row["all_dml"])
        self.assertFalse(role_row["any_truncate"])

    def test_concurrent_signal_initialization_creates_one_generation(self) -> None:
        """Serialize two first-generation requests by monitoring identity."""

        now = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
        request = SignalInitializationRequest(
            watch_item_id=self.watch_item_id,
            market=Market.CRYPTO,
            instrument_id=uuid4(),
            timeframe=Timeframe.H1,
            signal_type=SignalType.MARKET_STRUCTURE,
            direction=Direction.LONG,
            priority=Priority.HIGH,
            actionability=Actionability.WATCH_ONLY,
            setup_key=f"concurrent-{uuid4()}",
            initialized_at=now,
        )
        barrier = Barrier(2)
        correlations = (uuid4(), uuid4())
        self.correlation_ids.update(correlations)

        def initialize(correlation_id: UUID):
            barrier.wait(timeout=10)
            return PostgresSignalWorkflow(self.engine).initialize(
                request,
                correlation_id=correlation_id,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(initialize, correlations))

        self.signal_ids.add(results[0].signal.id)
        self.assertEqual(results[0].signal, results[1].signal)
        self.assertEqual(sorted(result.created for result in results), [False, True])
        self.assertEqual(results[0].signal.generation, 1)

    def test_expired_signal_is_reconciled_before_next_generation(self) -> None:
        """Persist a Ticket-free expiry fact before allocating the next generation."""

        now = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
        instrument_id = uuid4()
        initial_correlation = uuid4()
        next_correlation = uuid4()
        self.correlation_ids.update((initial_correlation, next_correlation))
        initial = self.signal_workflow.initialize(
            SignalInitializationRequest(
                watch_item_id=self.watch_item_id,
                market=Market.CRYPTO,
                instrument_id=instrument_id,
                timeframe=Timeframe.H1,
                signal_type=SignalType.MARKET_STRUCTURE,
                direction=Direction.LONG,
                priority=Priority.HIGH,
                actionability=Actionability.WATCH_ONLY,
                setup_key=f"expiring-{uuid4()}",
                initialized_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            ),
            correlation_id=initial_correlation,
        )
        self.signal_ids.add(initial.signal.id)

        next_generation = self.signal_workflow.initialize(
            SignalInitializationRequest(
                watch_item_id=self.watch_item_id,
                market=Market.CRYPTO,
                instrument_id=instrument_id,
                timeframe=Timeframe.H1,
                signal_type=SignalType.MARKET_STRUCTURE,
                direction=Direction.LONG,
                priority=Priority.HIGH,
                actionability=Actionability.WATCH_ONLY,
                setup_key=f"after-expiry-{uuid4()}",
                initialized_at=now,
            ),
            correlation_id=next_correlation,
            detected_at=now,
        )
        self.signal_ids.add(next_generation.signal.id)

        expired = self.signal_workflow.get_signal(initial.signal.id)
        assert expired is not None
        self.assertEqual(expired.state, SignalState.EXPIRED)
        self.assertEqual(expired.last_transition_at, initial.signal.expires_at)
        self.assertEqual(next_generation.signal.generation, 2)

        with self.engine.connect() as connection:
            expiry_transition = connection.execute(
                sa.select(signal_transitions).where(
                    signal_transitions.c.signal_id == initial.signal.id
                )
            ).mappings().one()
            expiry_outbox = connection.execute(
                sa.select(outbox_events.c.event_type).where(
                    outbox_events.c.correlation_id == next_correlation
                )
            ).scalars().all()
            consumption_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(decision_ticket_consumptions)
                .where(decision_ticket_consumptions.c.signal_id == initial.signal.id)
            ).scalar_one()
        self.assertIsNone(expiry_transition["decision_ticket_id"])
        self.assertEqual(expiry_transition["to_state"], SignalState.EXPIRED.value)
        self.assertIn("loot.crypto.SignalExpired", expiry_outbox)
        self.assertEqual(consumption_count, 0)

    def test_concurrent_policy_attempt_rejects_stale_writer(self) -> None:
        """Reject the Policy attempt computed before a concurrent commit."""

        now = datetime(2026, 7, 21, 9, 0, tzinfo=UTC)
        signal = self._initialize_signal(now)
        candidate, build_result = self._build_decision(signal, now)
        self._record_analysis(candidate, build_result, now)
        repository = _BarrierAuthorizationRepository(self.engine, Barrier(2))
        request_ids = (uuid4(), uuid4())
        self.correlation_ids.update(request_ids)

        def request(offset_seconds: int) -> CryptoPolicyEvaluationRequest:
            evaluated_at = now + timedelta(seconds=offset_seconds)
            return CryptoPolicyEvaluationRequest(
                evaluation_request_id=request_ids[offset_seconds],
                proposal=build_result.proposal,
                evidence_sets=(build_result.evidence,),
                signal=signal,
                current_context_digest="integration-context-v1",
                watch_item_version=1,
                trading_plan_config_version=None,
                position_version=None,
                evaluated_at=evaluated_at,
                authorization_expires_at=now + timedelta(hours=1),
                data_quality_ready=False,
                market_rule_allows=True,
                defer_until=evaluated_at + timedelta(minutes=15),
            )

        def evaluate(offset_seconds: int):
            return CryptoPolicyGate(repository).evaluate(request(offset_seconds))

        decisions: list[CryptoPolicyDecision] = []
        errors: list[AuthorizationConflictError] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(executor.submit(evaluate, offset) for offset in (0, 1))
            for future in futures:
                try:
                    decisions.append(future.result())
                except AuthorizationConflictError as error:
                    errors.append(error)

        self.assertEqual(len(decisions), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("attempt_number is stale", str(errors[0]))
        self.assertEqual(decisions[0].evaluation.outcome, PolicyOutcome.DEFERRED)
        self.assertEqual(decisions[0].evaluation.attempt_number, 1)
        self.assertIsNone(decisions[0].ticket)
        self.evaluation_ids.add(decisions[0].evaluation.id)
        self.assertEqual(repository.evaluation_count(build_result.proposal.id), 1)

    def test_concurrent_tickets_serialize_and_reject_stale_signal_version(self) -> None:
        """Allow one Signal transition and reject the second stale Ticket."""

        now = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
        signal = self._initialize_signal(now)
        tickets: list[DecisionTicket] = []
        for _ in range(2):
            candidate, build_result = self._build_decision(signal, now)
            self._record_analysis(candidate, build_result, now)
            decision = self._approve(signal, build_result, now)
            assert decision.ticket is not None
            tickets.append(decision.ticket)

        correlations = (uuid4(), uuid4())
        self.correlation_ids.update(correlations)
        barrier = Barrier(2)

        def apply(index: int):
            barrier.wait(timeout=10)
            return PostgresSignalWorkflow(self.engine).apply(
                tickets[index],
                SignalAuthorizationContext(
                    watch_item_version=1,
                    context_digest="integration-context-v1",
                ),
                correlation_id=correlations[index],
                occurred_at=now + timedelta(minutes=1),
            )

        transitions = []
        errors = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(executor.submit(apply, index) for index in range(2))
            for future in futures:
                try:
                    transitions.append(future.result())
                except Exception as error:  # noqa: BLE001 - verify the exact conflict below.
                    errors.append(error)

        self.assertEqual(len(transitions), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], SignalVersionConflictError)
        self.assertEqual(transitions[0].signal.version, 1)
        self.assertEqual(transitions[0].signal.state, SignalState.ARMED)

        with self.engine.connect() as connection:
            transition_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(signal_transitions)
                .where(signal_transitions.c.decision_ticket_id.in_(self.ticket_ids))
            ).scalar_one()
            consumption_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(decision_ticket_consumptions)
                .where(
                    decision_ticket_consumptions.c.decision_ticket_id.in_(
                        self.ticket_ids
                    )
                )
            ).scalar_one()
        self.assertEqual(transition_count, 1)
        self.assertEqual(consumption_count, 1)

    def test_signal_transaction_rolls_back_when_outbox_conflicts(self) -> None:
        """Rollback Signal, Transition and consumption if Outbox cannot append."""

        now = datetime(2026, 7, 21, 11, 0, tzinfo=UTC)
        signal = self._initialize_signal(now)
        candidate, build_result = self._build_decision(signal, now)
        self._record_analysis(candidate, build_result, now)
        decision = self._approve(signal, build_result, now)
        ticket = decision.ticket
        assert ticket is not None

        conflicting_correlation = uuid4()
        self.correlation_ids.add(conflicting_correlation)
        conflicting_message = build_outbox_message(
            event_id=uuid5(NAMESPACE_URL, f"signal-transition:{ticket.id}"),
            event_type="loot.crypto.ConflictingSignalTransition",
            producer="tests.integration",
            aggregate_type="SignalInstance",
            aggregate_id=signal.id,
            correlation_id=conflicting_correlation,
            causation_id=ticket.id,
            partition_key=str(signal.id),
            payload={"reason": "force transaction rollback"},
            occurred_at=now + timedelta(minutes=1),
        )
        with self.engine.begin() as connection:
            insert_outbox_message(connection, conflicting_message)

        with self.assertRaises(OutboxConflictError):
            self.signal_workflow.apply(
                ticket,
                SignalAuthorizationContext(
                    watch_item_version=1,
                    context_digest="integration-context-v1",
                ),
                correlation_id=uuid4(),
                occurred_at=now + timedelta(minutes=1),
            )

        stored_signal = self.signal_workflow.get_signal(signal.id)
        self.assertEqual(stored_signal, signal)
        with self.engine.connect() as connection:
            transition_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(signal_transitions)
                .where(signal_transitions.c.decision_ticket_id == ticket.id)
            ).scalar_one()
            consumption_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(decision_ticket_consumptions)
                .where(decision_ticket_consumptions.c.decision_ticket_id == ticket.id)
            ).scalar_one()
        self.assertEqual(transition_count, 0)
        self.assertEqual(consumption_count, 0)

    def test_outbox_recovery_returns_failed_but_not_future_or_published(self) -> None:
        """Keep a failed unpublished event recoverable without early delivery."""

        now = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
        failed_id, future_id, published_id = uuid4(), uuid4(), uuid4()
        messages = (
            build_outbox_message(
                event_id=failed_id,
                event_type="loot.crypto.RecoveryProbe",
                producer="tests.integration",
                aggregate_type="RecoveryProbe",
                aggregate_id=uuid4(),
                correlation_id=uuid4(),
                causation_id=None,
                partition_key=str(failed_id),
                payload={"case": "failed"},
                occurred_at=now - timedelta(minutes=2),
            ),
            build_outbox_message(
                event_id=future_id,
                event_type="loot.crypto.RecoveryProbe",
                producer="tests.integration",
                aggregate_type="RecoveryProbe",
                aggregate_id=uuid4(),
                correlation_id=uuid4(),
                causation_id=None,
                partition_key=str(future_id),
                payload={"case": "future"},
                occurred_at=now,
                available_at=now + timedelta(hours=1),
            ),
            build_outbox_message(
                event_id=published_id,
                event_type="loot.crypto.RecoveryProbe",
                producer="tests.integration",
                aggregate_type="RecoveryProbe",
                aggregate_id=uuid4(),
                correlation_id=uuid4(),
                causation_id=None,
                partition_key=str(published_id),
                payload={"case": "published"},
                occurred_at=now - timedelta(minutes=1),
            ),
        )
        self.correlation_ids.update(
            message.event.correlation_id for message in messages
        )
        with self.engine.begin() as connection:
            for message in messages:
                insert_outbox_message(connection, message)
            connection.execute(
                sa.update(outbox_events)
                .where(outbox_events.c.event_id == failed_id)
                .values(attempt_count=2, last_error="temporary publish failure")
            )
            connection.execute(
                sa.update(outbox_events)
                .where(outbox_events.c.event_id == published_id)
                .values(published_at=now)
            )

        recovered_ids = {
            message.event.event_id
            for message in self.outbox_repository.list_unpublished(
                limit=100,
                available_at=now,
            )
        }
        self.assertIn(failed_id, recovered_ids)
        self.assertNotIn(future_id, recovered_ids)
        self.assertNotIn(published_id, recovered_ids)

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
        self.signal_ids.add(signal.id)

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
        self.proposal_ids.add(build_result.proposal.id)
        self.evidence_ids.add(build_result.evidence.id)
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
        self.evaluation_ids.add(policy_decision.evaluation.id)
        self.ticket_ids.add(ticket.id)

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
