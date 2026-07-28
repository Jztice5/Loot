"""Crypto 常驻监控 Worker 应用编排测试。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import UUID, uuid4

from loot.application import (
    CryptoMonitoringWorker,
    CryptoRunCheckpoint,
    CryptoRunMode,
    CryptoRunOnceCommand,
    CryptoRunOnceResult,
    CryptoRunStatus,
    MonitoringInputChangedError,
    MonitoringWorkerTickStatus,
    default_btc_usdt_instrument,
)
from loot.contracts import (
    Instrument,
    Market,
    MarketSnapshot,
    MonitoringRun,
    MonitoringRunOutcome,
    MonitoringRunPhase,
    MonitoringRunStatus,
    Timeframe,
    monitoring_execution_context_digest,
    monitoring_run_id,
    monitoring_run_key,
)
from loot.domains.crypto import (
    CryptoTargetWindowUnavailableError,
    FakeCryptoProvider,
)


class _RunOnceStub:
    """报告 PREFILTERED 后返回指定正常业务结果。"""

    def __init__(self, status: CryptoRunStatus) -> None:
        self._status = status

    def run_with_snapshot(
            self,
            command: CryptoRunOnceCommand,
            snapshot: MarketSnapshot,
            *,
            evaluated_at: datetime | None = None,
            on_checkpoint: Callable[[CryptoRunCheckpoint], None] | None = None,
    ) -> CryptoRunOnceResult:
        assert evaluated_at is not None
        assert on_checkpoint is not None
        on_checkpoint(
            CryptoRunCheckpoint(
                phase=MonitoringRunPhase.PREFILTERED,
                snapshot_id=snapshot.id,
                snapshot_content_hash=snapshot.snapshot_content_hash,
                evaluated_at=evaluated_at,
            )
        )
        return CryptoRunOnceResult(
            run_id=command.run_id,
            mode=command.mode,
            status=self._status,
            reason="NO_CLOSED_STRUCTURE_BREAK",
            snapshot_id=snapshot.id,
        )


class _UnavailableProvider:
    """稳定模拟目标 K 线尚未发布。"""

    @property
    def provider_name(self) -> str:
        return "unavailable.provider"

    def fetch_recent_bars(self, *args: Any, **kwargs: Any) -> MarketSnapshot:
        raise AssertionError("worker must not fetch the recent window")

    def fetch_bars_ending_at(self, *args: Any, **kwargs: Any) -> MarketSnapshot:
        raise CryptoTargetWindowUnavailableError("target is not published")


class _FakeMonitoringRepository:
    """用不可变契约模拟 Run 账本的版本推进。"""

    def __init__(
            self,
            run: MonitoringRun,
            *,
            input_changed: bool = False,
    ) -> None:
        self.run = run
        self.instrument = default_btc_usdt_instrument()
        self.input_changed = input_changed
        self.materialized = (run,)

    def materialize_due_runs(
            self,
            *,
            now: datetime,
            workflow_version: str,
            subscription_ids: tuple[UUID, ...] | None = None,
    ) -> tuple[MonitoringRun, ...]:
        _ = (now, workflow_version, subscription_ids)
        return self.materialized

    def claim_due_run(
            self,
            *,
            worker_id: str,
            now: datetime,
            workflow_version: str,
    ) -> MonitoringRun | None:
        _ = (worker_id, now, workflow_version)
        return self.run

    def load_bound_instrument(self, run: MonitoringRun) -> Instrument:
        _ = run
        return self.instrument

    def bind_input(
            self,
            *,
            snapshot: MarketSnapshot,
            evaluated_at: datetime,
            now: datetime,
            **kwargs: Any,
    ) -> MonitoringRun:
        _ = kwargs
        if self.input_changed:
            raise MonitoringInputChangedError("changed")
        self.run = self._replace(
            phase=MonitoringRunPhase.INPUT_BOUND,
            input_snapshot_id=snapshot.id,
            snapshot_content_hash=snapshot.snapshot_content_hash,
            source_provider=snapshot.source_provider,
            decision_evaluated_at=evaluated_at,
            updated_at=now,
            version=self.run.version + 1,
        )
        return self.run

    def record_checkpoint(
            self,
            *,
            phase: MonitoringRunPhase,
            now: datetime,
            **identifiers: Any,
    ) -> MonitoringRun:
        fact_fields = {
            "candidate_id",
            "signal_id",
            "proposal_id",
            "policy_evaluation_id",
            "decision_ticket_id",
        }
        values = {
            key: value
            for key, value in identifiers.items()
            if key in fact_fields and value is not None
        }
        self.run = self._replace(
            **values,
            phase=phase,
            updated_at=now,
            version=self.run.version + 1,
        )
        return self.run

    @staticmethod
    def decision_ticket_is_expired(
            decision_ticket_id: UUID,
            *,
            now: datetime,
    ) -> bool:
        _ = (decision_ticket_id, now)
        return False

    def complete_run(
            self,
            *,
            outcome: MonitoringRunOutcome,
            now: datetime,
            **kwargs: Any,
    ) -> MonitoringRun:
        _ = kwargs
        self.run = self._replace(
            status=MonitoringRunStatus.COMPLETED,
            phase=MonitoringRunPhase.FINISHED,
            outcome=outcome,
            lease_token=None,
            lease_owner=None,
            lease_expires_at=None,
            updated_at=now,
            completed_at=now,
            version=self.run.version + 1,
        )
        return self.run

    def record_failure(
            self,
            *,
            error_code: str,
            retryable: bool,
            next_attempt_at: datetime | None,
            now: datetime,
            **kwargs: Any,
    ) -> MonitoringRun:
        _ = kwargs
        should_retry = retryable and self.run.attempt_count < self.run.max_attempts
        self.run = self._replace(
            status=(
                MonitoringRunStatus.RETRY_WAIT
                if should_retry
                else MonitoringRunStatus.FAILED
            ),
            next_attempt_at=next_attempt_at if should_retry else None,
            lease_token=None,
            lease_owner=None,
            lease_expires_at=None,
            last_error_code=error_code,
            updated_at=now,
            completed_at=None if should_retry else now,
            version=self.run.version + 1,
        )
        return self.run

    def _replace(self, **changes: Any) -> MonitoringRun:
        return MonitoringRun.model_validate({**self.run.model_dump(), **changes})


class CryptoMonitoringWorkerTest(unittest.TestCase):
    """验证 Worker 只编排精确输入、阶段恢复和失败分类。"""

    def setUp(self) -> None:
        self.now = datetime(2026, 7, 28, 8, 2, tzinfo=UTC)
        self.run = _running_run(self.now)

    def test_no_candidate_is_completed_without_retry(self) -> None:
        repository = _FakeMonitoringRepository(self.run)
        worker = CryptoMonitoringWorker(
            repository=repository,
            provider=FakeCryptoProvider(received_at=self.now),
            run_once_service=_RunOnceStub(CryptoRunStatus.NO_CANDIDATE),
            worker_id="worker-a",
            run_mode=CryptoRunMode.LIVE,
            clock=lambda: self.now,
        )

        result = worker.tick()

        self.assertEqual(result.status, MonitoringWorkerTickStatus.COMPLETED)
        self.assertEqual(result.outcome, MonitoringRunOutcome.NO_CANDIDATE)
        self.assertEqual(repository.run.status, MonitoringRunStatus.COMPLETED)

    def test_provider_unavailable_schedules_retry(self) -> None:
        repository = _FakeMonitoringRepository(self.run)
        worker = CryptoMonitoringWorker(
            repository=repository,
            provider=_UnavailableProvider(),
            run_once_service=_RunOnceStub(CryptoRunStatus.NO_CANDIDATE),
            worker_id="worker-a",
            clock=lambda: self.now,
        )

        result = worker.tick()

        self.assertEqual(result.status, MonitoringWorkerTickStatus.RETRY_SCHEDULED)
        self.assertEqual(repository.run.status, MonitoringRunStatus.RETRY_WAIT)
        self.assertEqual(repository.run.next_attempt_at, self.now + timedelta(seconds=30))

    def test_changed_snapshot_fails_without_retry(self) -> None:
        repository = _FakeMonitoringRepository(self.run, input_changed=True)
        worker = CryptoMonitoringWorker(
            repository=repository,
            provider=FakeCryptoProvider(received_at=self.now),
            run_once_service=_RunOnceStub(CryptoRunStatus.NO_CANDIDATE),
            worker_id="worker-a",
            clock=lambda: self.now,
        )

        result = worker.tick()

        self.assertEqual(result.status, MonitoringWorkerTickStatus.FAILED)
        self.assertEqual(repository.run.last_error_code, "INPUT_CHANGED")
        self.assertIsNone(repository.run.next_attempt_at)


def _running_run(now: datetime) -> MonitoringRun:
    subscription_id = uuid4()
    watch_item_id = uuid4()
    instrument_id = default_btc_usdt_instrument().instrument_id
    target = now.replace(minute=0, second=0, microsecond=0)
    workflow_version = "crypto.monitoring.h1.v1"
    return MonitoringRun(
        id=monitoring_run_id(subscription_id, target, workflow_version),
        run_key=monitoring_run_key(subscription_id, target, workflow_version),
        subscription_id=subscription_id,
        watch_item_id=watch_item_id,
        instrument_id=instrument_id,
        market=Market.CRYPTO,
        timeframe=Timeframe.H1,
        target_bar_closed_at=target,
        workflow_version=workflow_version,
        execution_context_digest=monitoring_execution_context_digest(
            subscription_id=subscription_id,
            watch_item_id=watch_item_id,
            instrument_id=instrument_id,
            watch_item_version=0,
            subscription_config_version=1,
            workflow_version=workflow_version,
        ),
        watch_item_version=0,
        subscription_config_version=1,
        status=MonitoringRunStatus.RUNNING,
        phase=MonitoringRunPhase.MATERIALIZED,
        attempt_count=1,
        max_attempts=5,
        lease_token=uuid4(),
        lease_owner="worker-a",
        lease_expires_at=now + timedelta(minutes=5),
        created_at=now - timedelta(seconds=30),
        updated_at=now,
        version=1,
    )


if __name__ == "__main__":
    unittest.main()
