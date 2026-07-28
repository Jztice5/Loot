-- REQ-0014: Crypto WatchItem and MonitoringSubscription baseline.
-- Target: PostgreSQL 18, database loot_test first.
-- Execution role: loot_migrator. Runtime role: loot_app.

BEGIN;

SET LOCAL TIME ZONE 'UTC';

CREATE TABLE loot.instruments (
    instrument_id UUID NOT NULL,
    market VARCHAR(24) NOT NULL,
    venue VARCHAR(80) NOT NULL,
    symbol VARCHAR(80) NOT NULL,
    instrument_type VARCHAR(24) NOT NULL,
    quote_currency VARCHAR(24) NOT NULL,
    timezone VARCHAR(80) NOT NULL,
    price_scale INTEGER NOT NULL,
    status VARCHAR(24) NOT NULL,
    payload_fingerprint VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_instruments PRIMARY KEY (instrument_id),
    CONSTRAINT uq_instruments_natural_identity
        UNIQUE (market, venue, symbol, instrument_type),
    CONSTRAINT ck_instruments_market_values
        CHECK (market IN ('CRYPTO', 'US_EQUITY', 'A_SHARE')),
    CONSTRAINT ck_instruments_status_values
        CHECK (status IN ('ACTIVE', 'PAUSED', 'DELISTED')),
    CONSTRAINT ck_instruments_price_scale_non_negative
        CHECK (price_scale >= 0),
    CONSTRAINT ck_instruments_payload_fingerprint_length
        CHECK (char_length(payload_fingerprint) = 64)
);

CREATE TABLE loot.watch_items (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    instrument_id UUID NOT NULL,
    market VARCHAR(24) NOT NULL,
    venue VARCHAR(80) NOT NULL,
    status VARCHAR(24) NOT NULL,
    monitoring_profile VARCHAR(120) NOT NULL,
    priority VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL,
    payload JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_watch_items PRIMARY KEY (id),
    CONSTRAINT fk_watch_items_instrument_id_instruments
        FOREIGN KEY (instrument_id) REFERENCES loot.instruments (instrument_id),
    CONSTRAINT ck_watch_items_market_values
        CHECK (market IN ('CRYPTO', 'US_EQUITY', 'A_SHARE')),
    CONSTRAINT ck_watch_items_status_values
        CHECK (status IN ('ACTIVE', 'PAUSED', 'ARCHIVED')),
    CONSTRAINT ck_watch_items_version_non_negative
        CHECK (version >= 0),
    CONSTRAINT ck_watch_items_updated_after_created
        CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX uq_watch_items_active_identity
    ON loot.watch_items (user_id, instrument_id, monitoring_profile)
    WHERE status = 'ACTIVE';

CREATE INDEX ix_watch_items_instrument_id
    ON loot.watch_items (instrument_id);

CREATE TABLE loot.monitoring_subscriptions (
    id UUID NOT NULL,
    watch_item_id UUID NOT NULL,
    market VARCHAR(24) NOT NULL,
    instrument_id UUID NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    route_key VARCHAR(240) NOT NULL,
    next_run_at TIMESTAMPTZ NULL,
    status VARCHAR(24) NOT NULL,
    config_version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_monitoring_subscriptions PRIMARY KEY (id),
    CONSTRAINT fk_monitoring_subscriptions_watch_item_id_watch_items
        FOREIGN KEY (watch_item_id) REFERENCES loot.watch_items (id),
    CONSTRAINT fk_monitoring_subscriptions_instrument_id_instruments
        FOREIGN KEY (instrument_id) REFERENCES loot.instruments (instrument_id),
    CONSTRAINT uq_monitoring_subscriptions_watch_timeframe
        UNIQUE (watch_item_id, timeframe),
    CONSTRAINT ck_monitoring_subscriptions_market_values
        CHECK (market IN ('CRYPTO', 'US_EQUITY', 'A_SHARE')),
    CONSTRAINT ck_monitoring_subscriptions_status_values
        CHECK (status IN ('ACTIVE', 'PAUSED', 'ARCHIVED', 'ERROR', 'DEGRADED')),
    CONSTRAINT ck_monitoring_subscriptions_config_version_positive
        CHECK (config_version >= 1),
    CONSTRAINT ck_monitoring_subscriptions_updated_after_created
        CHECK (updated_at >= created_at)
);

CREATE INDEX ix_monitoring_subscriptions_active_schedule
    ON loot.monitoring_subscriptions (status, next_run_at);

GRANT SELECT, INSERT, UPDATE, DELETE
    ON loot.instruments, loot.watch_items, loot.monitoring_subscriptions
    TO loot_app;

COMMIT;
