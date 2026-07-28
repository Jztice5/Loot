-- REQ-0015: Crypto H1 monitoring Run ledger, leases and execution attempts.
-- Target: PostgreSQL 18, database loot_test first.
-- Execution role: loot_migrator. Runtime role: loot_app.

BEGIN;

SET LOCAL TIME ZONE 'UTC';

CREATE TABLE loot.monitoring_runs (
    id UUID NOT NULL,
    run_key TEXT NOT NULL,
    subscription_id UUID NOT NULL,
    watch_item_id UUID NOT NULL,
    instrument_id UUID NOT NULL,
    market VARCHAR(24) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    target_bar_closed_at TIMESTAMPTZ NOT NULL,
    workflow_version VARCHAR(120) NOT NULL,
    execution_context_digest VARCHAR(64) NOT NULL,
    watch_item_version INTEGER NOT NULL,
    subscription_config_version INTEGER NOT NULL,
    status VARCHAR(24) NOT NULL,
    phase VARCHAR(32) NOT NULL,
    outcome VARCHAR(32) NULL,
    attempt_count INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    next_attempt_at TIMESTAMPTZ NULL,
    lease_token UUID NULL,
    lease_owner VARCHAR(160) NULL,
    lease_expires_at TIMESTAMPTZ NULL,
    input_snapshot_id UUID NULL,
    snapshot_content_hash VARCHAR(64) NULL,
    source_provider VARCHAR(120) NULL,
    decision_evaluated_at TIMESTAMPTZ NULL,
    candidate_id UUID NULL,
    proposal_id UUID NULL,
    policy_evaluation_id UUID NULL,
    decision_ticket_id UUID NULL,
    signal_id UUID NULL,
    last_error_code VARCHAR(120) NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NULL,
    version INTEGER NOT NULL,
    payload JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_monitoring_runs PRIMARY KEY (id),
    CONSTRAINT uq_monitoring_runs_run_key UNIQUE (run_key),
    CONSTRAINT uq_monitoring_runs_subscription_target_workflow
        UNIQUE (subscription_id, target_bar_closed_at, workflow_version),
    CONSTRAINT fk_monitoring_runs_subscription_id_monitoring_subscriptions
        FOREIGN KEY (subscription_id) REFERENCES loot.monitoring_subscriptions (id),
    CONSTRAINT fk_monitoring_runs_watch_item_id_watch_items
        FOREIGN KEY (watch_item_id) REFERENCES loot.watch_items (id),
    CONSTRAINT fk_monitoring_runs_instrument_id_instruments
        FOREIGN KEY (instrument_id) REFERENCES loot.instruments (instrument_id),
    CONSTRAINT ck_monitoring_runs_crypto_market_only CHECK (market = 'CRYPTO'),
    CONSTRAINT ck_monitoring_runs_h1_timeframe_only CHECK (timeframe = '1h'),
    CONSTRAINT ck_monitoring_runs_target_exact_h1_boundary
        CHECK (target_bar_closed_at = date_trunc('hour', target_bar_closed_at)),
    CONSTRAINT ck_monitoring_runs_status_values
        CHECK (status IN ('PENDING', 'RUNNING', 'RETRY_WAIT', 'COMPLETED', 'FAILED', 'CANCELED')),
    CONSTRAINT ck_monitoring_runs_phase_values
        CHECK (phase IN ('MATERIALIZED', 'INPUT_BOUND', 'PREFILTERED', 'SIGNAL_INITIALIZED',
            'ANALYSIS_PERSISTED', 'POLICY_EVALUATED', 'SIGNAL_APPLIED', 'FINISHED')),
    CONSTRAINT ck_monitoring_runs_outcome_values
        CHECK (outcome IS NULL OR outcome IN ('NO_CANDIDATE', 'CANDIDATE_EXPIRED',
            'POLICY_NOT_APPROVED', 'SIGNAL_TRANSITIONED')),
    CONSTRAINT ck_monitoring_runs_attempt_budget CHECK (attempt_count >= 0 AND max_attempts >= 1),
    CONSTRAINT ck_monitoring_runs_attempt_within_budget CHECK (attempt_count <= max_attempts),
    CONSTRAINT ck_monitoring_runs_watch_version_non_negative CHECK (watch_item_version >= 0),
    CONSTRAINT ck_monitoring_runs_subscription_version_positive CHECK (subscription_config_version >= 1),
    CONSTRAINT ck_monitoring_runs_version_non_negative CHECK (version >= 0),
    CONSTRAINT ck_monitoring_runs_updated_after_created CHECK (updated_at >= created_at),
    CONSTRAINT ck_monitoring_runs_context_digest_length
        CHECK (char_length(execution_context_digest) = 64),
    CONSTRAINT ck_monitoring_runs_snapshot_hash_length
        CHECK (snapshot_content_hash IS NULL OR char_length(snapshot_content_hash) = 64),
    CONSTRAINT ck_monitoring_runs_lease_matches_running CHECK (
        (status = 'RUNNING' AND lease_token IS NOT NULL AND lease_owner IS NOT NULL
            AND lease_expires_at IS NOT NULL)
        OR
        (status <> 'RUNNING' AND lease_token IS NULL AND lease_owner IS NULL
            AND lease_expires_at IS NULL)
    ),
    CONSTRAINT ck_monitoring_runs_retry_has_next_attempt
        CHECK ((status = 'RETRY_WAIT') = (next_attempt_at IS NOT NULL)),
    CONSTRAINT ck_monitoring_runs_completed_has_outcome
        CHECK ((status = 'COMPLETED') = (outcome IS NOT NULL)),
    CONSTRAINT ck_monitoring_runs_completed_is_finished
        CHECK (status <> 'COMPLETED' OR phase = 'FINISHED'),
    CONSTRAINT ck_monitoring_runs_terminal_has_completed_at
        CHECK ((status IN ('COMPLETED', 'FAILED', 'CANCELED')) = (completed_at IS NOT NULL)),
    CONSTRAINT ck_monitoring_runs_snapshot_binding_complete CHECK (
        (input_snapshot_id IS NULL AND snapshot_content_hash IS NULL AND source_provider IS NULL)
        OR
        (input_snapshot_id IS NOT NULL AND snapshot_content_hash IS NOT NULL AND source_provider IS NOT NULL)
    ),
    CONSTRAINT ck_monitoring_runs_advanced_phase_has_snapshot
        CHECK (phase = 'MATERIALIZED' OR input_snapshot_id IS NOT NULL),
    CONSTRAINT ck_monitoring_runs_snapshot_has_evaluation_time
        CHECK ((input_snapshot_id IS NULL) = (decision_evaluated_at IS NULL)),
    CONSTRAINT ck_monitoring_runs_finished_phase_is_completed
        CHECK (phase <> 'FINISHED' OR status = 'COMPLETED')
);

CREATE INDEX ix_monitoring_runs_due
    ON loot.monitoring_runs (status, next_attempt_at, target_bar_closed_at);

CREATE INDEX ix_monitoring_runs_expired_lease
    ON loot.monitoring_runs (lease_expires_at)
    WHERE status = 'RUNNING';

CREATE TABLE loot.monitoring_run_attempts (
    id UUID NOT NULL,
    run_id UUID NOT NULL,
    attempt_number INTEGER NOT NULL,
    lease_token UUID NOT NULL,
    worker_id VARCHAR(160) NOT NULL,
    status VARCHAR(24) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NULL,
    error_code VARCHAR(120) NULL,
    retryable BOOLEAN NULL,
    next_attempt_at TIMESTAMPTZ NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT pk_monitoring_run_attempts PRIMARY KEY (id),
    CONSTRAINT fk_monitoring_run_attempts_run_id_monitoring_runs
        FOREIGN KEY (run_id) REFERENCES loot.monitoring_runs (id) ON DELETE CASCADE,
    CONSTRAINT uq_monitoring_run_attempts_number UNIQUE (run_id, attempt_number),
    CONSTRAINT uq_monitoring_run_attempts_lease UNIQUE (run_id, lease_token),
    CONSTRAINT ck_monitoring_run_attempts_attempt_number_positive CHECK (attempt_number >= 1),
    CONSTRAINT ck_monitoring_run_attempts_status_values
        CHECK (status IN ('STARTED', 'COMPLETED', 'FAILED', 'ABANDONED')),
    CONSTRAINT ck_monitoring_run_attempts_started_has_no_finish
        CHECK ((status = 'STARTED') = (finished_at IS NULL)),
    CONSTRAINT ck_monitoring_run_attempts_failure_metadata
        CHECK ((status = 'FAILED') = (error_code IS NOT NULL AND retryable IS NOT NULL)),
    CONSTRAINT ck_monitoring_run_attempts_retry_schedule_matches_failure
        CHECK (next_attempt_at IS NULL OR (status = 'FAILED' AND retryable IS TRUE))
);

CREATE INDEX ix_monitoring_run_attempts_run_started
    ON loot.monitoring_run_attempts (run_id, started_at);

GRANT SELECT, INSERT, UPDATE, DELETE
    ON loot.monitoring_runs, loot.monitoring_run_attempts
    TO loot_app;

COMMIT;
