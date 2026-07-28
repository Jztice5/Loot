"""Loot PostgreSQL Core table metadata.

业务描述:
    定义 Crypto First 决策授权链的可索引数据库事实、幂等账本和 Outbox。

业务原因:
    contracts 仍是跨模块业务模型；本模块只负责关系约束、查询列和事务持久化结构，不能
    让 ORM 对象替代 Pydantic 契约。

调用链:
    Repository/Integration Test -> SQLAlchemy Table metadata -> PostgreSQL schema ``loot``
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

SCHEMA_NAME = "loot"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = sa.MetaData(schema=SCHEMA_NAME, naming_convention=NAMING_CONVENTION)

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
UTC_TIMESTAMP = sa.DateTime(timezone=True)
FINGERPRINT = sa.String(64)

MARKET_CHECK = "market IN ('CRYPTO', 'US_EQUITY', 'A_SHARE')"
DIRECTION_CHECK = "direction IN ('LONG', 'SHORT', 'NEUTRAL')"
SIGNAL_STATE_CHECK = (
    "state IN ('OBSERVING', 'ARMED', 'TRIGGERED', 'CONFIRMED', "
    "'WEAKENING', 'INVALIDATED', 'RESOLVED', 'EXPIRED')"
)

INSTRUMENT_STATUS_CHECK = "status IN ('ACTIVE', 'PAUSED', 'DELISTED')"
WATCH_ITEM_STATUS_CHECK = "status IN ('ACTIVE', 'PAUSED', 'ARCHIVED')"
SUBSCRIPTION_STATUS_CHECK = (
    "status IN ('ACTIVE', 'PAUSED', 'ARCHIVED', 'ERROR', 'DEGRADED')"
)

instruments = sa.Table(
    "instruments",
    metadata,
    sa.Column("instrument_id", UUID, primary_key=True),
    sa.Column("market", sa.String(24), nullable=False),
    sa.Column("venue", sa.String(80), nullable=False),
    sa.Column("symbol", sa.String(80), nullable=False),
    sa.Column("instrument_type", sa.String(24), nullable=False),
    sa.Column("quote_currency", sa.String(24), nullable=False),
    sa.Column("timezone", sa.String(80), nullable=False),
    sa.Column("price_scale", sa.Integer(), nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("payload_fingerprint", FINGERPRINT, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("inserted_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(MARKET_CHECK, name="market_values"),
    sa.CheckConstraint(INSTRUMENT_STATUS_CHECK, name="status_values"),
    sa.CheckConstraint("price_scale >= 0", name="price_scale_non_negative"),
    sa.CheckConstraint(
        "char_length(payload_fingerprint) = 64",
        name="payload_fingerprint_length",
    ),
    sa.UniqueConstraint(
        "market",
        "venue",
        "symbol",
        "instrument_type",
        name="uq_instruments_natural_identity",
    ),
)

watch_items = sa.Table(
    "watch_items",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("user_id", UUID, nullable=False),
    sa.Column(
        "instrument_id",
        UUID,
        sa.ForeignKey("loot.instruments.instrument_id"),
        nullable=False,
    ),
    sa.Column("market", sa.String(24), nullable=False),
    sa.Column("venue", sa.String(80), nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("monitoring_profile", sa.String(120), nullable=False),
    sa.Column("priority", sa.String(16), nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("version", sa.Integer(), nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("inserted_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(MARKET_CHECK, name="market_values"),
    sa.CheckConstraint(WATCH_ITEM_STATUS_CHECK, name="status_values"),
    sa.CheckConstraint("version >= 0", name="version_non_negative"),
    sa.CheckConstraint("updated_at >= created_at", name="updated_after_created"),
)

sa.Index(
    "uq_watch_items_active_identity",
    watch_items.c.user_id,
    watch_items.c.instrument_id,
    watch_items.c.monitoring_profile,
    unique=True,
    postgresql_where=watch_items.c.status == "ACTIVE",
)

sa.Index(
    "ix_watch_items_instrument_id",
    watch_items.c.instrument_id,
)

monitoring_subscriptions = sa.Table(
    "monitoring_subscriptions",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column(
        "watch_item_id",
        UUID,
        sa.ForeignKey("loot.watch_items.id"),
        nullable=False,
    ),
    sa.Column("market", sa.String(24), nullable=False),
    sa.Column(
        "instrument_id",
        UUID,
        sa.ForeignKey("loot.instruments.instrument_id"),
        nullable=False,
    ),
    sa.Column("timeframe", sa.String(8), nullable=False),
    sa.Column("route_key", sa.String(240), nullable=False),
    sa.Column("next_run_at", UTC_TIMESTAMP),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("config_version", sa.Integer(), nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("inserted_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(MARKET_CHECK, name="market_values"),
    sa.CheckConstraint(SUBSCRIPTION_STATUS_CHECK, name="status_values"),
    sa.CheckConstraint("config_version >= 1", name="config_version_positive"),
    sa.CheckConstraint("updated_at >= created_at", name="updated_after_created"),
    sa.UniqueConstraint(
        "watch_item_id",
        "timeframe",
        name="uq_monitoring_subscriptions_watch_timeframe",
    ),
)

sa.Index(
    "ix_monitoring_subscriptions_active_schedule",
    monitoring_subscriptions.c.status,
    monitoring_subscriptions.c.next_run_at,
)

monitoring_runs = sa.Table(
    "monitoring_runs",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("run_key", sa.Text(), nullable=False, unique=True),
    sa.Column(
        "subscription_id",
        UUID,
        sa.ForeignKey("loot.monitoring_subscriptions.id"),
        nullable=False,
    ),
    sa.Column("watch_item_id", UUID, sa.ForeignKey("loot.watch_items.id"), nullable=False),
    sa.Column("instrument_id", UUID, sa.ForeignKey("loot.instruments.instrument_id"), nullable=False),
    sa.Column("market", sa.String(24), nullable=False),
    sa.Column("timeframe", sa.String(8), nullable=False),
    sa.Column("target_bar_closed_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("workflow_version", sa.String(120), nullable=False),
    sa.Column("execution_context_digest", FINGERPRINT, nullable=False),
    sa.Column("watch_item_version", sa.Integer(), nullable=False),
    sa.Column("subscription_config_version", sa.Integer(), nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("phase", sa.String(32), nullable=False),
    sa.Column("outcome", sa.String(32)),
    sa.Column("attempt_count", sa.Integer(), nullable=False),
    sa.Column("max_attempts", sa.Integer(), nullable=False),
    sa.Column("next_attempt_at", UTC_TIMESTAMP),
    sa.Column("lease_token", UUID),
    sa.Column("lease_owner", sa.String(160)),
    sa.Column("lease_expires_at", UTC_TIMESTAMP),
    sa.Column("input_snapshot_id", UUID),
    sa.Column("snapshot_content_hash", FINGERPRINT),
    sa.Column("source_provider", sa.String(120)),
    sa.Column("decision_evaluated_at", UTC_TIMESTAMP),
    sa.Column("candidate_id", UUID),
    sa.Column("proposal_id", UUID),
    sa.Column("policy_evaluation_id", UUID),
    sa.Column("decision_ticket_id", UUID),
    sa.Column("signal_id", UUID),
    sa.Column("last_error_code", sa.String(120)),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("completed_at", UTC_TIMESTAMP),
    sa.Column("version", sa.Integer(), nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("inserted_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint("market = 'CRYPTO'", name="crypto_market_only"),
    sa.CheckConstraint("timeframe = '1h'", name="h1_timeframe_only"),
    sa.CheckConstraint(
        "target_bar_closed_at = date_trunc('hour', target_bar_closed_at)",
        name="target_exact_h1_boundary",
    ),
    sa.CheckConstraint(
        "status IN ('PENDING', 'RUNNING', 'RETRY_WAIT', 'COMPLETED', 'FAILED', 'CANCELED')",
        name="status_values",
    ),
    sa.CheckConstraint(
        "phase IN ('MATERIALIZED', 'INPUT_BOUND', 'PREFILTERED', 'SIGNAL_INITIALIZED', "
        "'ANALYSIS_PERSISTED', 'POLICY_EVALUATED', 'SIGNAL_APPLIED', 'FINISHED')",
        name="phase_values",
    ),
    sa.CheckConstraint(
        "outcome IS NULL OR outcome IN ('NO_CANDIDATE', 'CANDIDATE_EXPIRED', "
        "'POLICY_NOT_APPROVED', 'SIGNAL_TRANSITIONED')",
        name="outcome_values",
    ),
    sa.CheckConstraint("attempt_count >= 0 AND max_attempts >= 1", name="attempt_budget"),
    sa.CheckConstraint("attempt_count <= max_attempts", name="attempt_within_budget"),
    sa.CheckConstraint("watch_item_version >= 0", name="watch_version_non_negative"),
    sa.CheckConstraint("subscription_config_version >= 1", name="subscription_version_positive"),
    sa.CheckConstraint("version >= 0", name="version_non_negative"),
    sa.CheckConstraint("updated_at >= created_at", name="updated_after_created"),
    sa.CheckConstraint(
        "char_length(execution_context_digest) = 64",
        name="context_digest_length",
    ),
    sa.CheckConstraint(
        "snapshot_content_hash IS NULL OR char_length(snapshot_content_hash) = 64",
        name="snapshot_hash_length",
    ),
    sa.CheckConstraint(
        "(status = 'RUNNING' AND lease_token IS NOT NULL AND lease_owner IS NOT NULL "
        "AND lease_expires_at IS NOT NULL) OR (status <> 'RUNNING' AND lease_token IS NULL "
        "AND lease_owner IS NULL AND lease_expires_at IS NULL)",
        name="lease_matches_running",
    ),
    sa.CheckConstraint(
        "(status = 'RETRY_WAIT') = (next_attempt_at IS NOT NULL)",
        name="retry_has_next_attempt",
    ),
    sa.CheckConstraint(
        "(status = 'COMPLETED') = (outcome IS NOT NULL)",
        name="completed_has_outcome",
    ),
    sa.CheckConstraint(
        "status <> 'COMPLETED' OR phase = 'FINISHED'",
        name="completed_is_finished",
    ),
    sa.CheckConstraint(
        "(status IN ('COMPLETED', 'FAILED', 'CANCELED')) = (completed_at IS NOT NULL)",
        name="terminal_has_completed_at",
    ),
    sa.CheckConstraint(
        "(input_snapshot_id IS NULL AND snapshot_content_hash IS NULL AND source_provider IS NULL) "
        "OR (input_snapshot_id IS NOT NULL AND snapshot_content_hash IS NOT NULL "
        "AND source_provider IS NOT NULL)",
        name="snapshot_binding_complete",
    ),
    sa.CheckConstraint(
        "phase = 'MATERIALIZED' OR input_snapshot_id IS NOT NULL",
        name="advanced_phase_has_snapshot",
    ),
    sa.CheckConstraint(
        "(input_snapshot_id IS NULL) = (decision_evaluated_at IS NULL)",
        name="snapshot_has_evaluation_time",
    ),
    sa.CheckConstraint(
        "phase <> 'FINISHED' OR status = 'COMPLETED'",
        name="finished_phase_is_completed",
    ),
    sa.UniqueConstraint(
        "subscription_id",
        "target_bar_closed_at",
        "workflow_version",
        name="uq_monitoring_runs_subscription_target_workflow",
    ),
)

sa.Index(
    "ix_monitoring_runs_due",
    monitoring_runs.c.status,
    monitoring_runs.c.next_attempt_at,
    monitoring_runs.c.target_bar_closed_at,
)

sa.Index(
    "ix_monitoring_runs_expired_lease",
    monitoring_runs.c.lease_expires_at,
    postgresql_where=monitoring_runs.c.status == "RUNNING",
)

monitoring_run_attempts = sa.Table(
    "monitoring_run_attempts",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column(
        "run_id",
        UUID,
        sa.ForeignKey("loot.monitoring_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("attempt_number", sa.Integer(), nullable=False),
    sa.Column("lease_token", UUID, nullable=False),
    sa.Column("worker_id", sa.String(160), nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("started_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("finished_at", UTC_TIMESTAMP),
    sa.Column("error_code", sa.String(120)),
    sa.Column("retryable", sa.Boolean()),
    sa.Column("next_attempt_at", UTC_TIMESTAMP),
    sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
    sa.CheckConstraint(
        "status IN ('STARTED', 'COMPLETED', 'FAILED', 'ABANDONED')",
        name="status_values",
    ),
    sa.CheckConstraint(
        "(status = 'STARTED') = (finished_at IS NULL)",
        name="started_has_no_finish",
    ),
    sa.CheckConstraint(
        "(status = 'FAILED') = (error_code IS NOT NULL AND retryable IS NOT NULL)",
        name="failure_metadata",
    ),
    sa.CheckConstraint(
        "next_attempt_at IS NULL OR (status = 'FAILED' AND retryable IS TRUE)",
        name="retry_schedule_matches_failure",
    ),
    sa.UniqueConstraint("run_id", "attempt_number", name="uq_monitoring_run_attempts_number"),
    sa.UniqueConstraint("run_id", "lease_token", name="uq_monitoring_run_attempts_lease"),
)

sa.Index(
    "ix_monitoring_run_attempts_run_started",
    monitoring_run_attempts.c.run_id,
    monitoring_run_attempts.c.started_at,
)

inbox_messages = sa.Table(
    "inbox_messages",
    metadata,
    sa.Column("consumer_name", sa.String(120), primary_key=True),
    sa.Column("message_id", UUID, primary_key=True),
    sa.Column("payload_fingerprint", FINGERPRINT, nullable=False),
    sa.Column("received_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("processed_at", UTC_TIMESTAMP),
    sa.Column("status", sa.String(20), nullable=False),
    sa.Column("last_error", sa.Text()),
    sa.CheckConstraint(
        "status IN ('RECEIVED', 'PROCESSED', 'FAILED')",
        name="status_values",
    ),
    sa.CheckConstraint(
        "char_length(payload_fingerprint) = 64",
        name="payload_fingerprint_length",
    ),
)

evidence_sets = sa.Table(
    "evidence_sets",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("candidate_event_id", UUID, nullable=False),
    sa.Column("skill_run_id", UUID, nullable=False),
    sa.Column("skill_id", sa.String(160), nullable=False),
    sa.Column("skill_version", sa.String(80), nullable=False),
    sa.Column("input_snapshot_id", UUID, nullable=False),
    sa.Column("direction", sa.String(16), nullable=False),
    sa.Column("quality", sa.Numeric(8, 7), nullable=False),
    sa.Column("observed_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("expires_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("dedupe_key", sa.Text(), nullable=False, unique=True),
    sa.Column("payload_fingerprint", FINGERPRINT, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("inserted_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(DIRECTION_CHECK, name="direction_values"),
    sa.CheckConstraint("quality >= 0 AND quality <= 1", name="quality_range"),
    sa.CheckConstraint("expires_at > observed_at", name="expiry_after_observed"),
    sa.CheckConstraint(
        "char_length(payload_fingerprint) = 64",
        name="payload_fingerprint_length",
    ),
)

sa.Index(
    "ix_evidence_sets_candidate_event_id",
    evidence_sets.c.candidate_event_id,
)

signal_instances = sa.Table(
    "signal_instances",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("watch_item_id", UUID, nullable=False),
    sa.Column("position_id", UUID),
    sa.Column("market", sa.String(24), nullable=False),
    sa.Column("instrument_id", UUID, nullable=False),
    sa.Column("timeframe", sa.String(8), nullable=False),
    sa.Column("signal_type", sa.String(40), nullable=False),
    sa.Column("direction", sa.String(16), nullable=False),
    sa.Column("state", sa.String(24), nullable=False),
    sa.Column("priority", sa.String(16), nullable=False),
    sa.Column("actionability", sa.String(40), nullable=False),
    sa.Column("generation", sa.Integer(), nullable=False),
    sa.Column("setup_key", sa.Text(), nullable=False),
    sa.Column("latest_decision_ticket_id", UUID),
    sa.Column("dedupe_key", sa.Text(), nullable=False, unique=True),
    sa.Column("last_transition_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("expires_at", UTC_TIMESTAMP),
    sa.Column("version", sa.Integer(), nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("inserted_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(MARKET_CHECK, name="market_values"),
    sa.CheckConstraint(DIRECTION_CHECK, name="direction_values"),
    sa.CheckConstraint(SIGNAL_STATE_CHECK, name="state_values"),
    sa.CheckConstraint("generation >= 1", name="generation_positive"),
    sa.CheckConstraint("version >= 0", name="version_non_negative"),
    sa.CheckConstraint(
        "expires_at IS NULL OR expires_at >= last_transition_at",
        name="expiry_after_transition",
    ),
    sa.UniqueConstraint(
        "watch_item_id",
        "market",
        "instrument_id",
        "timeframe",
        "signal_type",
        "direction",
        "generation",
        name="uq_signal_instances_identity_generation",
    ),
    sa.UniqueConstraint(
        "watch_item_id",
        "market",
        "instrument_id",
        "timeframe",
        "signal_type",
        "direction",
        "setup_key",
        name="uq_signal_instances_identity_setup",
    ),
)

sa.Index(
    "uq_signal_instances_active_identity",
    signal_instances.c.watch_item_id,
    signal_instances.c.market,
    signal_instances.c.instrument_id,
    signal_instances.c.timeframe,
    signal_instances.c.signal_type,
    signal_instances.c.direction,
    unique=True,
    postgresql_where=signal_instances.c.state.not_in(
        ("INVALIDATED", "RESOLVED", "EXPIRED")
    ),
)

decision_proposals = sa.Table(
    "decision_proposals",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("candidate_event_id", UUID, nullable=False),
    sa.Column("market", sa.String(24), nullable=False),
    sa.Column("instrument_id", UUID, nullable=False),
    sa.Column("timeframe", sa.String(8), nullable=False),
    sa.Column("signal_type", sa.String(40), nullable=False),
    sa.Column("direction", sa.String(16), nullable=False),
    sa.Column("signal_id", UUID, sa.ForeignKey("loot.signal_instances.id"), nullable=False),
    sa.Column("suggested_transition", sa.String(24), nullable=False),
    sa.Column("rule_version", sa.String(120), nullable=False),
    sa.Column("input_snapshot_id", UUID, nullable=False),
    sa.Column("expected_signal_version", sa.Integer(), nullable=False),
    sa.Column("watch_item_version", sa.Integer(), nullable=False),
    sa.Column("trading_plan_config_version", sa.Integer()),
    sa.Column("position_version", sa.Integer()),
    sa.Column("context_digest", FINGERPRINT, nullable=False),
    sa.Column("proposal_digest", FINGERPRINT, nullable=False),
    sa.Column("created_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("dedupe_key", sa.Text(), nullable=False, unique=True),
    sa.Column("payload_fingerprint", FINGERPRINT, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("inserted_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(MARKET_CHECK, name="market_values"),
    sa.CheckConstraint(DIRECTION_CHECK, name="direction_values"),
    sa.CheckConstraint("expected_signal_version >= 0", name="signal_version_non_negative"),
    sa.CheckConstraint(
        "char_length(proposal_digest) = 64",
        name="proposal_digest_length",
    ),
    sa.CheckConstraint(
        "char_length(payload_fingerprint) = 64",
        name="payload_fingerprint_length",
    ),
)

sa.Index(
    "ix_decision_proposals_signal_id_created_at",
    decision_proposals.c.signal_id,
    decision_proposals.c.created_at,
)

decision_proposal_evidence = sa.Table(
    "decision_proposal_evidence",
    metadata,
    sa.Column(
        "proposal_id",
        UUID,
        sa.ForeignKey("loot.decision_proposals.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("position", sa.Integer(), primary_key=True),
    sa.Column(
        "evidence_id",
        UUID,
        sa.ForeignKey("loot.evidence_sets.id"),
        nullable=False,
    ),
    sa.CheckConstraint("position >= 0", name="position_non_negative"),
    sa.UniqueConstraint(
        "proposal_id",
        "evidence_id",
        name="uq_decision_proposal_evidence_reference",
    ),
)

policy_evaluations = sa.Table(
    "policy_evaluations",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("evaluation_request_id", UUID, nullable=False, unique=True),
    sa.Column(
        "proposal_id",
        UUID,
        sa.ForeignKey("loot.decision_proposals.id"),
        nullable=False,
    ),
    sa.Column("outcome", sa.String(16), nullable=False),
    sa.Column("policy_version", sa.String(120), nullable=False),
    sa.Column("proposal_digest", FINGERPRINT, nullable=False),
    sa.Column("evaluation_context_digest", FINGERPRINT, nullable=False),
    sa.Column("attempt_number", sa.Integer(), nullable=False),
    sa.Column("evaluated_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("expires_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("next_check_at", UTC_TIMESTAMP),
    sa.Column("dedupe_key", sa.Text(), nullable=False, unique=True),
    sa.Column("payload_fingerprint", FINGERPRINT, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("inserted_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(
        "outcome IN ('APPROVED', 'REJECTED', 'DEFERRED')",
        name="outcome_values",
    ),
    sa.CheckConstraint("attempt_number >= 1", name="attempt_positive"),
    sa.CheckConstraint("expires_at > evaluated_at", name="expiry_after_evaluation"),
    sa.CheckConstraint(
        "char_length(proposal_digest) = 64",
        name="proposal_digest_length",
    ),
    sa.CheckConstraint(
        "char_length(payload_fingerprint) = 64",
        name="payload_fingerprint_length",
    ),
    sa.UniqueConstraint(
        "proposal_id",
        "policy_version",
        "evaluation_context_digest",
        name="uq_policy_evaluations_identity",
    ),
)

sa.Index(
    "ix_policy_evaluations_proposal_id_evaluated_at",
    policy_evaluations.c.proposal_id,
    policy_evaluations.c.evaluated_at,
)

decision_tickets = sa.Table(
    "decision_tickets",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column(
        "proposal_id",
        UUID,
        sa.ForeignKey("loot.decision_proposals.id"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "policy_evaluation_id",
        UUID,
        sa.ForeignKey("loot.policy_evaluations.id"),
        nullable=False,
        unique=True,
    ),
    sa.Column("policy_version", sa.String(120), nullable=False),
    sa.Column("proposal_digest", FINGERPRINT, nullable=False),
    sa.Column("market", sa.String(24), nullable=False),
    sa.Column("instrument_id", UUID, nullable=False),
    sa.Column("timeframe", sa.String(8), nullable=False),
    sa.Column("direction", sa.String(16), nullable=False),
    sa.Column("signal_id", UUID, sa.ForeignKey("loot.signal_instances.id"), nullable=False),
    sa.Column("authorized_transition", sa.String(24), nullable=False),
    sa.Column("input_snapshot_id", UUID, nullable=False),
    sa.Column("expected_signal_version", sa.Integer(), nullable=False),
    sa.Column("watch_item_version", sa.Integer(), nullable=False),
    sa.Column("trading_plan_config_version", sa.Integer()),
    sa.Column("position_version", sa.Integer()),
    sa.Column("context_digest", FINGERPRINT, nullable=False),
    sa.Column("issued_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("expires_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("dedupe_key", sa.Text(), nullable=False, unique=True),
    sa.Column("payload_fingerprint", FINGERPRINT, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("inserted_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(MARKET_CHECK, name="market_values"),
    sa.CheckConstraint(DIRECTION_CHECK, name="direction_values"),
    sa.CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
    sa.CheckConstraint(
        "char_length(proposal_digest) = 64",
        name="proposal_digest_length",
    ),
    sa.CheckConstraint(
        "char_length(payload_fingerprint) = 64",
        name="payload_fingerprint_length",
    ),
)

sa.Index(
    "ix_decision_tickets_signal_id_issued_at",
    decision_tickets.c.signal_id,
    decision_tickets.c.issued_at,
)

signal_instances.append_constraint(
    sa.ForeignKeyConstraint(
        [signal_instances.c.latest_decision_ticket_id],
        [decision_tickets.c.id],
        name="fk_signal_instances_latest_decision_ticket_id_decision_tickets",
        use_alter=True,
    )
)

signal_transitions = sa.Table(
    "signal_transitions",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("signal_id", UUID, sa.ForeignKey("loot.signal_instances.id"), nullable=False),
    sa.Column(
        "decision_ticket_id",
        UUID,
        sa.ForeignKey("loot.decision_tickets.id"),
        nullable=True,
    ),
    sa.Column("event_id", UUID, nullable=False, unique=True),
    sa.Column("from_state", sa.String(24), nullable=False),
    sa.Column("to_state", sa.String(24), nullable=False),
    sa.Column("from_version", sa.Integer(), nullable=False),
    sa.Column("to_version", sa.Integer(), nullable=False),
    sa.Column("occurred_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("inserted_at", UTC_TIMESTAMP, nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint("from_state <> to_state", name="state_changes"),
    sa.CheckConstraint("to_version = from_version + 1", name="version_increments"),
    sa.UniqueConstraint(
        "signal_id",
        "decision_ticket_id",
        name="uq_signal_transitions_signal_ticket",
    ),
)

sa.Index(
    "ix_signal_transitions_signal_id_occurred_at",
    signal_transitions.c.signal_id,
    signal_transitions.c.occurred_at,
)

decision_ticket_consumptions = sa.Table(
    "decision_ticket_consumptions",
    metadata,
    sa.Column(
        "decision_ticket_id",
        UUID,
        sa.ForeignKey(
            "loot.decision_tickets.id",
            name="fk_ticket_consumptions_ticket",
        ),
        primary_key=True,
    ),
    sa.Column("signal_id", UUID, sa.ForeignKey("loot.signal_instances.id"), nullable=False),
    sa.Column(
        "transition_id",
        UUID,
        sa.ForeignKey(
            "loot.signal_transitions.id",
            name="fk_ticket_consumptions_transition",
        ),
    ),
    sa.Column("ticket_fingerprint", FINGERPRINT, nullable=False),
    sa.Column("consumed_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("result_payload", JSONB, nullable=False),
    sa.CheckConstraint(
        "char_length(ticket_fingerprint) = 64",
        name="ticket_fingerprint_length",
    ),
)

outbox_events = sa.Table(
    "outbox_events",
    metadata,
    sa.Column("event_id", UUID, primary_key=True),
    sa.Column("event_type", sa.String(160), nullable=False),
    sa.Column("event_version", sa.Integer(), nullable=False),
    sa.Column("aggregate_type", sa.String(80), nullable=False),
    sa.Column("aggregate_id", UUID, nullable=False),
    sa.Column("correlation_id", UUID, nullable=False),
    sa.Column("causation_id", UUID),
    sa.Column("partition_key", sa.String(240), nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("occurred_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("available_at", UTC_TIMESTAMP, nullable=False),
    sa.Column("published_at", UTC_TIMESTAMP),
    sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("locked_at", UTC_TIMESTAMP),
    sa.Column("last_error", sa.Text()),
    sa.CheckConstraint("event_version >= 1", name="event_version_positive"),
    sa.CheckConstraint("attempt_count >= 0", name="attempt_non_negative"),
)

sa.Index(
    "ix_outbox_events_unpublished_available",
    outbox_events.c.available_at,
    outbox_events.c.occurred_at,
    postgresql_where=outbox_events.c.published_at.is_(None),
)
