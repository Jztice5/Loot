"""证据、决策票据和信号契约。

业务描述:
    定义 Skill 证据、Policy Gate 前的决策请求、Signal 当前投影和状态迁移事件。

业务原因:
    Agent 只能编排 Skill，不能直接写 Signal。所有信号变化必须先形成可审计证据，
    再通过 Policy Gate 和 Signal State Machine。

调用链:
    CandidateEvent -> Skill Runtime -> EvidenceSet -> DecisionTicket
    -> Policy Gate -> Signal State Machine -> SignalInstance/SignalEvent -> Alert
"""

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
    """Skill 运行产生的结构化证据集。

    业务描述:
        记录某个版本的 Skill 在某个输入快照上得到的证据、质量分和输出结构。

    业务场景:
        - PA、量价、信息事件等 Skill 输出可审计证据。
        - DecisionTicket 通过 evidence_refs 引用证据，而不是复制分析文本。
        - Replay 用 skill_version 和 input_snapshot_id 复现当时判断。

    调用链:
        Skill Runtime -> EvidenceSet -> DecisionTicket -> Policy Gate

    业务规则:
        quality 范围是 0 到 1；expires_at 必须晚于 observed_at。
    """

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
        # 决策注释: 已过期或零有效期证据不能支撑新的状态迁移。
        if self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be later than observed_at")
        return self


class DecisionTicket(ContractModel):
    """进入 Policy Gate 前的决策票据。

    业务描述:
        表达 Decision Skill 建议的 Signal 状态迁移，以及支撑该建议的证据引用。

    业务场景:
        - Skill 汇总证据后建议从 OBSERVING 转为 ARMED 或 TRIGGERED。
        - Policy Gate 根据市场规则、TradingPlan 和数据质量决定是否准入。
        - Signal State Machine 只消费通过准入的决策票据。

    业务原因:
        DecisionTicket 把“AI 分析建议”和“系统事实状态变化”隔开，防止越权写信号。

    调用链:
        Decision Skill -> DecisionTicket -> Policy Gate -> Signal State Machine

    业务规则:
        evidence_refs 和 skill_versions 必须非空；next_check_at 不能早于 created_at。
    """

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
        # 决策注释: 决策必须能追溯到具体 Skill 版本，否则无法 replay 和审计。
        if not value:
            raise ValueError("skill_versions must not be empty")
        return {ensure_non_empty(key): ensure_non_empty(version) for key, version in value.items()}

    @field_validator("created_at", "next_check_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _next_check_after_created(self) -> "DecisionTicket":
        # 决策注释: 复查时间倒退会让调度器立即消费过期决策。
        if self.next_check_at is not None and self.next_check_at < self.created_at:
            raise ValueError("next_check_at must not be earlier than created_at")
        return self


class SignalInstance(ContractModel):
    """由 Signal State Machine 控制的当前信号投影。

    业务描述:
        表达某个自选标的、周期和信号类型当前处于什么状态，以及最新决策来源。

    业务场景:
        - UI 展示当前有效信号。
        - Alert Center 判断是否需要提醒。
        - Replay 对比状态机输出是否稳定。

    业务原因:
        SignalInstance 是投影，不是写入口；只有状态机能基于 DecisionTicket 更新它。

    调用链:
        DecisionTicket -> Policy Gate -> Signal State Machine -> SignalInstance

    业务规则:
        dedupe_key 不能为空；expires_at 不能早于 last_transition_at。
    """

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
        # 决策注释: 信号不能在最后一次状态迁移之前过期。
        if self.expires_at is not None and self.expires_at < self.last_transition_at:
            raise ValueError("expires_at must not be earlier than last_transition_at")
        return self


class SignalEvent(ContractModel):
    """状态机完成迁移后发布的信号事件。

    业务描述:
        记录一次真实 Signal 状态变化，供 Alert、Replay 和其他消费者处理。

    业务场景:
        - ARMED 进入 TRIGGERED 后触发提醒。
        - 信号失效、减弱、确认或过期后同步给 UI 和历史记录。
        - Replay 校验重复 DecisionTicket 不会重复迁移。

    业务原因:
        SignalEvent 是状态变化事实，必须由 Signal State Machine 产生，不能由 Agent 写入。

    调用链:
        Signal State Machine -> SignalEvent -> Alert Center/Replay/Projection

    业务规则:
        from_state 和 to_state 不能相同；decision_ticket_id 与 dedupe_key 必须存在。
    """

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
        # 决策注释: 无状态变化的事件会制造重复提醒和错误 replay 记录。
        if self.from_state == self.to_state:
            raise ValueError("signal event must represent a state change")
        return self
