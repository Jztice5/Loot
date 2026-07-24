"""监控订阅和候选事件契约。

业务描述:
    定义从用户自选派生出来的监控任务，以及确定性预筛选产生的候选事件。

业务原因:
    Loot 不做全市场扫描，监控必须从用户明确配置出发；Agent 只能被候选事件唤醒。

调用链:
    WatchItem -> MonitoringSubscription -> PreFilter -> CandidateEvent -> Market Agent
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from loot.contracts.base import ContractModel, ensure_non_empty, ensure_utc_datetime
from loot.contracts.enums import (
    CandidateType,
    Direction,
    Market,
    MonitoringSubscriptionStatus,
    Priority,
    Timeframe,
)


class MonitoringSubscription(ContractModel):
    """由 WatchItem 派生的监控订阅。

    业务描述:
        表达某个自选标的在某个周期上的调度入口和市场路由键。

    业务场景:
        - Scheduler 根据 next_run_at 拉起下一次预筛选。
        - Market Router 根据 route_key 把任务送到对应市场域。

    业务规则:
        route_key 不能为空；config_version 用于配置变更后的订阅重建和幂等。
    """

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
    """确定性预筛选输出的候选事件。

    业务描述:
        表达“值得进一步分析”的市场状态变化，但不代表 Signal 已成立。

    业务场景:
        - 价格接近用户价格区域。
        - 结构突破、量能异常、趋势变化或持仓失效位接近。
        - 信息事件被映射到用户自选标的。

    业务原因:
        CandidateEvent 是降低噪声和成本的闸门，避免 Agent 被普通行情频繁唤醒。

    调用链:
        PreFilter -> CandidateEvent -> Market Agent -> Skill Runtime -> EvidenceSet

    业务规则:
        direction 必须显式表达市场判断；trigger_reason、suggested_skill_group 和
        dedupe_key 不能为空；expires_at 必须晚于 occurred_at。
    """

    id: UUID
    candidate_type: CandidateType
    direction: Direction
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
        # 决策注释: 候选事件必须有未来有效期，过期候选不能再唤醒 Agent。
        if self.expires_at <= self.occurred_at:
            raise ValueError("expires_at must be later than occurred_at")
        return self
