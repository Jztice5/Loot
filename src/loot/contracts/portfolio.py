"""Contracts for watch items, trading plans, and manual positions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from loot.contracts.base import (
    ContractModel,
    ensure_non_empty,
    ensure_positive_decimal,
    ensure_utc_datetime,
)
from loot.contracts.enums import (
    Direction,
    ExitMode,
    InstrumentType,
    Market,
    PositionEventType,
    PositionSide,
    PositionStatus,
    Priority,
    SignalType,
    Timeframe,
    TradingPlanStatus,
    WatchItemStatus,
)
from loot.contracts.market import PriceZone


class VersionedCondition(ContractModel):
    """Versioned human-authored condition used by a trading plan."""

    expression: str
    version: int = Field(default=1, ge=1)

    @field_validator("expression")
    @classmethod
    def _expression_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)


class WatchItem(ContractModel):
    """User-maintained monitored instrument configuration."""

    id: UUID
    user_id: UUID
    instrument_id: UUID
    market: Market
    venue: str
    status: WatchItemStatus
    timeframes: list[Timeframe] = Field(min_length=1)
    monitoring_profile: str
    enabled_signal_types: list[SignalType] = Field(default_factory=list)
    custom_zones: list[PriceZone] = Field(default_factory=list)
    priority: Priority = Priority.NORMAL
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=0)

    @field_validator("venue", "monitoring_profile")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _updated_after_created(self) -> "WatchItem":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self


class TradingPlan(ContractModel):
    """Human-authored plan that constrains signal interpretation."""

    id: UUID
    watch_item_id: UUID
    direction: Direction
    primary_timeframe: Timeframe
    thesis: str
    entry_conditions: VersionedCondition
    invalidation: VersionedCondition
    max_risk_r: Decimal | None = None
    exit_mode: ExitMode
    enabled_skill_ids: list[str] = Field(default_factory=list)
    status: TradingPlanStatus
    config_version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=0)

    @field_validator("thesis")
    @classmethod
    def _thesis_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("enabled_skill_ids")
    @classmethod
    def _skill_ids_are_present(cls, values: list[str]) -> list[str]:
        return [ensure_non_empty(value) for value in values]

    @field_validator("max_risk_r")
    @classmethod
    def _max_risk_is_positive(cls, value: Decimal | None) -> Decimal | None:
        return ensure_positive_decimal(value, "max_risk_r")

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _updated_after_created(self) -> "TradingPlan":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self


class Position(ContractModel):
    """Current projection computed from append-only PositionEvent records."""

    id: UUID
    trading_plan_id: UUID
    instrument_id: UUID
    market: Market
    instrument_type: InstrumentType
    side: PositionSide
    quantity: Decimal = Field(ge=0)
    average_entry_price: Decimal = Field(ge=0)
    current_stop: Decimal | None = None
    realized_pnl: Decimal = Decimal("0")
    status: PositionStatus
    opened_at: datetime
    closed_at: datetime | None = None
    version: int = Field(ge=0)

    @field_validator("current_stop")
    @classmethod
    def _stop_is_positive(cls, value: Decimal | None) -> Decimal | None:
        return ensure_positive_decimal(value, "current_stop")

    @field_validator("opened_at", "closed_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _closed_after_opened(self) -> "Position":
        if self.closed_at is not None and self.closed_at < self.opened_at:
            raise ValueError("closed_at must not be earlier than opened_at")
        return self


class PositionEvent(ContractModel):
    """Append-only manual position event."""

    id: UUID
    position_id: UUID
    event_type: PositionEventType
    quantity_delta: Decimal | None = None
    execution_price: Decimal | None = None
    previous_stop: Decimal | None = None
    new_stop: Decimal | None = None
    occurred_at: datetime
    note: str | None = None
    idempotency_key: str
    created_at: datetime

    @field_validator("idempotency_key")
    @classmethod
    def _idempotency_key_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("note")
    @classmethod
    def _note_is_optional(cls, value: str | None) -> str | None:
        return ensure_non_empty(value) if value is not None else None

    @field_validator("quantity_delta", "execution_price", "previous_stop", "new_stop")
    @classmethod
    def _money_fields_are_positive(cls, value: Decimal | None) -> Decimal | None:
        return ensure_positive_decimal(value, "position event decimal field")

    @field_validator("occurred_at", "created_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _event_payload_matches_type(self) -> "PositionEvent":
        if self.event_type in {
            PositionEventType.OPEN,
            PositionEventType.ADD,
            PositionEventType.REDUCE,
        }:
            if self.quantity_delta is None or self.execution_price is None:
                raise ValueError("quantity_delta and execution_price are required")
        if self.event_type == PositionEventType.MOVE_STOP and self.new_stop is None:
            raise ValueError("new_stop is required for MOVE_STOP")
        return self
