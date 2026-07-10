"""Event envelope contract shared by producers and consumers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from loot.contracts.base import ContractModel, ensure_non_empty, ensure_utc_datetime


class EventEnvelope(ContractModel):
    """Versioned event envelope for at-least-once delivery.

    All event producers must populate tracing identifiers so consumers can
    deduplicate and replay the business chain deterministically.
    """

    event_id: UUID
    event_type: str
    event_version: int = Field(ge=1)
    occurred_at: datetime
    producer: str
    correlation_id: UUID
    causation_id: UUID | None = None
    partition_key: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type", "producer", "partition_key")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)
