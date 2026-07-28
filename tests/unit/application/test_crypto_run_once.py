"""Crypto Run-Once application service tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from loot.application import (
    CryptoRunCheckpoint,
    CryptoRunMode,
    CryptoRunOnceCommand,
    CryptoRunOnceService,
    CryptoRunStatus,
    DemoBreakoutCryptoProvider,
    default_btc_usdt_instrument,
)
from loot.contracts import (
    DecisionTicket,
    Direction,
    MonitoringRunPhase,
    SignalState,
    Timeframe,
)
from loot.domains.crypto import CryptoPolicyGate, FakeCryptoProvider
from loot.signals import (
    InMemoryAuthorizationRepository,
    SignalAuthorizationContext,
    SignalInitializationRequest,
    SignalInitializationResult,
    SignalStateMachine,
    SignalTransitionResult,
)


class _InMemorySignalWorkflow:
    """Adapt the domain state machine to the PostgreSQL workflow call shape."""

    def __init__(self, repository: InMemoryAuthorizationRepository) -> None:
        self._state_machine = SignalStateMachine(repository)
        self._signal = None
        self.initialize_count = 0
        self.apply_count = 0
        self.correlation_ids: list[UUID] = []

    def initialize(
            self,
            request: SignalInitializationRequest,
            *,
            correlation_id: UUID,
            detected_at: datetime | None = None,
    ) -> SignalInitializationResult:
        """Initialize and retain the current in-memory projection."""

        self.correlation_ids.append(correlation_id)
        self.initialize_count += 1
        result = self._state_machine.initialize(request)
        self._signal = result.signal
        return result

    def apply(
            self,
            decision_ticket: DecisionTicket,
            authorization_context: SignalAuthorizationContext,
            *,
            correlation_id: UUID,
            occurred_at: datetime | None = None,
    ) -> SignalTransitionResult:
        """Apply one authorized Ticket against the retained projection."""

        self.correlation_ids.append(correlation_id)
        self.apply_count += 1
        if self._signal is None:
            raise AssertionError("Signal must be initialized before apply")
        result = self._state_machine.apply(
            self._signal,
            decision_ticket,
            authorization_context,
            occurred_at=occurred_at,
        )
        self._signal = result.signal
        return result


class _RecordingAnalysisRepository:
    """Capture the Analysis transaction input without a database."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record_analysis_result(self, **kwargs: Any) -> None:
        """Record one application call for assertion."""

        self.calls.append(kwargs)


class _FailingProvider:
    """证明预加载 Snapshot 入口不会再次读取 Provider。"""

    @property
    def provider_name(self) -> str:
        return "failing.provider"

    def fetch_recent_bars(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("preloaded execution must not fetch recent bars")

    def fetch_bars_ending_at(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("preloaded execution must not fetch a target window")


class CryptoRunOnceServiceTest(unittest.TestCase):
    """Validate orchestration exits and the successful authorization chain."""

    def setUp(self) -> None:
        """Create stable identities and times for each test."""

        self.received_at = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
        self.evaluated_at = self.received_at + timedelta(minutes=1)
        self.instrument = default_btc_usdt_instrument()

    def test_demo_runs_complete_authorized_signal_transition(self) -> None:
        """Persist one conceptual Analysis and move Signal to ARMED."""

        authorization_repository = InMemoryAuthorizationRepository()
        workflow = _InMemorySignalWorkflow(authorization_repository)
        analysis_repository = _RecordingAnalysisRepository()
        service = CryptoRunOnceService(
            provider=DemoBreakoutCryptoProvider(received_at=self.received_at),
            signal_workflow=workflow,
            analysis_repository=analysis_repository,
            policy_gate=CryptoPolicyGate(authorization_repository),
            clock=lambda: self.evaluated_at,
        )

        result = service.run(self._command(CryptoRunMode.DEMO))

        self.assertEqual(result.status, CryptoRunStatus.SIGNAL_TRANSITIONED)
        self.assertEqual(result.reason, "POLICY_APPROVED")
        self.assertEqual(result.direction, Direction.LONG)
        self.assertEqual(result.signal_state, SignalState.ARMED)
        self.assertIsNotNone(result.candidate_id)
        self.assertIsNotNone(result.proposal_id)
        self.assertIsNotNone(result.policy_evaluation_id)
        self.assertIsNotNone(result.decision_ticket_id)
        self.assertEqual(workflow.initialize_count, 1)
        self.assertEqual(workflow.apply_count, 1)
        self.assertEqual(len(workflow.correlation_ids), 2)
        self.assertEqual(len(analysis_repository.calls), 1)
        self.assertEqual(
            analysis_repository.calls[0]["message_id"],
            result.candidate_id,
        )
        self.assertNotIn("database_url", result.as_dict())

    def test_no_candidate_does_not_initialize_signal_or_record_analysis(self) -> None:
        """Stop after PreFilter when the strict structure rule does not fire."""

        authorization_repository = InMemoryAuthorizationRepository()
        workflow = _InMemorySignalWorkflow(authorization_repository)
        analysis_repository = _RecordingAnalysisRepository()
        service = CryptoRunOnceService(
            provider=FakeCryptoProvider(received_at=self.received_at),
            signal_workflow=workflow,
            analysis_repository=analysis_repository,
            policy_gate=CryptoPolicyGate(authorization_repository),
            clock=lambda: self.evaluated_at,
        )

        result = service.run(self._command(CryptoRunMode.LIVE))

        self.assertEqual(result.status, CryptoRunStatus.NO_CANDIDATE)
        self.assertEqual(result.reason, "NO_CLOSED_STRUCTURE_BREAK")
        self.assertIsNone(result.candidate_id)
        self.assertEqual(workflow.initialize_count, 0)
        self.assertEqual(workflow.apply_count, 0)
        self.assertEqual(analysis_repository.calls, [])

    def test_expired_candidate_does_not_leave_observing_signal(self) -> None:
        """Reject stale market input before Signal initialization."""

        authorization_repository = InMemoryAuthorizationRepository()
        workflow = _InMemorySignalWorkflow(authorization_repository)
        analysis_repository = _RecordingAnalysisRepository()
        service = CryptoRunOnceService(
            provider=DemoBreakoutCryptoProvider(received_at=self.received_at),
            signal_workflow=workflow,
            analysis_repository=analysis_repository,
            policy_gate=CryptoPolicyGate(authorization_repository),
            clock=lambda: self.received_at + timedelta(hours=2),
        )

        result = service.run(self._command(CryptoRunMode.DEMO))

        self.assertEqual(result.status, CryptoRunStatus.CANDIDATE_EXPIRED)
        self.assertIsNotNone(result.candidate_id)
        self.assertEqual(workflow.initialize_count, 0)
        self.assertEqual(analysis_repository.calls, [])

    def test_default_instrument_identity_is_stable(self) -> None:
        """Keep repeated CLI runs on one canonical BTC-USDT instrument."""

        first = default_btc_usdt_instrument()
        second = default_btc_usdt_instrument()

        self.assertEqual(first, second)
        self.assertEqual(first.symbol, "BTC-USDT")
        self.assertEqual(first.venue, "OKX")

    def test_preloaded_snapshot_reports_stable_recovery_checkpoints(self) -> None:
        """Worker 入口跳过 Provider，并让全部阶段复用首次评估时间。"""

        provider = DemoBreakoutCryptoProvider(received_at=self.received_at)
        snapshot = provider.fetch_bars_ending_at(
            self.instrument,
            Timeframe.H1,
            target_bar_closed_at=self.received_at,
            limit=4,
        )
        authorization_repository = InMemoryAuthorizationRepository()
        workflow = _InMemorySignalWorkflow(authorization_repository)
        checkpoints: list[CryptoRunCheckpoint] = []
        service = CryptoRunOnceService(
            provider=_FailingProvider(),
            signal_workflow=workflow,
            analysis_repository=_RecordingAnalysisRepository(),
            policy_gate=CryptoPolicyGate(authorization_repository),
        )

        result = service.run_with_snapshot(
            self._command(CryptoRunMode.LIVE),
            snapshot,
            evaluated_at=self.evaluated_at,
            on_checkpoint=checkpoints.append,
        )

        self.assertEqual(result.status, CryptoRunStatus.SIGNAL_TRANSITIONED)
        self.assertEqual(
            [item.phase for item in checkpoints],
            [
                MonitoringRunPhase.PREFILTERED,
                MonitoringRunPhase.SIGNAL_INITIALIZED,
                MonitoringRunPhase.ANALYSIS_PERSISTED,
                MonitoringRunPhase.POLICY_EVALUATED,
                MonitoringRunPhase.SIGNAL_APPLIED,
            ],
        )
        self.assertTrue(
            all(item.evaluated_at == self.evaluated_at for item in checkpoints)
        )

    def _command(self, mode: CryptoRunMode) -> CryptoRunOnceCommand:
        """Build one unique but otherwise stable Run-Once command."""

        return CryptoRunOnceCommand(
            mode=mode,
            instrument=self.instrument,
            watch_item_id=uuid4(),
            timeframe=Timeframe.H1,
            context_digest="unit-run-once-context-v1",
        )


if __name__ == "__main__":
    unittest.main()
