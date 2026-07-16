"""决策授权链与 Signal 契约。

业务描述:
    定义确定性分析证据、Policy Gate 前提案、Policy 审计事实、授权票据以及 Signal
    投影和事件。

业务原因:
    Proposal 与 Ticket 必须是两个不同阶段的类型。Agent 或确定性分析器只能提出建议，
    Policy Gate 批准后才能签发 Ticket，Signal State Machine 只消费已授权 Ticket。

调用链:
    CandidateEvent -> EvidenceSet -> DecisionProposal -> PolicyEvaluation
    -> [APPROVED] DecisionTicket -> SignalStateMachine -> SignalInstance/SignalEvent
"""

from __future__ import annotations

import hashlib
import json
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
from loot.contracts.enums import (
    Actionability,
    Direction,
    Market,
    PolicyOutcome,
    Priority,
    SignalState,
    SignalType,
    Timeframe,
)


def _validate_skill_versions(value: dict[str, str]) -> dict[str, str]:
    """校验可回放的 Skill 版本映射。"""

    if not value:
        raise ValueError("skill_versions must not be empty")
    return {
        ensure_non_empty(skill_id): ensure_non_empty(version)
        for skill_id, version in value.items()
    }


class EvidenceSet(ContractModel):
    """分析器在一个输入快照上产生的方向性证据。

    业务描述:
        记录 Candidate 对应的版本化分析输出，并保留方向、输入快照和稳定幂等身份。

    业务场景:
        Crypto 确定性 Decision Builder 或后续 Skill Runtime 生成可审计证据。

    调用链:
        CandidateEvent -> Analyzer/Skill -> EvidenceSet -> DecisionProposal

    业务规则:
        quality 范围为 0 到 1；expires_at 必须晚于 observed_at；direction 不得在后续
        Proposal、Policy 或 Ticket 阶段被改写。
    """

    id: UUID
    candidate_event_id: UUID
    skill_run_id: UUID
    skill_id: str
    skill_version: str
    input_snapshot_id: UUID
    direction: Direction
    quality: Decimal = Field(ge=0, le=1)
    observed_at: datetime
    expires_at: datetime
    dedupe_key: str
    output: JsonObject = Field(default_factory=dict)

    @field_validator("skill_id", "skill_version", "dedupe_key")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("observed_at", "expires_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _expires_after_observed(self) -> "EvidenceSet":
        # 已过期或零有效期证据不能支撑新的状态迁移。
        if self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be later than observed_at")
        return self


class DecisionProposal(ContractModel):
    """进入 Policy Gate 前的不可变决策提案。

    业务描述:
        表达基于 Candidate 和 Evidence 建议的 Signal 状态迁移，并绑定审核时需要校验的
        Signal 与业务上下文版本。

    业务场景:
        Deterministic Decision Builder 或未来 Market Agent 汇总证据后请求 Policy 审核。

    业务原因:
        Proposal 不是授权凭证，类型边界防止分析组件绕过 Policy Gate 修改 Signal。

    调用链:
        EvidenceSet -> DecisionProposal -> Policy Gate -> PolicyEvaluation

    业务规则:
        direction、目标 Signal、目标状态、规则版本和上下文摘要必须进入稳定身份；提案
        写入后不可修改，任何语义变化都必须生成新提案。
    """

    id: UUID
    candidate_event_id: UUID
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    signal_type: SignalType
    direction: Direction
    signal_id: UUID
    suggested_transition: SignalState
    evidence_refs: tuple[UUID, ...] = Field(min_length=1)
    skill_versions: dict[str, str]
    rule_version: str
    actionability: Actionability
    position_impact: str
    invalidation: str | None = None
    next_check_at: datetime | None = None
    input_snapshot_id: UUID
    expected_signal_version: int = Field(ge=0)
    watch_item_version: int = Field(ge=0)
    trading_plan_config_version: int | None = Field(default=None, ge=1)
    position_version: int | None = Field(default=None, ge=0)
    context_digest: str
    decision_summary: str
    created_at: datetime
    dedupe_key: str

    @field_validator(
        "rule_version",
        "position_impact",
        "context_digest",
        "decision_summary",
        "dedupe_key",
    )
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("invalidation")
    @classmethod
    def _optional_text_is_non_empty(cls, value: str | None) -> str | None:
        return ensure_non_empty(value) if value is not None else None

    @field_validator("skill_versions")
    @classmethod
    def _skill_versions_are_present(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_skill_versions(value)

    @field_validator("created_at", "next_check_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _next_check_after_created(self) -> "DecisionProposal":
        if self.next_check_at is not None and self.next_check_at < self.created_at:
            raise ValueError("next_check_at must not be earlier than created_at")
        return self

    def content_digest(self) -> str:
        """返回锁定完整 Proposal payload 的 SHA-256 摘要。"""

        canonical_payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


class PolicyGuardResult(ContractModel):
    """Policy Gate 单项 Guard 的结构化审计结果。"""

    guard_id: str
    passed: bool
    reason_code: str
    details: JsonObject = Field(default_factory=dict)

    @field_validator("guard_id", "reason_code")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)


class PolicyEvaluation(ContractModel):
    """Policy Gate 对一个 Proposal 的只追加评估事实。

    业务描述:
        记录 APPROVED、REJECTED 或 DEFERRED 结果、Guard 明细、评估上下文和重评次数。

    业务场景:
        Policy Gate 每次审核都写入评估；只有 APPROVED 结果可以关联 DecisionTicket。

    调用链:
        DecisionProposal -> Policy Gate -> PolicyEvaluation -> [APPROVED] DecisionTicket

    业务规则:
        同一 evaluation_request_id 必须幂等；DEFERRED 必须给出 next_check_at；拒绝或
        延后必须保留原因码，评估事实只能追加不能覆盖。
    """

    id: UUID
    evaluation_request_id: UUID
    proposal_id: UUID
    outcome: PolicyOutcome
    policy_version: str
    proposal_digest: str
    evaluation_context_digest: str
    attempt_number: int = Field(ge=1)
    guard_results: tuple[PolicyGuardResult, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = ()
    evaluated_at: datetime
    expires_at: datetime
    next_check_at: datetime | None = None
    dedupe_key: str

    @field_validator(
        "policy_version",
        "proposal_digest",
        "evaluation_context_digest",
        "dedupe_key",
    )
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("reason_codes")
    @classmethod
    def _reason_codes_are_non_empty(
            cls,
            value: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(ensure_non_empty(reason) for reason in value)

    @field_validator("evaluated_at", "expires_at", "next_check_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _evaluation_lifecycle_is_consistent(self) -> "PolicyEvaluation":
        if self.expires_at <= self.evaluated_at:
            raise ValueError("expires_at must be later than evaluated_at")
        if self.outcome in {PolicyOutcome.REJECTED, PolicyOutcome.DEFERRED}:
            if not self.reason_codes:
                raise ValueError("rejected or deferred evaluation requires reason_codes")
        if self.outcome == PolicyOutcome.DEFERRED:
            if self.next_check_at is None:
                raise ValueError("deferred evaluation requires next_check_at")
            if not self.evaluated_at < self.next_check_at <= self.expires_at:
                raise ValueError(
                    "next_check_at must be after evaluated_at and not after expires_at"
                )
        elif self.next_check_at is not None:
            raise ValueError("next_check_at is only allowed for deferred evaluation")
        return self


class DecisionTicket(ContractModel):
    """Policy Gate 签发的有限期 Signal 状态迁移授权凭证。

    业务描述:
        固定获批 Proposal 的摘要、PolicyEvaluation、目标 Signal、方向、上下文版本和
        唯一授权状态迁移。

    业务场景:
        Policy Gate 仅在 APPROVED 时签发，Signal State Machine 从事实仓库复核后消费。

    业务原因:
        Ticket 是授权而不是建议；状态机不能只信任调用方传入的可构造对象。

    调用链:
        APPROVED PolicyEvaluation -> DecisionTicket -> SignalStateMachine

    业务规则:
        一个 Proposal 生命周期最多一张 Ticket；authorized_transition 是状态机唯一读取
        的目标状态；expires_at 必须晚于 issued_at。
    """

    id: UUID
    proposal_id: UUID
    policy_evaluation_id: UUID
    policy_version: str
    proposal_digest: str
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    direction: Direction
    signal_id: UUID
    authorized_transition: SignalState
    actionability: Actionability
    position_impact: str
    input_snapshot_id: UUID
    expected_signal_version: int = Field(ge=0)
    watch_item_version: int = Field(ge=0)
    trading_plan_config_version: int | None = Field(default=None, ge=1)
    position_version: int | None = Field(default=None, ge=0)
    context_digest: str
    issued_at: datetime
    expires_at: datetime
    dedupe_key: str

    @field_validator(
        "policy_version",
        "proposal_digest",
        "position_impact",
        "context_digest",
        "dedupe_key",
    )
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _expires_after_issue(self) -> "DecisionTicket":
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be later than issued_at")
        return self


class SignalInstance(ContractModel):
    """由 Signal State Machine 控制的当前信号投影。

    业务描述:
        表达一个监控身份和 generation 当前处于什么状态，以及方向和最新授权来源。

    业务场景:
        UI、Alert 和 Replay 读取当前事实；只有状态机可以初始化或更新投影。

    调用链:
        Monitoring lifecycle -> SignalStateMachine.initialize -> OBSERVING
        DecisionTicket -> SignalStateMachine.apply -> updated SignalInstance

    业务规则:
        direction 进入 setup identity；初始 OBSERVING 没有 Ticket，其他状态必须关联最新
        Ticket；generation 从 1 开始；终态实例不得被重置。
    """

    id: UUID
    watch_item_id: UUID
    position_id: UUID | None = None
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    signal_type: SignalType
    direction: Direction
    state: SignalState
    priority: Priority
    actionability: Actionability
    generation: int = Field(ge=1)
    setup_key: str
    latest_decision_ticket_id: UUID | None = None
    dedupe_key: str
    last_transition_at: datetime
    expires_at: datetime | None = None
    version: int = Field(ge=0)

    @field_validator("setup_key", "dedupe_key")
    @classmethod
    def _identity_key_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("last_transition_at", "expires_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _signal_lifecycle_is_consistent(self) -> "SignalInstance":
        if (
                self.state == SignalState.OBSERVING
                and self.latest_decision_ticket_id is not None
        ):
            raise ValueError(
                "latest_decision_ticket_id must be empty in initial OBSERVING state"
            )
        if (
                self.latest_decision_ticket_id is None
                and self.state != SignalState.OBSERVING
        ):
            raise ValueError(
                "latest_decision_ticket_id is required after initial OBSERVING state"
            )
        if self.expires_at is not None and self.expires_at < self.last_transition_at:
            raise ValueError("expires_at must not be earlier than last_transition_at")
        return self


class SignalEvent(ContractModel):
    """状态机完成真实迁移后发布的方向性信号事件。

    业务描述:
        记录一次 Signal 状态变化，并直接保留 Candidate 到 Ticket 的关键追踪引用。

    调用链:
        SignalStateMachine -> SignalEvent -> Alert Center/Replay/Projection

    业务规则:
        from_state 和 to_state 不能相同；direction 必须与 Signal 和授权链一致。
    """

    event_id: UUID
    signal_id: UUID
    market: Market
    instrument_id: UUID
    signal_type: SignalType
    direction: Direction
    from_state: SignalState
    to_state: SignalState
    priority: Priority
    actionable_now: bool
    position_impact: str
    candidate_event_id: UUID
    decision_proposal_id: UUID
    policy_evaluation_id: UUID
    decision_ticket_id: UUID
    input_snapshot_id: UUID
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
