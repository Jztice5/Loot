"""Create the Crypto decision persistence baseline.

Revision ID: 20260716_0001
Revises: None
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_STATEMENTS = (
    "CREATE SCHEMA IF NOT EXISTS loot",
    """
    CREATE TABLE loot.inbox_messages (
        consumer_name VARCHAR(120) NOT NULL,
        message_id UUID NOT NULL,
        payload_fingerprint VARCHAR(64) NOT NULL,
        received_at TIMESTAMPTZ NOT NULL,
        processed_at TIMESTAMPTZ NULL,
        status VARCHAR(20) NOT NULL,
        last_error TEXT NULL,
        CONSTRAINT pk_inbox_messages PRIMARY KEY (consumer_name, message_id),
        CONSTRAINT ck_inbox_messages_status_values
            CHECK (status IN ('RECEIVED', 'PROCESSED', 'FAILED')),
        CONSTRAINT ck_inbox_messages_payload_fingerprint_length
            CHECK (char_length(payload_fingerprint) = 64)
    )
    """,
    """
    CREATE TABLE loot.evidence_sets (
        id UUID PRIMARY KEY,
        candidate_event_id UUID NOT NULL,
        skill_run_id UUID NOT NULL,
        skill_id VARCHAR(160) NOT NULL,
        skill_version VARCHAR(80) NOT NULL,
        input_snapshot_id UUID NOT NULL,
        direction VARCHAR(16) NOT NULL,
        quality NUMERIC(8, 7) NOT NULL,
        observed_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        dedupe_key TEXT NOT NULL UNIQUE,
        payload_fingerprint VARCHAR(64) NOT NULL,
        payload JSONB NOT NULL,
        inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT ck_evidence_sets_direction_values
            CHECK (direction IN ('LONG', 'SHORT', 'NEUTRAL')),
        CONSTRAINT ck_evidence_sets_quality_range CHECK (quality >= 0 AND quality <= 1),
        CONSTRAINT ck_evidence_sets_expiry_after_observed CHECK (expires_at > observed_at),
        CONSTRAINT ck_evidence_sets_payload_fingerprint_length
            CHECK (char_length(payload_fingerprint) = 64)
    )
    """,
    "CREATE INDEX ix_evidence_sets_candidate_event_id ON loot.evidence_sets (candidate_event_id)",
    """
    CREATE TABLE loot.signal_instances (
        id UUID PRIMARY KEY,
        watch_item_id UUID NOT NULL,
        position_id UUID NULL,
        market VARCHAR(24) NOT NULL,
        instrument_id UUID NOT NULL,
        timeframe VARCHAR(8) NOT NULL,
        signal_type VARCHAR(40) NOT NULL,
        direction VARCHAR(16) NOT NULL,
        state VARCHAR(24) NOT NULL,
        priority VARCHAR(16) NOT NULL,
        actionability VARCHAR(40) NOT NULL,
        generation INTEGER NOT NULL,
        setup_key TEXT NOT NULL,
        latest_decision_ticket_id UUID NULL,
        dedupe_key TEXT NOT NULL UNIQUE,
        last_transition_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NULL,
        version INTEGER NOT NULL,
        payload JSONB NOT NULL,
        inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT ck_signal_instances_market_values
            CHECK (market IN ('CRYPTO', 'US_EQUITY', 'A_SHARE')),
        CONSTRAINT ck_signal_instances_direction_values
            CHECK (direction IN ('LONG', 'SHORT', 'NEUTRAL')),
        CONSTRAINT ck_signal_instances_state_values
            CHECK (state IN ('OBSERVING', 'ARMED', 'TRIGGERED', 'CONFIRMED',
                'WEAKENING', 'INVALIDATED', 'RESOLVED', 'EXPIRED')),
        CONSTRAINT ck_signal_instances_generation_positive CHECK (generation >= 1),
        CONSTRAINT ck_signal_instances_version_non_negative CHECK (version >= 0),
        CONSTRAINT ck_signal_instances_expiry_after_transition
            CHECK (expires_at IS NULL OR expires_at >= last_transition_at),
        CONSTRAINT uq_signal_instances_identity_generation UNIQUE
            (watch_item_id, market, instrument_id, timeframe, signal_type, direction, generation),
        CONSTRAINT uq_signal_instances_identity_setup UNIQUE
            (watch_item_id, market, instrument_id, timeframe, signal_type, direction, setup_key)
    )
    """,
    """
    CREATE UNIQUE INDEX uq_signal_instances_active_identity
    ON loot.signal_instances
        (watch_item_id, market, instrument_id, timeframe, signal_type, direction)
    WHERE state NOT IN ('INVALIDATED', 'RESOLVED', 'EXPIRED')
    """,
    """
    CREATE TABLE loot.decision_proposals (
        id UUID PRIMARY KEY,
        candidate_event_id UUID NOT NULL,
        market VARCHAR(24) NOT NULL,
        instrument_id UUID NOT NULL,
        timeframe VARCHAR(8) NOT NULL,
        signal_type VARCHAR(40) NOT NULL,
        direction VARCHAR(16) NOT NULL,
        signal_id UUID NOT NULL REFERENCES loot.signal_instances(id),
        suggested_transition VARCHAR(24) NOT NULL,
        rule_version VARCHAR(120) NOT NULL,
        input_snapshot_id UUID NOT NULL,
        expected_signal_version INTEGER NOT NULL,
        watch_item_version INTEGER NOT NULL,
        trading_plan_config_version INTEGER NULL,
        position_version INTEGER NULL,
        context_digest VARCHAR(64) NOT NULL,
        proposal_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        dedupe_key TEXT NOT NULL UNIQUE,
        payload_fingerprint VARCHAR(64) NOT NULL,
        payload JSONB NOT NULL,
        inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT ck_decision_proposals_market_values
            CHECK (market IN ('CRYPTO', 'US_EQUITY', 'A_SHARE')),
        CONSTRAINT ck_decision_proposals_direction_values
            CHECK (direction IN ('LONG', 'SHORT', 'NEUTRAL')),
        CONSTRAINT ck_decision_proposals_signal_version_non_negative
            CHECK (expected_signal_version >= 0),
        CONSTRAINT ck_decision_proposals_proposal_digest_length
            CHECK (char_length(proposal_digest) = 64),
        CONSTRAINT ck_decision_proposals_payload_fingerprint_length
            CHECK (char_length(payload_fingerprint) = 64)
    )
    """,
    """
    CREATE INDEX ix_decision_proposals_signal_id_created_at
    ON loot.decision_proposals (signal_id, created_at)
    """,
    """
    CREATE TABLE loot.decision_proposal_evidence (
        proposal_id UUID NOT NULL REFERENCES loot.decision_proposals(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        evidence_id UUID NOT NULL REFERENCES loot.evidence_sets(id),
        CONSTRAINT pk_decision_proposal_evidence PRIMARY KEY (proposal_id, position),
        CONSTRAINT ck_decision_proposal_evidence_position_non_negative CHECK (position >= 0),
        CONSTRAINT uq_decision_proposal_evidence_reference UNIQUE (proposal_id, evidence_id)
    )
    """,
    """
    CREATE TABLE loot.policy_evaluations (
        id UUID PRIMARY KEY,
        evaluation_request_id UUID NOT NULL UNIQUE,
        proposal_id UUID NOT NULL REFERENCES loot.decision_proposals(id),
        outcome VARCHAR(16) NOT NULL,
        policy_version VARCHAR(120) NOT NULL,
        proposal_digest VARCHAR(64) NOT NULL,
        evaluation_context_digest VARCHAR(64) NOT NULL,
        attempt_number INTEGER NOT NULL,
        evaluated_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        next_check_at TIMESTAMPTZ NULL,
        dedupe_key TEXT NOT NULL UNIQUE,
        payload_fingerprint VARCHAR(64) NOT NULL,
        payload JSONB NOT NULL,
        inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT ck_policy_evaluations_outcome_values
            CHECK (outcome IN ('APPROVED', 'REJECTED', 'DEFERRED')),
        CONSTRAINT ck_policy_evaluations_attempt_positive CHECK (attempt_number >= 1),
        CONSTRAINT ck_policy_evaluations_expiry_after_evaluation
            CHECK (expires_at > evaluated_at),
        CONSTRAINT ck_policy_evaluations_proposal_digest_length
            CHECK (char_length(proposal_digest) = 64),
        CONSTRAINT ck_policy_evaluations_payload_fingerprint_length
            CHECK (char_length(payload_fingerprint) = 64),
        CONSTRAINT uq_policy_evaluations_identity UNIQUE
            (proposal_id, policy_version, evaluation_context_digest)
    )
    """,
    """
    CREATE INDEX ix_policy_evaluations_proposal_id_evaluated_at
    ON loot.policy_evaluations (proposal_id, evaluated_at)
    """,
    """
    CREATE TABLE loot.decision_tickets (
        id UUID PRIMARY KEY,
        proposal_id UUID NOT NULL UNIQUE REFERENCES loot.decision_proposals(id),
        policy_evaluation_id UUID NOT NULL UNIQUE REFERENCES loot.policy_evaluations(id),
        policy_version VARCHAR(120) NOT NULL,
        proposal_digest VARCHAR(64) NOT NULL,
        market VARCHAR(24) NOT NULL,
        instrument_id UUID NOT NULL,
        timeframe VARCHAR(8) NOT NULL,
        direction VARCHAR(16) NOT NULL,
        signal_id UUID NOT NULL REFERENCES loot.signal_instances(id),
        authorized_transition VARCHAR(24) NOT NULL,
        input_snapshot_id UUID NOT NULL,
        expected_signal_version INTEGER NOT NULL,
        watch_item_version INTEGER NOT NULL,
        trading_plan_config_version INTEGER NULL,
        position_version INTEGER NULL,
        context_digest VARCHAR(64) NOT NULL,
        issued_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        dedupe_key TEXT NOT NULL UNIQUE,
        payload_fingerprint VARCHAR(64) NOT NULL,
        payload JSONB NOT NULL,
        inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT ck_decision_tickets_market_values
            CHECK (market IN ('CRYPTO', 'US_EQUITY', 'A_SHARE')),
        CONSTRAINT ck_decision_tickets_direction_values
            CHECK (direction IN ('LONG', 'SHORT', 'NEUTRAL')),
        CONSTRAINT ck_decision_tickets_expiry_after_issue CHECK (expires_at > issued_at),
        CONSTRAINT ck_decision_tickets_proposal_digest_length
            CHECK (char_length(proposal_digest) = 64),
        CONSTRAINT ck_decision_tickets_payload_fingerprint_length
            CHECK (char_length(payload_fingerprint) = 64)
    )
    """,
    """
    CREATE INDEX ix_decision_tickets_signal_id_issued_at
    ON loot.decision_tickets (signal_id, issued_at)
    """,
    """
    ALTER TABLE loot.signal_instances
    ADD CONSTRAINT fk_signal_instances_latest_decision_ticket_id_decision_tickets
    FOREIGN KEY (latest_decision_ticket_id) REFERENCES loot.decision_tickets(id)
    """,
    """
    CREATE TABLE loot.signal_transitions (
        id UUID PRIMARY KEY,
        signal_id UUID NOT NULL REFERENCES loot.signal_instances(id),
        decision_ticket_id UUID NOT NULL REFERENCES loot.decision_tickets(id),
        event_id UUID NOT NULL UNIQUE,
        from_state VARCHAR(24) NOT NULL,
        to_state VARCHAR(24) NOT NULL,
        from_version INTEGER NOT NULL,
        to_version INTEGER NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL,
        payload JSONB NOT NULL,
        inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT ck_signal_transitions_state_changes CHECK (from_state <> to_state),
        CONSTRAINT ck_signal_transitions_version_increments
            CHECK (to_version = from_version + 1),
        CONSTRAINT uq_signal_transitions_signal_ticket UNIQUE (signal_id, decision_ticket_id)
    )
    """,
    """
    CREATE INDEX ix_signal_transitions_signal_id_occurred_at
    ON loot.signal_transitions (signal_id, occurred_at)
    """,
    """
    CREATE TABLE loot.decision_ticket_consumptions (
        decision_ticket_id UUID PRIMARY KEY REFERENCES loot.decision_tickets(id),
        signal_id UUID NOT NULL REFERENCES loot.signal_instances(id),
        transition_id UUID NULL REFERENCES loot.signal_transitions(id),
        ticket_fingerprint VARCHAR(64) NOT NULL,
        consumed_at TIMESTAMPTZ NOT NULL,
        result_payload JSONB NOT NULL,
        CONSTRAINT ck_decision_ticket_consumptions_ticket_fingerprint_length
            CHECK (char_length(ticket_fingerprint) = 64)
    )
    """,
    """
    CREATE TABLE loot.outbox_events (
        event_id UUID PRIMARY KEY,
        event_type VARCHAR(160) NOT NULL,
        event_version INTEGER NOT NULL,
        aggregate_type VARCHAR(80) NOT NULL,
        aggregate_id UUID NOT NULL,
        correlation_id UUID NOT NULL,
        causation_id UUID NULL,
        partition_key VARCHAR(240) NOT NULL,
        payload JSONB NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL,
        available_at TIMESTAMPTZ NOT NULL,
        published_at TIMESTAMPTZ NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        locked_at TIMESTAMPTZ NULL,
        last_error TEXT NULL,
        CONSTRAINT ck_outbox_events_event_version_positive CHECK (event_version >= 1),
        CONSTRAINT ck_outbox_events_attempt_non_negative CHECK (attempt_count >= 0)
    )
    """,
    """
    CREATE INDEX ix_outbox_events_unpublished_available
    ON loot.outbox_events (available_at, occurred_at)
    WHERE published_at IS NULL
    """,
)

_DOWNGRADE_STATEMENTS = (
    "DROP TABLE IF EXISTS loot.outbox_events",
    "DROP TABLE IF EXISTS loot.decision_ticket_consumptions",
    "DROP TABLE IF EXISTS loot.signal_transitions",
    "ALTER TABLE IF EXISTS loot.signal_instances DROP CONSTRAINT IF EXISTS fk_signal_instances_latest_decision_ticket_id_decision_tickets",
    "DROP TABLE IF EXISTS loot.decision_tickets",
    "DROP TABLE IF EXISTS loot.policy_evaluations",
    "DROP TABLE IF EXISTS loot.decision_proposal_evidence",
    "DROP TABLE IF EXISTS loot.decision_proposals",
    "DROP TABLE IF EXISTS loot.signal_instances",
    "DROP TABLE IF EXISTS loot.evidence_sets",
    "DROP TABLE IF EXISTS loot.inbox_messages",
)


def upgrade() -> None:
    """Create the initial durable authorization and Signal facts."""

    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Drop REQ-0008 tables while retaining the pre-created schema and roles."""

    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
