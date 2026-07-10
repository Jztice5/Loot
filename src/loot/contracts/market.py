"""Market identity contracts."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from loot.contracts.base import ContractModel, ensure_non_empty
from loot.contracts.enums import InstrumentStatus, InstrumentType, Market


class Instrument(ContractModel):
    """Canonical instrument identity shared across bounded contexts."""

    instrument_id: UUID
    market: Market
    venue: str
    symbol: str
    instrument_type: InstrumentType
    quote_currency: str
    timezone: str
    price_scale: int = Field(ge=0)
    status: InstrumentStatus

    @field_validator("venue", "symbol", "quote_currency", "timezone")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)


class PriceZone(ContractModel):
    """User-defined price zone used as evidence, not a direct decision."""

    lower_price: Decimal = Field(gt=0)
    upper_price: Decimal = Field(gt=0)
    label: str | None = None

    @field_validator("label")
    @classmethod
    def _optional_label(cls, value: str | None) -> str | None:
        return ensure_non_empty(value) if value is not None else None

    @model_validator(mode="after")
    def _zone_order_is_valid(self) -> "PriceZone":
        if self.upper_price < self.lower_price:
            raise ValueError("upper_price must be greater than or equal to lower_price")
        return self
