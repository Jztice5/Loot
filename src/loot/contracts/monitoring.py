"""Monitoring candidate and subscription contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from loot.contracts.base import ContractModel, ensure_non_empty, ensure_utc_datetime
from loot.contracts.enums import (
    CandidateType,
    Market,
    MonitoringSubscriptionStatus,
    Priority,
    Timeframe,
)


class MonitoringSubscription(ContractModel):
    """Derived monitoring subscription for a watch item and timeframe."""

    id: UUID
    watch_item_id: UUID
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    route_key: str
    next_run_at: datetime | None = None
    status: MonitoringSubscriptionStatus
    config_version: int = Field(ge=1)

    @field_validator("route_key")
    @classmethod
    def _route_key_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("next_run_at")
    @classmethod
    def _next_run_at_is_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None


class CandidateEvent(ContractModel):
    """Deterministic prefilter output that may wake a market agent."""

    id: UUID
    candidate_type: CandidateType
    trigger_reason: str
    snapshot_id: UUID
    watch_item_id: UUID
    position_id: UUID | None = None
    suggested_skill_group: str
    urgency: Priority
    occurred_at: datetime
    expires_at: datetime
    dedupe_key: str

    @field_validator("trigger_reason", "suggested_skill_group", "dedupe_key")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("occurred_at", "expires_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _expires_after_occurrence(self) -> "CandidateEvent":
        if self.expires_at <= self.occurred_at:
            raise ValueError("expires_at must be later than occurred_at")
        return self
