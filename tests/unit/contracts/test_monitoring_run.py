"""MonitoringRun 与 Attempt 契约单元测试。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError

from loot.contracts import (
    Market,
    MonitoringAttemptStatus,
    MonitoringRun,
    MonitoringRunAttempt,
    MonitoringRunOutcome,
    MonitoringRunPhase,
    MonitoringRunStatus,
    Timeframe,
    monitoring_execution_context_digest,
    monitoring_run_id,
    monitoring_run_key,
)


class MonitoringRunContractTest(unittest.TestCase):
    """验证稳定身份以及状态、租约、输入之间的组合不变量。"""

    def setUp(self) -> None:
        self.target = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
        self.subscription_id = uuid4()
        self.watch_item_id = uuid4()
        self.instrument_id = uuid4()

    def test_identity_is_stable_and_changes_with_business_key(self) -> None:
        key = monitoring_run_key(
            self.subscription_id,
            self.target,
            "crypto.monitoring.h1.v1",
        )
        first = monitoring_run_id(
            self.subscription_id,
            self.target,
            "crypto.monitoring.h1.v1",
        )
        duplicate = monitoring_run_id(
            self.subscription_id,
            self.target,
            "crypto.monitoring.h1.v1",
        )
        next_period = monitoring_run_id(
            self.subscription_id,
            self.target + timedelta(hours=1),
            "crypto.monitoring.h1.v1",
        )

        self.assertIn(str(self.subscription_id), key)
        self.assertEqual(first, duplicate)
        self.assertNotEqual(first, next_period)
        with self.assertRaisesRegex(ValidationError, "canonical business key"):
            self._run(id=uuid4())

    def test_execution_context_digest_binds_configuration_versions(self) -> None:
        first = self._context_digest(watch_item_version=2)
        duplicate = self._context_digest(watch_item_version=2)
        changed = self._context_digest(watch_item_version=3)

        self.assertEqual(first, duplicate)
        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, changed)

    def test_running_requires_complete_lease(self) -> None:
        with self.assertRaisesRegex(ValidationError, "complete lease"):
            self._run(status=MonitoringRunStatus.RUNNING)

        running = self._run(
            status=MonitoringRunStatus.RUNNING,
            lease_token=uuid4(),
            lease_owner="worker-a",
            lease_expires_at=self.target + timedelta(minutes=5),
            attempt_count=1,
        )

        self.assertEqual(running.status, MonitoringRunStatus.RUNNING)

    def test_retry_and_completed_states_require_their_metadata(self) -> None:
        with self.assertRaisesRegex(ValidationError, "next_attempt_at"):
            self._run(status=MonitoringRunStatus.RETRY_WAIT, attempt_count=1)
        with self.assertRaisesRegex(ValidationError, "outcome and FINISHED"):
            self._run(
                status=MonitoringRunStatus.COMPLETED,
                completed_at=self.target + timedelta(minutes=2),
            )

        completed = self._run(
            status=MonitoringRunStatus.COMPLETED,
            phase=MonitoringRunPhase.FINISHED,
            outcome=MonitoringRunOutcome.NO_CANDIDATE,
            input_snapshot_id=uuid4(),
            snapshot_content_hash="a" * 64,
            source_provider="fake.crypto",
            decision_evaluated_at=self.target,
            completed_at=self.target + timedelta(minutes=2),
        )

        self.assertEqual(completed.outcome, MonitoringRunOutcome.NO_CANDIDATE)

    def test_snapshot_binding_is_all_or_nothing(self) -> None:
        with self.assertRaisesRegex(ValidationError, "bind together"):
            self._run(input_snapshot_id=uuid4())

        bound = self._run(
            phase=MonitoringRunPhase.INPUT_BOUND,
            input_snapshot_id=uuid4(),
            snapshot_content_hash="a" * 64,
            source_provider="fake.crypto",
            decision_evaluated_at=self.target,
        )

        self.assertEqual(bound.phase, MonitoringRunPhase.INPUT_BOUND)

    def test_attempt_failure_metadata_is_consistent(self) -> None:
        attempt_id = uuid4()
        lease_token = uuid4()
        started = MonitoringRunAttempt(
            id=attempt_id,
            run_id=uuid4(),
            attempt_number=1,
            lease_token=lease_token,
            worker_id="worker-a",
            status=MonitoringAttemptStatus.STARTED,
            started_at=self.target,
        )
        failed = MonitoringRunAttempt.model_validate(
            {
                **started.model_dump(),
                "status": MonitoringAttemptStatus.FAILED,
                "finished_at": self.target + timedelta(seconds=2),
                "error_code": "PROVIDER_TIMEOUT",
                "retryable": True,
                "next_attempt_at": self.target + timedelta(seconds=30),
            }
        )

        self.assertTrue(failed.retryable)
        with self.assertRaisesRegex(ValidationError, "requires error_code"):
            MonitoringRunAttempt.model_validate(
                {
                    **started.model_dump(),
                    "status": MonitoringAttemptStatus.FAILED,
                    "finished_at": self.target + timedelta(seconds=2),
                }
            )

    def _run(self, **changes: object) -> MonitoringRun:
        workflow_version = "crypto.monitoring.h1.v1"
        values = {
            "id": monitoring_run_id(
                self.subscription_id,
                self.target,
                workflow_version,
            ),
            "run_key": monitoring_run_key(
                self.subscription_id,
                self.target,
                workflow_version,
            ),
            "subscription_id": self.subscription_id,
            "watch_item_id": self.watch_item_id,
            "instrument_id": self.instrument_id,
            "market": Market.CRYPTO,
            "timeframe": Timeframe.H1,
            "target_bar_closed_at": self.target,
            "workflow_version": workflow_version,
            "execution_context_digest": self._context_digest(watch_item_version=2),
            "watch_item_version": 2,
            "subscription_config_version": 1,
            "status": MonitoringRunStatus.PENDING,
            "phase": MonitoringRunPhase.MATERIALIZED,
            "attempt_count": 0,
            "max_attempts": 5,
            "created_at": self.target,
            "updated_at": self.target,
            "version": 0,
        }
        values.update(changes)
        return MonitoringRun.model_validate(values)

    def _context_digest(self, *, watch_item_version: int) -> str:
        return monitoring_execution_context_digest(
            subscription_id=self.subscription_id,
            watch_item_id=self.watch_item_id,
            instrument_id=self.instrument_id,
            watch_item_version=watch_item_version,
            subscription_config_version=1,
            workflow_version="crypto.monitoring.h1.v1",
        )


if __name__ == "__main__":
    unittest.main()
