-- REQ-0015 forward repair: persist deterministic Signal expiry reconciliation.
-- Target: PostgreSQL 18, database loot_test first.
-- Execution role: loot_migrator. Runtime role: loot_app.

BEGIN;

SET LOCAL TIME ZONE 'UTC';

-- A normal Signal transition consumes an approved DecisionTicket. A deterministic expiry
-- transition is the State Machine's narrowly scoped exception and therefore has no Ticket.
ALTER TABLE loot.signal_transitions
    ALTER COLUMN decision_ticket_id DROP NOT NULL;

COMMIT;
