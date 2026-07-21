"""Crypto Run-Once integration test against the configured loot_test database."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from loot.application import (
    CryptoRunMode,
    CryptoRunOnceCommand,
    CryptoRunOnceService,
    CryptoRunStatus,
    DemoBreakoutCryptoProvider,
    default_btc_usdt_instrument,
)
from loot.contracts import SignalState
from loot.domains.crypto import CryptoPolicyGate
from loot.persistence import (
    PostgresAnalysisRepository,
    PostgresAuthorizationRepository,
    PostgresSignalWorkflow,
    create_postgres_engine,
)
from loot.persistence.config import load_local_setting
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

_DATABASE_URL = load_local_setting("LOOT_TEST_DATABASE_URL")
_CONSUMER_NAME = "loot.application.crypto_run_once.v1"


@unittest.skipUnless(
    _DATABASE_URL,
    "LOOT_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
class CryptoRunOnceIntegrationTest(unittest.TestCase):
    """Verify one full Run-Once chain across all existing persistence tables."""

    @classmethod
    def setUpClass(cls) -> None:
        """Connect only to an explicitly configured loot_test database."""

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
                "loot_test connection failed; verify local loot_app credentials"
            ) from None
        if database_name != "loot_test":
            cls.engine.dispose()
            raise RuntimeError("Run-Once integration tests must connect to loot_test")

    @classmethod
    def tearDownClass(cls) -> None:
        """Dispose PostgreSQL connections after integration verification."""

        cls.engine.dispose()

    def setUp(self) -> None:
        """Allocate unique identities and empty cleanup tracking."""

        self.watch_item_id = uuid4()
        self.created_ids: set[UUID] = set()
        self.candidate_id: UUID | None = None

    def tearDown(self) -> None:
        """Delete only facts created by this test in foreign-key-safe order."""

        with self.engine.begin() as connection:
            if self.created_ids:
                connection.execute(
                    sa.update(signal_instances)
                    .where(signal_instances.c.id.in_(self.created_ids))
                    .values(latest_decision_ticket_id=None)
                )
                connection.execute(
                    sa.delete(outbox_events).where(
                        outbox_events.c.aggregate_id.in_(self.created_ids)
                    )
                )
                connection.execute(
                    sa.delete(decision_ticket_consumptions).where(
                        decision_ticket_consumptions.c.decision_ticket_id.in_(
                            self.created_ids
                        )
                    )
                )
                connection.execute(
                    sa.delete(signal_transitions).where(
                        signal_transitions.c.decision_ticket_id.in_(self.created_ids)
                    )
                )
                connection.execute(
                    sa.delete(decision_tickets).where(
                        decision_tickets.c.id.in_(self.created_ids)
                    )
                )
                connection.execute(
                    sa.delete(policy_evaluations).where(
                        policy_evaluations.c.id.in_(self.created_ids)
                    )
                )
                connection.execute(
                    sa.delete(decision_proposal_evidence).where(
                        decision_proposal_evidence.c.proposal_id.in_(self.created_ids)
                    )
                )
                connection.execute(
                    sa.delete(decision_proposals).where(
                        decision_proposals.c.id.in_(self.created_ids)
                    )
                )
                connection.execute(
                    sa.delete(evidence_sets).where(
                        evidence_sets.c.id.in_(self.created_ids)
                    )
                )
                connection.execute(
                    sa.delete(signal_instances).where(
                        signal_instances.c.id.in_(self.created_ids)
                    )
                )
            if self.candidate_id is not None:
                connection.execute(
                    sa.delete(inbox_messages).where(
                        inbox_messages.c.consumer_name == _CONSUMER_NAME,
                        inbox_messages.c.message_id == self.candidate_id,
                    )
                )

    def test_demo_persists_complete_decision_chain(self) -> None:
        """Write and query one fact in every existing decision-chain table."""

        now = datetime.now(UTC)
        authorization_repository = PostgresAuthorizationRepository(self.engine)
        service = CryptoRunOnceService(
            provider=DemoBreakoutCryptoProvider(received_at=now),
            signal_workflow=PostgresSignalWorkflow(self.engine),
            analysis_repository=PostgresAnalysisRepository(self.engine),
            policy_gate=CryptoPolicyGate(authorization_repository),
        )

        result = service.run(
            CryptoRunOnceCommand(
                mode=CryptoRunMode.DEMO,
                instrument=default_btc_usdt_instrument(),
                watch_item_id=self.watch_item_id,
                context_digest="integration-run-once-context-v1",
            )
        )
        self.candidate_id = result.candidate_id
        self.created_ids.update(
            identifier
            for identifier in (
                result.signal_id,
                result.proposal_id,
                result.policy_evaluation_id,
                result.decision_ticket_id,
            )
            if identifier is not None
        )

        self.assertEqual(result.status, CryptoRunStatus.SIGNAL_TRANSITIONED)
        self.assertEqual(result.signal_state, SignalState.ARMED)
        assert result.candidate_id is not None
        assert result.signal_id is not None
        assert result.proposal_id is not None
        assert result.policy_evaluation_id is not None
        assert result.decision_ticket_id is not None

        with self.engine.connect() as connection:
            evidence_id = connection.execute(
                sa.select(evidence_sets.c.id).where(
                    evidence_sets.c.candidate_event_id == result.candidate_id
                )
            ).scalar_one()
            self.created_ids.add(evidence_id)
            checks = (
                sa.select(sa.func.count()).select_from(inbox_messages).where(
                    inbox_messages.c.consumer_name == _CONSUMER_NAME,
                    inbox_messages.c.message_id == result.candidate_id,
                ),
                sa.select(sa.func.count()).select_from(evidence_sets).where(
                    evidence_sets.c.id == evidence_id
                ),
                sa.select(sa.func.count()).select_from(signal_instances).where(
                    signal_instances.c.id == result.signal_id,
                    signal_instances.c.state == SignalState.ARMED.value,
                ),
                sa.select(sa.func.count()).select_from(decision_proposals).where(
                    decision_proposals.c.id == result.proposal_id
                ),
                sa.select(sa.func.count())
                .select_from(decision_proposal_evidence)
                .where(
                    decision_proposal_evidence.c.proposal_id == result.proposal_id,
                    decision_proposal_evidence.c.evidence_id == evidence_id,
                ),
                sa.select(sa.func.count()).select_from(policy_evaluations).where(
                    policy_evaluations.c.id == result.policy_evaluation_id
                ),
                sa.select(sa.func.count()).select_from(decision_tickets).where(
                    decision_tickets.c.id == result.decision_ticket_id
                ),
                sa.select(sa.func.count()).select_from(signal_transitions).where(
                    signal_transitions.c.decision_ticket_id
                    == result.decision_ticket_id
                ),
                sa.select(sa.func.count())
                .select_from(decision_ticket_consumptions)
                .where(
                    decision_ticket_consumptions.c.decision_ticket_id
                    == result.decision_ticket_id
                ),
                sa.select(sa.func.count()).select_from(outbox_events).where(
                    outbox_events.c.aggregate_id.in_(self.created_ids)
                ),
            )
            counts = tuple(
                int(connection.execute(query).scalar_one()) for query in checks
            )

        self.assertEqual(counts[:9], (1,) * 9)
        self.assertGreaterEqual(counts[9], 5)


if __name__ == "__main__":
    unittest.main()
