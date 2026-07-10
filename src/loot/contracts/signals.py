"""Decision, evidence, and signal contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from loot.contracts.base import (
    ContractModel,
    JsonObject,
    ensure_non_empty,
    ensure_utc_datetime,
)
from loot.contracts.enums import Actionability, Market, Priority, SignalState, SignalType, Timeframe


class EvidenceSet(ContractModel):
    """Structured evidence emitted by a versioned skill run."""

    id: UUID
    skill_run_id: UUID
    skill_id: str
    skill_version: str
    input_snapshot_id: UUID
    quality: Decimal = Field(ge=0, le=1)
    observed_at: datetime
    expires_at: datetime
    output: JsonObject = Field(default_factory=dict)

    @field_validator("skill_id", "skill_version")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("observed_at", "expires_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _expires_after_observed(self) -> "EvidenceSet":
        if self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be later than observed_at")
        return self


class DecisionTicket(ContractModel):
    """Policy-gated decision request produced by a decision skill."""

    id: UUID
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    suggested_transition: SignalState
    evidence_refs: list[UUID] = Field(min_length=1)
    skill_versions: dict[str, str]
    rule_version: str
    actionability: Actionability
    position_impact: str
    invalidation: str | None = None
    next_check_at: datetime | None = None
    input_snapshot_id: UUID
    decision_summary: str
    created_at: datetime

    @field_validator("rule_version", "position_impact", "decision_summary")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("skill_versions")
    @classmethod
    def _skill_versions_are_present(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("skill_versions must not be empty")
        return {ensure_non_empty(key): ensure_non_empty(version) for key, version in value.items()}

    @field_validator("created_at", "next_check_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _next_check_after_created(self) -> "DecisionTicket":
        if self.next_check_at is not None and self.next_check_at < self.created_at:
            raise ValueError("next_check_at must not be earlier than created_at")
        return self


class SignalInstance(ContractModel):
    """Current signal projection controlled by a state machine."""

    id: UUID
    watch_item_id: UUID
    position_id: UUID | None = None
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    signal_type: SignalType
    state: SignalState
    priority: Priority
    actionability: Actionability
    latest_decision_ticket_id: UUID
    dedupe_key: str
    last_transition_at: datetime
    expires_at: datetime | None = None
    version: int = Field(ge=0)

    @field_validator("dedupe_key")
    @classmethod
    def _dedupe_key_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("last_transition_at", "expires_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _expires_after_transition(self) -> "SignalInstance":
        if self.expires_at is not None and self.expires_at < self.last_transition_at:
            raise ValueError("expires_at must not be earlier than last_transition_at")
        return self


class SignalEvent(ContractModel):
    """Cross-domain signal transition event emitted after state changes."""

    event_id: UUID
    signal_id: UUID
    market: Market
    instrument_id: UUID
    signal_type: SignalType
    from_state: SignalState
    to_state: SignalState
    priority: Priority
    actionable_now: bool
    position_impact: str
    decision_ticket_id: UUID
    occurred_at: datetime
    dedupe_key: str

    @field_validator("position_impact", "dedupe_key")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _state_must_change(self) -> "SignalEvent":
        if self.from_state == self.to_state:
            raise ValueError("signal event must represent a state change")
        return self
