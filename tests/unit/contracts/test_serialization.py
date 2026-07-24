"""Canonical contract serialization tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from loot.contracts import EventEnvelope
from loot.contracts.serialization import (
    canonical_json,
    json_compatible,
    payload_fingerprint,
)
from loot.persistence.mappers import (
    StoredPayloadConflictError,
    validate_stored_fingerprint,
)


class ContractSerializationTest(unittest.TestCase):
    """Validate stable JSONB payload and fingerprint behavior."""

    def test_mapping_order_does_not_change_fingerprint(self) -> None:
        first = {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "quality": Decimal("0.7500"),
            "observed_at": datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
            "nested": {"beta": 2, "alpha": 1},
        }
        reordered = {
            "nested": {"alpha": 1, "beta": 2},
            "observed_at": datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
            "quality": Decimal("0.7500"),
            "id": UUID("11111111-1111-1111-1111-111111111111"),
        }

        self.assertEqual(canonical_json(first), canonical_json(reordered))
        self.assertEqual(
            payload_fingerprint(first),
            payload_fingerprint(reordered),
        )
        self.assertEqual(len(payload_fingerprint(first)), 64)

    def test_json_compatible_normalizes_database_payload_types(self) -> None:
        payload = json_compatible(
            {
                "id": UUID("11111111-1111-1111-1111-111111111111"),
                "quality": Decimal("0.75"),
                "observed_at": datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
            }
        )

        self.assertEqual(payload["id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(payload["quality"], "0.75")
        self.assertEqual(payload["observed_at"], "2026-07-16T08:00:00Z")

    def test_stored_fingerprint_rejects_changed_contract_payload(self) -> None:
        event = EventEnvelope(
            event_id=UUID("11111111-1111-1111-1111-111111111111"),
            event_type="loot.test.Event",
            event_version=1,
            occurred_at=datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
            producer="loot.tests",
            correlation_id=UUID("22222222-2222-2222-2222-222222222222"),
            partition_key="test",
            payload={"value": 1},
        )

        validate_stored_fingerprint(payload_fingerprint(event), event)
        with self.assertRaises(StoredPayloadConflictError):
            validate_stored_fingerprint("0" * 64, event)


if __name__ == "__main__":
    unittest.main()
