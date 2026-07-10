"""Loot 跨模块枚举契约。

业务描述:
    固定市场、状态、周期、优先级和信号类型等业务词汇，避免各模块自造字符串。

业务原因:
    枚举是事件、数据库投影、测试样例和前端展示的共同语言。这里变化会影响
    Provider、Policy Gate、Signal State Machine 和 Alert Center。

调用链:
    contracts.enums -> domain contracts -> tests/replay/API consumers
"""

from __future__ import annotations

from enum import StrEnum


class Market(StrEnum):
    """市场 bounded context。"""

    CRYPTO = "CRYPTO"
    US_EQUITY = "US_EQUITY"
    A_SHARE = "A_SHARE"


class InstrumentType(StrEnum):
    """可监控标的类型。"""

    SPOT = "SPOT"
    PERPETUAL = "PERPETUAL"
    STOCK = "STOCK"
    ETF = "ETF"


class InstrumentStatus(StrEnum):
    """标的生命周期状态。"""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELISTED = "DELISTED"


class Timeframe(StrEnum):
    """标准监控周期。"""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"


class WatchItemStatus(StrEnum):
    """自选项生命周期状态。"""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class TradingPlanStatus(StrEnum):
    """交易计划生命周期状态。"""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Direction(StrEnum):
    """交易计划方向偏向。"""

    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class ExitMode(StrEnum):
    """退出管理方式。"""

    FIXED_TARGET = "FIXED_TARGET"
    STRUCTURE_TRAILING = "STRUCTURE_TRAILING"
    MANUAL = "MANUAL"


class PositionSide(StrEnum):
    """持仓方向。"""

    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(StrEnum):
    """持仓投影状态。"""

    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


class PositionEventType(StrEnum):
    """手动持仓追加事件类型。"""

    OPEN = "OPEN"
    ADD = "ADD"
    REDUCE = "REDUCE"
    MOVE_STOP = "MOVE_STOP"
    CLOSE = "CLOSE"


class MonitoringSubscriptionStatus(StrEnum):
    """派生监控订阅状态。"""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    DEGRADED = "DEGRADED"


class Priority(StrEnum):
    """候选、信号和提醒共用优先级。"""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Actionability(StrEnum):
    """信号是否具备立即行动价值。"""

    ACTIONABLE_NOW = "ACTIONABLE_NOW"
    WATCH_ONLY = "WATCH_ONLY"
    BLOCKED_BY_MARKET_RULE = "BLOCKED_BY_MARKET_RULE"
    DATA_QUALITY_BLOCKED = "DATA_QUALITY_BLOCKED"


class SignalState(StrEnum):
    """Signal State Machine 状态。"""

    OBSERVING = "OBSERVING"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    CONFIRMED = "CONFIRMED"
    WEAKENING = "WEAKENING"
    INVALIDATED = "INVALIDATED"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"


class SignalType(StrEnum):
    """初始信号类型。"""

    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    VOLUME_BREAKOUT = "VOLUME_BREAKOUT"
    POSITION_RISK = "POSITION_RISK"
    INFORMATION_EVENT = "INFORMATION_EVENT"


class CandidateType(StrEnum):
    """确定性预筛选候选类型。"""

    PRICE_ZONE_APPROACH = "PRICE_ZONE_APPROACH"
    STRUCTURE_BREAKOUT = "STRUCTURE_BREAKOUT"
    VOLUME_ANOMALY = "VOLUME_ANOMALY"
    TREND_CHANGE = "TREND_CHANGE"
    POSITION_INVALIDATION_APPROACH = "POSITION_INVALIDATION_APPROACH"
    INFORMATION_EVENT_MAPPED = "INFORMATION_EVENT_MAPPED"
