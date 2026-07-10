"""自选、交易计划和手动持仓契约。

业务描述:
    定义用户手动维护的监控意图、交易计划、持仓投影和持仓事件事实。

业务场景:
    - 用户把标的加入自选并配置监控周期。
    - 用户写入 Trading Plan 约束后续信号解释。
    - 用户手动记录开仓、加仓、减仓、移动止损和关闭持仓。

业务原因:
    Loot V1 不连接交易账户，也不自动下单。系统只能基于用户手工事实做提醒，
    因此 PositionEvent 必须成为持仓历史的唯一事实来源。

调用链:
    User Action -> WatchItem/TradingPlan/PositionEvent -> Projection -> Signal Loop

业务规则:
    - WatchItem 和 TradingPlan 是用户意图，不等价于交易指令。
    - PositionEvent 只能追加，Position 只是由事件计算出的当前投影。
    - 所有生命周期时间必须单向推进，避免 replay 产生不同结果。
"""

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
    """交易计划中的版本化人工条件。

    业务描述:
        保存用户写下的入场、失效或其他判断条件，并用 version 标明变更版本。

    业务规则:
        expression 不能为空；条件文本变更必须提升版本，便于历史信号解释可追溯。
    """

    expression: str
    version: int = Field(default=1, ge=1)

    @field_validator("expression")
    @classmethod
    def _expression_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)


class WatchItem(ContractModel):
    """用户自选监控配置。

    业务描述:
        表达用户希望系统持续关注某个标的、哪些周期、哪些信号类型和哪些价格区。

    业务场景:
        - 用户手动加入 BTC、NVDA 或 A 股标的到自选。
        - MonitoringSubscription 根据 WatchItem 派生每个周期的监控任务。
        - PreFilter 根据 custom_zones 和 signal_types 判断是否唤醒后续分析。

    业务原因:
        WatchItem 是监控控制面的入口，先固定它可以避免 Agent 自行扩大扫描范围。

    调用链:
        User Input -> WatchItem -> MonitoringSubscription -> PreFilter -> CandidateEvent

    业务规则:
        timeframes 至少一个；venue 和 monitoring_profile 不能为空；
        updated_at 不能早于 created_at。
    """

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
        # 决策注释: 自选配置时间倒退会让订阅重建和变更审计失去确定顺序。
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self


class TradingPlan(ContractModel):
    """用户人工编写的交易计划。

    业务描述:
        记录用户对某个自选标的的方向、入场条件、失效条件、风险和退出方式。

    业务场景:
        - Decision Skill 判断候选信号是否符合用户原始计划。
        - Policy Gate 判断 signal transition 是否被计划约束允许。
        - Alert 展示提醒时引用 thesis 和 invalidation，避免只给技术噪声。

    业务原因:
        Agent 不能替用户发明交易计划。TradingPlan 是后续信号解释的人工边界。

    调用链:
        User Plan -> TradingPlan -> DecisionTicket -> Policy Gate -> Signal State Machine

    业务规则:
        thesis、entry_conditions 和 invalidation 必须存在；max_risk_r 必须为正数；
        updated_at 不能早于 created_at。
    """

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
        # 决策注释: 计划版本时间倒退会破坏历史 Signal 与计划版本的对应关系。
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self


class Position(ContractModel):
    """由 PositionEvent 计算出的当前持仓投影。

    业务描述:
        表达某个 TradingPlan 下当前还剩多少仓位、均价、止损、已实现盈亏和状态。

    业务场景:
        - Alert 判断提醒是否属于已有持仓风险。
        - Position Risk 类型信号判断是否接近失效位或止损位。
        - UI 展示用户当前手动维护的持仓状态。

    业务原因:
        Position 是投影而不是事实。历史事实只能来自追加的 PositionEvent。

    调用链:
        PositionEvent -> Position Projection -> Position Risk PreFilter -> Signal Loop

    业务规则:
        quantity 和 average_entry_price 不能为负；closed_at 不能早于 opened_at。
    """

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
        # 决策注释: 平仓时间早于开仓时间会让持仓生命周期无法 replay。
        if self.closed_at is not None and self.closed_at < self.opened_at:
            raise ValueError("closed_at must not be earlier than opened_at")
        return self


class PositionEvent(ContractModel):
    """手动持仓追加事件。

    业务描述:
        记录用户对持仓做出的事实变更，包括开仓、加仓、减仓、移动止损和关闭。

    业务场景:
        - 用户手工记录成交后，系统更新 Position 投影。
        - Replay 通过事件重建持仓历史。
        - Alert 根据最新 Position 判断风险和行动价值。

    业务原因:
        V1 不接券商或交易所账户，因此系统不能推断持仓事实，必须由用户显式输入。

    调用链:
        User Action -> PositionEvent -> Position Projection -> Candidate/Signal/Alert

    业务规则:
        OPEN、ADD、REDUCE 必须带 quantity_delta 和 execution_price；
        MOVE_STOP 必须带 new_stop；每个事件必须带 idempotency_key。
    """

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
        # 1. 成交类事件必须携带数量和成交价，才能重建仓位和均价。
        if self.event_type in {
            PositionEventType.OPEN,
            PositionEventType.ADD,
            PositionEventType.REDUCE,
        }:
            if self.quantity_delta is None or self.execution_price is None:
                raise ValueError("quantity_delta and execution_price are required")

        # 2. 移动止损只改变风险边界，不要求成交价，但必须给出新的止损位。
        if self.event_type == PositionEventType.MOVE_STOP and self.new_stop is None:
            raise ValueError("new_stop is required for MOVE_STOP")
        return self
