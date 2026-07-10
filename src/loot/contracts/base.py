"""Shared primitives for contract models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Immutable base model for cross-module contract payloads."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
    )


def ensure_non_empty(value: str) -> str:
    """Validate that a string field carries business-identifying content."""

    if not value or not value.strip():
        raise ValueError("must not be empty")
    return value.strip()


def ensure_utc_datetime(value: datetime) -> datetime:
    """Normalize aware datetimes to UTC and reject naive datetimes."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value.astimezone(UTC)


def ensure_positive_decimal(value: Decimal | None, field_name: str) -> Decimal | None:
    """Validate optional positive decimal values used in market contracts."""

    if value is not None and value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


JsonObject = dict[str, Any]
