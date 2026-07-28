"""Crypto 常驻监控 Scheduler 与 Worker 应用编排。

业务描述:
    把到期 Subscription 物化为持久化 Run，并用精确 H1 Snapshot 驱动既有 Run-Once 决策链。

业务场景:
    CLI 以 ``--once`` 做人工验收，或以 ``--loop`` 持续处理 ACTIVE Crypto H1 订阅。

业务原因:
    Worker 只负责编排、失败分类和恢复，不拥有市场判断、Policy 授权或 Signal 写权限。

调用链:
    materialize -> claim -> exact Provider window -> bind input -> Run-Once checkpoints
    -> complete | retry | fail | cancel

业务规则:
    每个 Run 复用首次 Snapshot、evaluated_at 和稳定阶段身份；NO_CANDIDATE 正常完成；
    租约丢失后停止写入；已过期 Ticket 不得通过伪造旧时钟继续消费。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Callable, Protocol
from uuid import UUID

from loot.application.crypto_run_once import (
    CryptoRunCheckpoint,
    CryptoRunMode,
    CryptoRunOnceCommand,
    CryptoRunOnceResult,
)
from loot.contracts import (
    CRYPTO_MONITORING_WORKFLOW_VERSION,
    Instrument,
    MarketSnapshot,
    MonitoringRun,
    MonitoringRunOutcome,
    MonitoringRunPhase,
)
from loot.contracts.base import ensure_non_empty, ensure_utc_datetime
from loot.domains.crypto import (
    CryptoMarketDataProvider,
    CryptoProviderError,
    CryptoTargetWindowUnavailableError,
)

_DEFAULT_BACKOFF = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=15),
)


class MonitoringPersistenceError(RuntimeError):
    """Monitoring Run 持久化错误基类。"""


class MonitoringRunNotFoundError(MonitoringPersistenceError):
    """目标 MonitoringRun 不存在。"""


class MonitoringLeaseLostError(MonitoringPersistenceError):
    """调用方已失去 Run 租约或使用了过期版本。"""


class MonitoringInputChangedError(MonitoringPersistenceError):
    """同一 Run 重试时精确行情窗口内容发生变化。"""


class MonitoringFactConflictError(MonitoringPersistenceError):
    """稳定身份对应了不同的运行或阶段事实。"""


class MonitoringConfigurationInactiveError(MonitoringPersistenceError):
    """Run 绑定的 WatchItem、Subscription 或 Instrument 已失效。"""


class MonitoringWorkerTickStatus(StrEnum):
    """单次 Worker tick 的稳定结果。"""

    IDLE = "IDLE"
    COMPLETED = "COMPLETED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    LEASE_LOST = "LEASE_LOST"


@dataclass(frozen=True, slots=True)
class MonitoringWorkerTickResult:
    """Worker 单次轮询的脱敏摘要。"""

    status: MonitoringWorkerTickStatus
    materialized_count: int
    run_id: UUID | None = None
    attempt_number: int | None = None
    outcome: MonitoringRunOutcome | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "status": self.status.value,
            "materialized_count": self.materialized_count,
            "run_id": str(self.run_id) if self.run_id is not None else None,
            "attempt_number": self.attempt_number,
            "outcome": self.outcome.value if self.outcome is not None else None,
            "reason": self.reason,
        }


class MonitoringRepository(Protocol):
    """Worker 所需的持久化端口。"""

    def materialize_due_runs(
            self,
            *,
            now: datetime,
            workflow_version: str,
            subscription_ids: tuple[UUID, ...] | None = None,
    ) -> tuple[MonitoringRun, ...]: ...

    def claim_due_run(
            self,
            *,
            worker_id: str,
            now: datetime,
            workflow_version: str,
    ) -> MonitoringRun | None: ...

    def load_bound_instrument(self, run: MonitoringRun) -> Instrument: ...

    def bind_input(
            self,
            *,
            run_id: UUID,
            lease_token: UUID,
            expected_version: int,
            snapshot: MarketSnapshot,
            evaluated_at: datetime,
            now: datetime,
    ) -> MonitoringRun: ...

    def record_checkpoint(
            self,
            *,
            run_id: UUID,
            lease_token: UUID,
            expected_version: int,
            phase: MonitoringRunPhase,
            now: datetime,
            candidate_id: UUID | None = None,
            signal_id: UUID | None = None,
            proposal_id: UUID | None = None,
            policy_evaluation_id: UUID | None = None,
            decision_ticket_id: UUID | None = None,
    ) -> MonitoringRun: ...

    def decision_ticket_is_expired(
            self,
            decision_ticket_id: UUID,
            *,
            now: datetime,
    ) -> bool: ...

    def complete_run(
            self,
            *,
            run_id: UUID,
            lease_token: UUID,
            expected_version: int,
            outcome: MonitoringRunOutcome,
            now: datetime,
    ) -> MonitoringRun: ...

    def record_failure(
            self,
            *,
            run_id: UUID,
            lease_token: UUID,
            expected_version: int,
            error_code: str,
            retryable: bool,
            next_attempt_at: datetime | None,
            now: datetime,
    ) -> MonitoringRun: ...


class RunOnceExecutor(Protocol):
    """Worker 使用的可恢复 Run-Once 执行端口。"""

    def run_with_snapshot(
            self,
            command: CryptoRunOnceCommand,
            snapshot: MarketSnapshot,
            *,
            evaluated_at: datetime | None = None,
            on_checkpoint: Callable[[CryptoRunCheckpoint], None] | None = None,
    ) -> CryptoRunOnceResult: ...


class CryptoMonitoringWorker:
    """认领并执行一个持久化 Crypto H1 MonitoringRun。

    业务描述:
        将到期订阅物化为 Run，每次 tick 至多认领一个 Run，并复用 Run-Once 完成分析闭环。

    业务场景:
        适用于单次人工验收和常驻轮询；进程重启后由数据库中的 Run、Attempt 与 phase 恢复。

    业务原因:
        进程内定时器无法证明某个 H1 周期是否执行，也无法约束多 Worker 并发和重试输入漂移。

    调用链:
        Scheduler -> MonitoringRepository -> Provider -> CryptoRunOnceService
        -> checkpoint -> MonitoringRepository

    业务规则:
        每次 tick 至多消费一个 Run；Provider 调用不持有数据库事务；重试复用首次 Snapshot 和
        evaluated_at；只有当前 ``lease_token + version`` 的 Worker 可以推进状态。
    """

    def __init__(
            self,
            *,
            repository: MonitoringRepository,
            provider: CryptoMarketDataProvider,
            run_once_service: RunOnceExecutor,
            worker_id: str,
            run_mode: CryptoRunMode = CryptoRunMode.LIVE,
            workflow_version: str = CRYPTO_MONITORING_WORKFLOW_VERSION,
            clock: Callable[[], datetime] | None = None,
            retry_backoff: tuple[timedelta, ...] = _DEFAULT_BACKOFF,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._run_once_service = run_once_service
        self._worker_id = ensure_non_empty(worker_id)
        self._run_mode = run_mode
        self._workflow_version = ensure_non_empty(workflow_version)
        self._clock = clock or _utc_now
        if not retry_backoff or any(delay <= timedelta(0) for delay in retry_backoff):
            raise ValueError("retry_backoff must contain positive durations")
        self._retry_backoff = retry_backoff

    def tick(self) -> MonitoringWorkerTickResult:
        """物化到期周期并执行至多一个 Run。

        状态流转:
            PENDING/RETRY_WAIT/expired RUNNING -> RUNNING
            -> COMPLETED | RETRY_WAIT | FAILED

        幂等与补偿:
            Provider 调用在数据库事务之外；每个 checkpoint 使用最新 version 条件更新；
            任何阶段重投继续使用原 run_id 和首次绑定输入。
        """

        tick_time = self._now()
        materialized = self._repository.materialize_due_runs(
            now=tick_time,
            workflow_version=self._workflow_version,
        )
        claimed = self._repository.claim_due_run(
            worker_id=self._worker_id,
            now=tick_time,
            workflow_version=self._workflow_version,
        )
        if claimed is None:
            return MonitoringWorkerTickResult(
                status=MonitoringWorkerTickStatus.IDLE,
                materialized_count=len(materialized),
            )
        assert claimed.lease_token is not None
        lease_token = claimed.lease_token
        current = claimed

        try:
            # 1. RUNNING 使用物化时绑定的身份；暂停只影响认领前和后续 Run。
            instrument = self._repository.load_bound_instrument(current)

            # 2. 精确读取目标闭合窗口，禁止用当前最新行情替代历史目标。
            snapshot = self._provider.fetch_bars_ending_at(
                instrument,
                current.timeframe,
                target_bar_closed_at=current.target_bar_closed_at,
                limit=4,
            )

            # 3. Snapshot 与业务评估时间只在首次成功读取后绑定一次。
            evaluated_at = current.decision_evaluated_at or self._now()
            current = self._repository.bind_input(
                run_id=current.id,
                lease_token=lease_token,
                expected_version=current.version,
                snapshot=snapshot,
                evaluated_at=evaluated_at,
                now=self._now(),
            )

            def persist_checkpoint(checkpoint: CryptoRunCheckpoint) -> None:
                nonlocal current
                if (
                        checkpoint.snapshot_id != current.input_snapshot_id
                        or checkpoint.snapshot_content_hash != current.snapshot_content_hash
                        or checkpoint.evaluated_at != current.decision_evaluated_at
                ):
                    raise MonitoringFactConflictError(
                        "Run-Once checkpoint differs from bound monitoring input"
                    )
                current = self._repository.record_checkpoint(
                    run_id=current.id,
                    lease_token=lease_token,
                    expected_version=current.version,
                    phase=checkpoint.phase,
                    now=self._now(),
                    candidate_id=checkpoint.candidate_id,
                    signal_id=checkpoint.signal_id,
                    proposal_id=checkpoint.proposal_id,
                    policy_evaluation_id=checkpoint.policy_evaluation_id,
                    decision_ticket_id=checkpoint.decision_ticket_id,
                )
                if (
                        checkpoint.phase == MonitoringRunPhase.POLICY_EVALUATED
                        and checkpoint.decision_ticket_id is not None
                        and self._repository.decision_ticket_is_expired(
                    checkpoint.decision_ticket_id,
                    now=self._now(),
                )
                ):
                    raise MonitoringFactConflictError("AUTHORIZATION_EXPIRED")

            # 4. 复用既有业务链，阶段事实提交后立即推进恢复游标。
            result = self._run_once_service.run_with_snapshot(
                CryptoRunOnceCommand(
                    mode=self._run_mode,
                    instrument=instrument,
                    watch_item_id=current.watch_item_id,
                    timeframe=current.timeframe,
                    watch_item_version=current.watch_item_version,
                    context_digest=current.execution_context_digest,
                    run_id=current.id,
                ),
                snapshot,
                evaluated_at=current.decision_evaluated_at,
                on_checkpoint=persist_checkpoint,
            )
            outcome = MonitoringRunOutcome(result.status.value)
            completed = self._repository.complete_run(
                run_id=current.id,
                lease_token=lease_token,
                expected_version=current.version,
                outcome=outcome,
                now=self._now(),
            )
            return MonitoringWorkerTickResult(
                status=MonitoringWorkerTickStatus.COMPLETED,
                materialized_count=len(materialized),
                run_id=completed.id,
                attempt_number=completed.attempt_count,
                outcome=outcome,
                reason=result.reason,
            )
        except MonitoringLeaseLostError:
            return MonitoringWorkerTickResult(
                status=MonitoringWorkerTickStatus.LEASE_LOST,
                materialized_count=len(materialized),
                run_id=current.id,
                attempt_number=current.attempt_count,
                reason="LEASE_LOST",
            )
        except MonitoringInputChangedError:
            return self._record_failure(
                current,
                lease_token,
                materialized_count=len(materialized),
                error_code="INPUT_CHANGED",
                retryable=False,
            )
        except MonitoringFactConflictError as error:
            reason = str(error)
            error_code = (
                "AUTHORIZATION_EXPIRED"
                if reason == "AUTHORIZATION_EXPIRED"
                else "FACT_CONFLICT"
            )
            return self._record_failure(
                current,
                lease_token,
                materialized_count=len(materialized),
                error_code=error_code,
                retryable=False,
            )
        except (CryptoTargetWindowUnavailableError, CryptoProviderError, TimeoutError, OSError):
            return self._record_failure(
                current,
                lease_token,
                materialized_count=len(materialized),
                error_code="PROVIDER_UNAVAILABLE",
                retryable=True,
            )
        except ValueError:
            return self._record_failure(
                current,
                lease_token,
                materialized_count=len(materialized),
                error_code="CONTRACT_VIOLATION",
                retryable=False,
            )

    def _record_failure(
            self,
            run: MonitoringRun,
            lease_token: UUID,
            *,
            materialized_count: int,
            error_code: str,
            retryable: bool,
    ) -> MonitoringWorkerTickResult:
        now = self._now()
        backoff_index = min(run.attempt_count - 1, len(self._retry_backoff) - 1)
        failed = self._repository.record_failure(
            run_id=run.id,
            lease_token=lease_token,
            expected_version=run.version,
            error_code=error_code,
            retryable=retryable,
            next_attempt_at=(now + self._retry_backoff[backoff_index]) if retryable else None,
            now=now,
        )
        status = (
            MonitoringWorkerTickStatus.RETRY_SCHEDULED
            if failed.status.value == "RETRY_WAIT"
            else MonitoringWorkerTickStatus.FAILED
        )
        return MonitoringWorkerTickResult(
            status=status,
            materialized_count=materialized_count,
            run_id=failed.id,
            attempt_number=failed.attempt_count,
            reason=failed.last_error_code,
        )

    def _now(self) -> datetime:
        return ensure_utc_datetime(self._clock())


def _utc_now() -> datetime:
    return datetime.now(UTC)
