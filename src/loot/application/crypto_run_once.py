"""Crypto 单次分析与持久化应用服务。

业务描述:
    把 Crypto 行情 Provider、PreFilter、确定性决策、Policy Gate 和 PostgreSQL Signal
    workflow 编排为一次同步运行，并返回可供 DBX 追踪的事实 ID。

业务场景:
    - ``demo`` 模式稳定生成一条 LONG 结构突破，验证完整持久化链路。
    - ``live`` 模式消费 OKX 已收盘 K 线，无候选时正常结束。

业务原因:
    既有领域组件只在测试中被分别调用，缺少一个进程退出后仍保留事实的正式应用入口。

调用链:
    RunOnceCommand -> Provider -> PreFilter -> Signal initialization
    -> Decision Builder -> Analysis Repository -> Policy Gate -> Signal workflow

业务规则:
    应用层不能直接创建 DecisionTicket、更新 Signal 表或伪造 live Candidate；数据库事务、
    幂等和授权复核继续由既有 Repository、Policy Gate 和 Signal workflow 负责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Callable, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from loot.contracts import (
    Actionability,
    DecisionProposal,
    DecisionTicket,
    Direction,
    EvidenceSet,
    Instrument,
    InstrumentStatus,
    InstrumentType,
    Market,
    MarketBar,
    MarketSnapshot,
    SignalState,
    SignalType,
    Timeframe,
)
from loot.contracts.base import ensure_non_empty, ensure_utc_datetime
from loot.domains.crypto import (
    CryptoDecisionContext,
    CryptoMarketDataProvider,
    CryptoPolicyDecision,
    CryptoPolicyEvaluationRequest,
    CryptoPreFilterInput,
    CryptoPreFilterResult,
    CryptoStructurePreFilter,
    DeterministicDecisionBuilder,
    FakeCryptoProvider,
)
from loot.signals import (
    SignalAuthorizationContext,
    SignalInitializationRequest,
    SignalInitializationResult,
    SignalTransitionResult,
)

_ANALYSIS_CONSUMER = "loot.application.crypto_run_once.v1"
_MINIMUM_STRUCTURE_BARS = 4


class CryptoRunMode(StrEnum):
    """Run-Once 行情来源模式。"""

    DEMO = "demo"
    LIVE = "live"


class CryptoRunStatus(StrEnum):
    """Run-Once 稳定结果状态。"""

    NO_CANDIDATE = "NO_CANDIDATE"
    CANDIDATE_EXPIRED = "CANDIDATE_EXPIRED"
    POLICY_NOT_APPROVED = "POLICY_NOT_APPROVED"
    SIGNAL_TRANSITIONED = "SIGNAL_TRANSITIONED"


@dataclass(frozen=True, slots=True)
class CryptoRunOnceCommand:
    """执行一次 Crypto 决策链所需的显式业务上下文。"""

    mode: CryptoRunMode
    instrument: Instrument
    watch_item_id: UUID
    timeframe: Timeframe = Timeframe.H1
    watch_item_version: int = 1
    context_digest: str = "crypto-run-once.v1"
    position_id: UUID | None = None
    trading_plan_config_version: int | None = None
    position_version: int | None = None
    bar_limit: int = _MINIMUM_STRUCTURE_BARS
    run_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        """拒绝跨市场、无效版本和不足以计算结构的运行命令。"""

        if self.instrument.market != Market.CRYPTO:
            raise ValueError("Crypto Run-Once only accepts CRYPTO instruments")
        if self.bar_limit < _MINIMUM_STRUCTURE_BARS:
            raise ValueError("bar_limit must provide at least 4 bars")
        if self.watch_item_version < 0:
            raise ValueError("watch_item_version must be non-negative")
        if (
                self.trading_plan_config_version is not None
                and self.trading_plan_config_version < 1
        ):
            raise ValueError("trading_plan_config_version must be positive")
        if self.position_version is not None and self.position_version < 0:
            raise ValueError("position_version must be non-negative")
        ensure_non_empty(self.context_digest)


@dataclass(frozen=True, slots=True)
class CryptoRunOnceResult:
    """单次运行的结构化摘要，不包含数据库凭据或完整行情 payload。"""

    run_id: UUID
    mode: CryptoRunMode
    status: CryptoRunStatus
    reason: str
    snapshot_id: UUID
    candidate_id: UUID | None = None
    direction: Direction | None = None
    signal_id: UUID | None = None
    proposal_id: UUID | None = None
    policy_evaluation_id: UUID | None = None
    decision_ticket_id: UUID | None = None
    signal_state: SignalState | None = None

    def as_dict(self) -> dict[str, str | None]:
        """转换为 CLI 可直接输出的 JSON 兼容摘要。"""

        return {
            "run_id": str(self.run_id),
            "mode": self.mode.value,
            "status": self.status.value,
            "reason": self.reason,
            "snapshot_id": str(self.snapshot_id),
            "candidate_id": _optional_uuid_text(self.candidate_id),
            "direction": self.direction.value if self.direction is not None else None,
            "signal_id": _optional_uuid_text(self.signal_id),
            "proposal_id": _optional_uuid_text(self.proposal_id),
            "policy_evaluation_id": _optional_uuid_text(
                self.policy_evaluation_id
            ),
            "decision_ticket_id": _optional_uuid_text(self.decision_ticket_id),
            "signal_state": (
                self.signal_state.value if self.signal_state is not None else None
            ),
        }


class _SignalWorkflow(Protocol):
    """Run-Once 依赖的 Signal 持久化端口。"""

    def initialize(
            self,
            request: SignalInitializationRequest,
            *,
            correlation_id: UUID,
    ) -> SignalInitializationResult:
        """初始化 OBSERVING Signal。"""

        ...

    def apply(
            self,
            decision_ticket: DecisionTicket,
            authorization_context: SignalAuthorizationContext,
            *,
            correlation_id: UUID,
            occurred_at: datetime | None = None,
    ) -> SignalTransitionResult:
        """消费已授权 Ticket 并迁移 Signal。"""

        ...


class _AnalysisRepository(Protocol):
    """Run-Once 依赖的 Analysis 事实写入端口。"""

    def record_analysis_result(
            self,
            *,
            consumer_name: str,
            message_id: UUID,
            message_payload: Any,
            received_at: datetime,
            processed_at: datetime,
            evidence: tuple[EvidenceSet, ...],
            proposal: DecisionProposal,
    ) -> Any:
        """原子记录 Inbox、Evidence 和 Proposal。"""

        ...


class _PolicyGate(Protocol):
    """Run-Once 依赖的 Crypto Policy Gate 端口。"""

    def evaluate(
            self,
            request: CryptoPolicyEvaluationRequest,
    ) -> CryptoPolicyDecision:
        """评估 Proposal 并返回可选 Ticket。"""

        ...


@dataclass(frozen=True, slots=True)
class DemoBreakoutCryptoProvider:
    """稳定产生 LONG 结构突破的本地演示 Provider。

    业务描述:
        基于 FakeCryptoProvider 的确定性窗口重建最后一根 K 线，使其收盘价严格突破前三根
        K 线的最高价。

    业务场景:
        REQ-0013 本地演示和无网络测试需要保证完整授权链一定被执行。

    业务原因:
        FakeCryptoProvider 的默认最后收盘价等于参考高点，不满足严格突破规则。

    调用链:
        Run-Once -> DemoBreakoutCryptoProvider -> FakeCryptoProvider
        -> rebuilt MarketSnapshot -> PreFilter

    业务规则:
        所有 K 线仍是已收盘、UTC、确定性假数据，不表达真实市场价格。
    """

    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    start_price: Decimal = Decimal("100")
    step: Decimal = Decimal("1")

    @property
    def provider_name(self) -> str:
        """返回底层 Fake Provider 标识，保持快照和 K 线来源一致。"""

        return "fake.crypto"

    def fetch_recent_bars(
            self,
            instrument: Instrument,
            timeframe: Timeframe,
            *,
            limit: int,
            include_unclosed: bool = False,
    ) -> MarketSnapshot:
        """生成最后一根收盘价严格上破的确定性行情窗口。

        调用链:
            validate limit -> build Fake snapshot -> calculate reference high
            -> rebuild trigger bar -> rebuild content-addressed snapshot
        """

        if limit < _MINIMUM_STRUCTURE_BARS:
            raise ValueError("demo breakout requires at least 4 bars")

        # 1. 生成满足 MarketBar 时间和来源契约的确定性基础窗口。
        baseline = FakeCryptoProvider(
            received_at=ensure_utc_datetime(self.received_at),
            start_price=self.start_price,
            step=self.step,
        ).fetch_recent_bars(
            instrument,
            timeframe,
            limit=limit,
            include_unclosed=include_unclosed,
        )

        # 2. 只重建触发 K 线，使其严格越过 PreFilter 的前三根参考上沿。
        reference_bars = baseline.bars[-_MINIMUM_STRUCTURE_BARS:-1]
        reference_high = max(bar.high_price for bar in reference_bars)
        increment = max(abs(self.step), Decimal("1"))
        trigger = baseline.bars[-1]
        breakout_close = reference_high + increment
        rebuilt_trigger = MarketBar.model_validate(
            {
                **trigger.model_dump(),
                "high_price": max(trigger.high_price, breakout_close + increment),
                "close_price": breakout_close,
                "quote_volume": trigger.volume * breakout_close,
            }
        )

        # 3. 重新计算 Snapshot 内容指纹，避免修改行情事实后复用旧 snapshot_id。
        return MarketSnapshot.from_bars(
            market=baseline.market,
            instrument_id=baseline.instrument_id,
            timeframe=baseline.timeframe,
            source_provider=baseline.source_provider,
            as_of=baseline.as_of,
            bars=(*baseline.bars[:-1], rebuilt_trigger),
        )


class CryptoRunOnceService:
    """编排一次 Crypto Snapshot 到 Signal 迁移的应用服务。

    业务描述:
        在一个同步调用中执行行情读取、低成本筛选、Signal 初始化、确定性分析、Policy
        授权和 Signal 迁移，并返回各阶段事实 ID。

    业务场景:
        本地 demo 保留数据库事实，或用 OKX live 行情执行一次只读市场判断。

    业务原因:
        应用层负责用例顺序和提前退出，领域真假、授权与持久化一致性仍由下层组件拥有。

    调用链:
        Provider -> PreFilter -> [Candidate] Signal workflow -> Decision Builder
        -> Analysis Repository -> Policy Gate -> [APPROVED] Signal workflow

    业务规则:
        无 Candidate 或 Candidate 已过期时不得初始化 Signal；未批准时不得调用迁移入口；
        生产 CLI 注入 PostgreSQL 适配器，单元测试可以注入内存端口。
    """

    def __init__(
            self,
            *,
            provider: CryptoMarketDataProvider,
            signal_workflow: _SignalWorkflow,
            analysis_repository: _AnalysisRepository,
            policy_gate: _PolicyGate,
            prefilter: CryptoStructurePreFilter | None = None,
            decision_builder: DeterministicDecisionBuilder | None = None,
            clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._signal_workflow = signal_workflow
        self._analysis_repository = analysis_repository
        self._policy_gate = policy_gate
        self._prefilter = prefilter or CryptoStructurePreFilter()
        self._decision_builder = decision_builder or DeterministicDecisionBuilder()
        self._clock = clock or _utc_now

    def run(self, command: CryptoRunOnceCommand) -> CryptoRunOnceResult:
        """执行一次完整链路，或在明确业务闸门处提前返回。

        调用链:
            fetch snapshot -> evaluate PreFilter -> validate freshness
            -> initialize Signal -> persist analysis -> evaluate Policy
            -> [APPROVED] apply Ticket -> build result

        幂等与补偿:
            各持久化阶段独立提交并复用既有幂等键；中途失败不删除已提交事实，调用方可按
            相同 Candidate 和上下文重试，Repository 会区分安全重投与 payload 冲突。
        """

        # 1. 读取标准行情并执行确定性成本闸门；live 无突破时不产生 Signal 噪声。
        snapshot = self._provider.fetch_recent_bars(
            command.instrument,
            command.timeframe,
            limit=command.bar_limit,
            include_unclosed=False,
        )
        prefilter_result = self._prefilter.evaluate(
            CryptoPreFilterInput(
                snapshot=snapshot,
                watch_item_id=command.watch_item_id,
                position_id=command.position_id,
            )
        )
        candidate = prefilter_result.candidate
        if candidate is None:
            return self._no_candidate_result(command, snapshot, prefilter_result)

        # 2. 在创建 OBSERVING Signal 前拒绝过期候选，避免留下无法授权的活跃投影。
        evaluated_at = ensure_utc_datetime(self._clock())
        if evaluated_at >= candidate.expires_at:
            return CryptoRunOnceResult(
                run_id=command.run_id,
                mode=command.mode,
                status=CryptoRunStatus.CANDIDATE_EXPIRED,
                reason="CANDIDATE_EXPIRED",
                snapshot_id=snapshot.id,
                candidate_id=candidate.id,
                direction=candidate.direction,
            )

        # 3. 由 Signal workflow 幂等初始化本轮方向性监控投影。
        initialization = self._signal_workflow.initialize(
            SignalInitializationRequest(
                watch_item_id=command.watch_item_id,
                position_id=command.position_id,
                market=Market.CRYPTO,
                instrument_id=command.instrument.instrument_id,
                timeframe=command.timeframe,
                signal_type=SignalType.MARKET_STRUCTURE,
                direction=candidate.direction,
                priority=candidate.urgency,
                actionability=Actionability.WATCH_ONLY,
                setup_key=candidate.dedupe_key,
                initialized_at=candidate.occurred_at,
                expires_at=candidate.expires_at,
            ),
            correlation_id=_stage_id(command.run_id, "signal-initialize"),
        )
        signal = initialization.signal

        # 4. 构建并原子保存 Evidence 和 Proposal；Candidate 作为 Inbox 消息来源参与指纹。
        build_result = self._decision_builder.build(
            CryptoDecisionContext(
                candidate=candidate,
                signal=signal,
                watch_item_version=command.watch_item_version,
                context_digest=command.context_digest,
                trading_plan_config_version=command.trading_plan_config_version,
                position_version=command.position_version,
            )
        )
        self._analysis_repository.record_analysis_result(
            consumer_name=_ANALYSIS_CONSUMER,
            message_id=candidate.id,
            message_payload={
                "candidate": candidate.model_dump(mode="json"),
                "snapshot_content_hash": snapshot.snapshot_content_hash,
            },
            received_at=candidate.occurred_at,
            processed_at=evaluated_at,
            evidence=(build_result.evidence,),
            proposal=build_result.proposal,
        )

        # 5. Policy Gate 复核完整事实链；应用层不能自行构造或补发 Ticket。
        authorization_expires_at = min(
            candidate.expires_at,
            evaluated_at + timedelta(hours=1),
        )
        policy_decision = self._policy_gate.evaluate(
            CryptoPolicyEvaluationRequest(
                evaluation_request_id=_stage_id(command.run_id, "policy-evaluate"),
                proposal=build_result.proposal,
                evidence_sets=(build_result.evidence,),
                signal=signal,
                current_context_digest=command.context_digest,
                watch_item_version=command.watch_item_version,
                trading_plan_config_version=command.trading_plan_config_version,
                position_version=command.position_version,
                evaluated_at=evaluated_at,
                authorization_expires_at=authorization_expires_at,
                data_quality_ready=True,
                market_rule_allows=True,
            )
        )
        if policy_decision.ticket is None:
            return self._policy_not_approved_result(
                command,
                snapshot,
                candidate.id,
                candidate.direction,
                signal.id,
                build_result.proposal.id,
                policy_decision,
            )

        # 6. 只有 APPROVED Ticket 才进入事实仓库支持的 Signal 状态迁移。
        transition = self._signal_workflow.apply(
            policy_decision.ticket,
            SignalAuthorizationContext(
                watch_item_version=command.watch_item_version,
                context_digest=command.context_digest,
                trading_plan_config_version=command.trading_plan_config_version,
                position_version=command.position_version,
            ),
            correlation_id=_stage_id(command.run_id, "signal-transition"),
            occurred_at=evaluated_at,
        )
        return CryptoRunOnceResult(
            run_id=command.run_id,
            mode=command.mode,
            status=CryptoRunStatus.SIGNAL_TRANSITIONED,
            reason="POLICY_APPROVED",
            snapshot_id=snapshot.id,
            candidate_id=candidate.id,
            direction=candidate.direction,
            signal_id=transition.signal.id,
            proposal_id=build_result.proposal.id,
            policy_evaluation_id=policy_decision.evaluation.id,
            decision_ticket_id=policy_decision.ticket.id,
            signal_state=transition.signal.state,
        )

    @staticmethod
    def _no_candidate_result(
            command: CryptoRunOnceCommand,
            snapshot: MarketSnapshot,
            prefilter_result: CryptoPreFilterResult,
    ) -> CryptoRunOnceResult:
        """把 PreFilter 的稳定无候选原因映射为应用结果。"""

        return CryptoRunOnceResult(
            run_id=command.run_id,
            mode=command.mode,
            status=CryptoRunStatus.NO_CANDIDATE,
            reason=prefilter_result.reason.value,
            snapshot_id=snapshot.id,
        )

    @staticmethod
    def _policy_not_approved_result(
            command: CryptoRunOnceCommand,
            snapshot: MarketSnapshot,
            candidate_id: UUID,
            direction: Direction,
            signal_id: UUID,
            proposal_id: UUID,
            policy_decision: CryptoPolicyDecision,
    ) -> CryptoRunOnceResult:
        """保留未批准 Evaluation 身份，并明确停止 Ticket 消费。"""

        evaluation = policy_decision.evaluation
        reasons = ",".join(evaluation.reason_codes) or evaluation.outcome.value
        return CryptoRunOnceResult(
            run_id=command.run_id,
            mode=command.mode,
            status=CryptoRunStatus.POLICY_NOT_APPROVED,
            reason=reasons,
            snapshot_id=snapshot.id,
            candidate_id=candidate_id,
            direction=direction,
            signal_id=signal_id,
            proposal_id=proposal_id,
            policy_evaluation_id=evaluation.id,
            signal_state=SignalState.OBSERVING,
        )


def default_btc_usdt_instrument() -> Instrument:
    """返回 Run-Once 使用的稳定 OKX BTC-USDT 现货身份。"""

    identity = "loot:instrument:crypto:OKX:BTC-USDT:SPOT"
    return Instrument(
        instrument_id=uuid5(NAMESPACE_URL, identity),
        market=Market.CRYPTO,
        venue="OKX",
        symbol="BTC-USDT",
        instrument_type=InstrumentType.SPOT,
        quote_currency="USDT",
        timezone="UTC",
        price_scale=2,
        status=InstrumentStatus.ACTIVE,
    )


def _stage_id(run_id: UUID, stage: str) -> UUID:
    """为一次运行的持久化阶段生成稳定 correlation/request ID。"""

    return uuid5(NAMESPACE_URL, f"crypto-run-once:{run_id}:{stage}")


def _optional_uuid_text(value: UUID | None) -> str | None:
    """把可选 UUID 转换为 JSON 文本。"""

    return str(value) if value is not None else None


def _utc_now() -> datetime:
    """返回当前 UTC aware 时间，允许测试注入固定时钟。"""

    return datetime.now(UTC)
