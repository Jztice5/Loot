"""Enumerations shared by Loot contracts."""

from __future__ import annotations

from enum import StrEnum


class Market(StrEnum):
    """Supported market bounded contexts."""

    CRYPTO = "CRYPTO"
    US_EQUITY = "US_EQUITY"
    A_SHARE = "A_SHARE"


class InstrumentType(StrEnum):
    """Supported instrument categories."""

    SPOT = "SPOT"
    PERPETUAL = "PERPETUAL"
    STOCK = "STOCK"
    ETF = "ETF"


class InstrumentStatus(StrEnum):
    """Lifecycle status for an instrument."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELISTED = "DELISTED"


class Timeframe(StrEnum):
    """Canonical monitoring timeframes."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"


class WatchItemStatus(StrEnum):
    """Watch item lifecycle states."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class TradingPlanStatus(StrEnum):
    """Trading plan lifecycle states."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Direction(StrEnum):
    """Trading plan directional bias."""

    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class ExitMode(StrEnum):
    """Supported exit management modes."""

    FIXED_TARGET = "FIXED_TARGET"
    STRUCTURE_TRAILING = "STRUCTURE_TRAILING"
    MANUAL = "MANUAL"


class PositionSide(StrEnum):
    """Position side."""

    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(StrEnum):
    """Position projection states."""

    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


class PositionEventType(StrEnum):
    """Append-only manual position event types."""

    OPEN = "OPEN"
    ADD = "ADD"
    REDUCE = "REDUCE"
    MOVE_STOP = "MOVE_STOP"
    CLOSE = "CLOSE"


class MonitoringSubscriptionStatus(StrEnum):
    """Derived monitoring subscription states."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    DEGRADED = "DEGRADED"


class Priority(StrEnum):
    """Priority used by signals, candidates, and alerts."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Actionability(StrEnum):
    """Whether a signal can be acted on immediately."""

    ACTIONABLE_NOW = "ACTIONABLE_NOW"
    WATCH_ONLY = "WATCH_ONLY"
    BLOCKED_BY_MARKET_RULE = "BLOCKED_BY_MARKET_RULE"
    DATA_QUALITY_BLOCKED = "DATA_QUALITY_BLOCKED"


class SignalState(StrEnum):
    """Signal state machine states."""

    OBSERVING = "OBSERVING"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    CONFIRMED = "CONFIRMED"
    WEAKENING = "WEAKENING"
    INVALIDATED = "INVALIDATED"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"


class SignalType(StrEnum):
    """Initial signal categories."""

    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    VOLUME_BREAKOUT = "VOLUME_BREAKOUT"
    POSITION_RISK = "POSITION_RISK"
    INFORMATION_EVENT = "INFORMATION_EVENT"


class CandidateType(StrEnum):
    """Deterministic prefilter candidate categories."""

    PRICE_ZONE_APPROACH = "PRICE_ZONE_APPROACH"
    STRUCTURE_BREAKOUT = "STRUCTURE_BREAKOUT"
    VOLUME_ANOMALY = "VOLUME_ANOMALY"
    TREND_CHANGE = "TREND_CHANGE"
    POSITION_INVALIDATION_APPROACH = "POSITION_INVALIDATION_APPROACH"
    INFORMATION_EVENT_MAPPED = "INFORMATION_EVENT_MAPPED"
