"""Crypto 常驻监控 Run 与 Attempt 契约。

业务描述:
    固定每个 H1 收盘周期的持久化运行身份、恢复阶段、租约所有权和追加式执行尝试。

业务场景:
    Scheduler 物化到期 Run，Worker 认领后绑定精确行情快照，并在失败或进程重启后恢复。

业务原因:
    进程内定时循环不能证明某个周期是否执行过，也不能安全处理重复调度、租约过期和输入变化。

调用链:
    MonitoringSubscription -> MonitoringRun -> MonitoringRunAttempt -> CryptoRunOnceService

业务规则:
    Run 身份由订阅、目标收盘时间和工作流版本确定；RUNNING 必须持有完整租约；终态不得保留
    租约；COMPLETED 必须记录业务结果；同一 Run 的 Snapshot 输入绑定后不可静默变化。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, field_validator, model_validator

from loot.contracts.base import ContractModel, ensure_non_empty, ensure_utc_datetime
from loot.contracts.enums import Market, Timeframe
from loot.contracts.serialization import payload_fingerprint

CRYPTO_MONITORING_WORKFLOW_VERSION = "crypto.monitoring.h1.v1"


class MonitoringRunStatus(StrEnum):
    """监控运行的执行状态。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class MonitoringRunPhase(StrEnum):
    """跨事务恢复阶段游标，不替代各阶段事实仓库。"""

    MATERIALIZED = "MATERIALIZED"
    INPUT_BOUND = "INPUT_BOUND"
    PREFILTERED = "PREFILTERED"
    SIGNAL_INITIALIZED = "SIGNAL_INITIALIZED"
    ANALYSIS_PERSISTED = "ANALYSIS_PERSISTED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    SIGNAL_APPLIED = "SIGNAL_APPLIED"
    FINISHED = "FINISHED"


class MonitoringRunOutcome(StrEnum):
    """监控运行正常完成后的业务结果。"""

    NO_CANDIDATE = "NO_CANDIDATE"
    CANDIDATE_EXPIRED = "CANDIDATE_EXPIRED"
    POLICY_NOT_APPROVED = "POLICY_NOT_APPROVED"
    SIGNAL_TRANSITIONED = "SIGNAL_TRANSITIONED"


class MonitoringAttemptStatus(StrEnum):
    """一次 Worker 执行尝试的审计状态。"""

    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


_TERMINAL_STATUSES = {
    MonitoringRunStatus.COMPLETED,
    MonitoringRunStatus.FAILED,
    MonitoringRunStatus.CANCELED,
}


class MonitoringRun(ContractModel):
    """一个订阅在一个精确 H1 收盘周期上的当前运行投影。

    业务场景:
        Scheduler 创建稳定 Run，Worker 在每次认领、检查点、重试和完成时更新当前投影。

    业务原因:
        把“某周期是否执行过、使用什么输入、恢复到哪里”固化为可校验事实，而非进程内状态。

    调用链:
        MonitoringSubscription -> MonitoringRun -> MonitoringRunAttempt -> Run-Once facts

    业务规则:
        身份由订阅、目标收盘时间和工作流版本确定；RUNNING 必须持有完整租约；输入首次绑定后
        不可漂移；只有 COMPLETED 可以进入 FINISHED 并记录正常业务结果。
    """

    id: UUID
    run_key: str
    subscription_id: UUID
    watch_item_id: UUID
    instrument_id: UUID
    market: Market
    timeframe: Timeframe
    target_bar_closed_at: datetime
    workflow_version: str
    execution_context_digest: str
    watch_item_version: int = Field(ge=0)
    subscription_config_version: int = Field(ge=1)
    status: MonitoringRunStatus
    phase: MonitoringRunPhase
    outcome: MonitoringRunOutcome | None = None
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    next_attempt_at: datetime | None = None
    lease_token: UUID | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    input_snapshot_id: UUID | None = None
    snapshot_content_hash: str | None = None
    source_provider: str | None = None
    decision_evaluated_at: datetime | None = None
    candidate_id: UUID | None = None
    proposal_id: UUID | None = None
    policy_evaluation_id: UUID | None = None
    decision_ticket_id: UUID | None = None
    signal_id: UUID | None = None
    last_error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    version: int = Field(ge=0)

    @field_validator("run_key", "workflow_version")
    @classmethod
    def _stable_text_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("execution_context_digest")
    @classmethod
    def _context_digest_is_sha256(cls, value: str) -> str:
        normalized = ensure_non_empty(value)
        if len(normalized) != 64 or any(
                character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError("execution_context_digest must be lowercase SHA-256 hex")
        return normalized

    @field_validator("lease_owner", "source_provider", "last_error_code")
    @classmethod
    def _optional_text_is_present(cls, value: str | None) -> str | None:
        return ensure_non_empty(value) if value is not None else None

    @field_validator("snapshot_content_hash")
    @classmethod
    def _snapshot_hash_is_sha256(cls, value: str | None) -> str | None:
        if value is not None and (
                len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("snapshot_content_hash must be lowercase SHA-256 hex")
        return value

    @field_validator(
        "target_bar_closed_at",
        "next_attempt_at",
        "lease_expires_at",
        "decision_evaluated_at",
        "created_at",
        "updated_at",
        "completed_at",
    )
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _run_is_consistent(self) -> "MonitoringRun":
        """阻止非法市场、时间、租约、结果和快照字段组合。"""

        if self.market != Market.CRYPTO or self.timeframe != Timeframe.H1:
            raise ValueError("monitoring worker v0.1 only supports CRYPTO H1")
        expected_key = monitoring_run_key(
            self.subscription_id,
            self.target_bar_closed_at,
            self.workflow_version,
        )
        expected_id = monitoring_run_id(
            self.subscription_id,
            self.target_bar_closed_at,
            self.workflow_version,
        )
        if self.run_key != expected_key or self.id != expected_id:
            raise ValueError("MonitoringRun identity must match its canonical business key")
        if (
                self.target_bar_closed_at.minute != 0
                or self.target_bar_closed_at.second != 0
                or self.target_bar_closed_at.microsecond != 0
        ):
            raise ValueError("target_bar_closed_at must be an exact H1 boundary")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        if self.attempt_count > self.max_attempts:
            raise ValueError("attempt_count must not exceed max_attempts")

        lease_values = (self.lease_token, self.lease_owner, self.lease_expires_at)
        if self.status == MonitoringRunStatus.RUNNING:
            if any(value is None for value in lease_values):
                raise ValueError("RUNNING monitoring run requires a complete lease")
            if self.next_attempt_at is not None:
                raise ValueError("RUNNING monitoring run cannot have next_attempt_at")
        elif any(value is not None for value in lease_values):
            raise ValueError("only RUNNING monitoring run may retain a lease")

        if self.status == MonitoringRunStatus.RETRY_WAIT:
            if self.next_attempt_at is None:
                raise ValueError("RETRY_WAIT monitoring run requires next_attempt_at")
        elif self.next_attempt_at is not None:
            raise ValueError("only RETRY_WAIT monitoring run may have next_attempt_at")

        if self.status == MonitoringRunStatus.COMPLETED:
            if self.outcome is None or self.phase != MonitoringRunPhase.FINISHED:
                raise ValueError("COMPLETED monitoring run requires outcome and FINISHED phase")
        elif self.outcome is not None:
            raise ValueError("only COMPLETED monitoring run may have an outcome")
        if (
                self.phase == MonitoringRunPhase.FINISHED
                and self.status != MonitoringRunStatus.COMPLETED
        ):
            raise ValueError("FINISHED phase is only valid for a COMPLETED monitoring run")

        if self.status in _TERMINAL_STATUSES:
            if self.completed_at is None:
                raise ValueError("terminal monitoring run requires completed_at")
        elif self.completed_at is not None:
            raise ValueError("non-terminal monitoring run cannot have completed_at")

        snapshot_values = (
            self.input_snapshot_id,
            self.snapshot_content_hash,
            self.source_provider,
        )
        if any(value is not None for value in snapshot_values) and any(
                value is None for value in snapshot_values
        ):
            raise ValueError("snapshot identity, content hash and provider bind together")
        if (self.input_snapshot_id is None) != (self.decision_evaluated_at is None):
            raise ValueError("snapshot identity and decision_evaluated_at bind together")
        if self.phase != MonitoringRunPhase.MATERIALIZED and any(
                value is None for value in snapshot_values
        ):
            raise ValueError("phase after MATERIALIZED requires a bound snapshot")
        return self


class MonitoringRunAttempt(ContractModel):
    """一次租约所有者对 MonitoringRun 的追加式执行证据。

    业务场景:
        每次 claim 追加 STARTED Attempt；正常完成、失败或租约过期后写入对应终态。

    业务原因:
        Run 只保留当前投影，Attempt 负责保留每次执行的审计轨迹和恢复依据。

    调用链:
        claim -> STARTED -> COMPLETED | FAILED | ABANDONED

    业务规则:
        Attempt 只追加不覆盖历史；失败必须记录稳定错误码和是否可重试；仅可重试失败携带
        next_attempt_at。
    """

    id: UUID
    run_id: UUID
    attempt_number: int = Field(ge=1)
    lease_token: UUID
    worker_id: str
    status: MonitoringAttemptStatus
    started_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None
    retryable: bool | None = None
    next_attempt_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("worker_id")
    @classmethod
    def _worker_id_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("error_code")
    @classmethod
    def _error_code_is_present(cls, value: str | None) -> str | None:
        return ensure_non_empty(value) if value is not None else None

    @field_validator("started_at", "finished_at", "next_attempt_at")
    @classmethod
    def _attempt_timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _attempt_is_consistent(self) -> "MonitoringRunAttempt":
        if self.status == MonitoringAttemptStatus.STARTED:
            if self.finished_at is not None:
                raise ValueError("STARTED attempt cannot have finished_at")
            if self.error_code is not None or self.retryable is not None:
                raise ValueError("STARTED attempt cannot record a failure")
        elif self.finished_at is None:
            raise ValueError("finished attempt requires finished_at")

        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at must not be earlier than started_at")
        if self.status == MonitoringAttemptStatus.FAILED:
            if self.error_code is None or self.retryable is None:
                raise ValueError("FAILED attempt requires error_code and retryable")
        elif self.error_code is not None or self.retryable is not None:
            raise ValueError("only FAILED attempt may record failure metadata")
        if self.next_attempt_at is not None and (
                self.status != MonitoringAttemptStatus.FAILED or self.retryable is not True
        ):
            raise ValueError("next_attempt_at requires a retryable FAILED attempt")
        return self


def monitoring_run_key(
        subscription_id: UUID,
        target_bar_closed_at: datetime,
        workflow_version: str,
) -> str:
    """生成跨进程一致的规范化运行键。"""

    target = ensure_utc_datetime(target_bar_closed_at)
    version = ensure_non_empty(workflow_version)
    return f"{subscription_id}:{target.isoformat()}:{version}"


def monitoring_run_id(
        subscription_id: UUID,
        target_bar_closed_at: datetime,
        workflow_version: str,
) -> UUID:
    """用规范化运行键生成确定性 UUIDv5。"""

    return uuid5(
        NAMESPACE_URL,
        f"loot:monitoring-run:{monitoring_run_key(subscription_id, target_bar_closed_at, workflow_version)}",
    )


def monitoring_execution_context_digest(
        *,
        subscription_id: UUID,
        watch_item_id: UUID,
        instrument_id: UUID,
        watch_item_version: int,
        subscription_config_version: int,
        workflow_version: str,
) -> str:
    """锁定一次 Run 允许消费的配置版本和工作流语义。"""

    return payload_fingerprint(
        {
            "instrument_id": instrument_id,
            "subscription_config_version": subscription_config_version,
            "subscription_id": subscription_id,
            "watch_item_id": watch_item_id,
            "watch_item_version": watch_item_version,
            "workflow_version": ensure_non_empty(workflow_version),
        }
    )
