"""Crypto Candidate 的确定性 Evidence 与 DecisionProposal 构建器。

业务描述:
    将已经通过 Crypto PreFilter 的结构突破 Candidate 转换为可回放 EvidenceSet 和
    Policy Gate 前 DecisionProposal。

业务原因:
    REQ-0007 先用确定性组件跑通授权链，不引入 Agent 或 LLM；未来替换分析方式时，
    Proposal 之后的 Policy 和 Signal 边界保持不变。

调用链:
    CandidateEvent + SignalInstance + versioned context
    -> DeterministicDecisionBuilder.build -> EvidenceSet + DecisionProposal
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from loot.contracts import (
    Actionability,
    CandidateEvent,
    CandidateType,
    DecisionProposal,
    Direction,
    EvidenceSet,
    Market,
    SignalInstance,
    SignalState,
    SignalType,
)

_BUILDER_RULE_VERSION = "crypto.structure-breakout.decision.v1"
_SKILL_ID = "crypto.deterministic.structure-breakout"
_SKILL_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class CryptoDecisionContext:
    """确定性 Decision Builder 的版本化业务上下文。

    业务描述:
        绑定 Candidate、目标 Signal 和 Policy 后续需要校验的 WatchItem、TradingPlan、
        Position 版本及业务上下文摘要。

    业务规则:
        position 只影响可操作性和提醒语义，不得改写 Candidate.direction。
    """

    candidate: CandidateEvent
    signal: SignalInstance
    watch_item_version: int
    context_digest: str
    trading_plan_config_version: int | None = None
    position_version: int | None = None
    actionability: Actionability = Actionability.WATCH_ONLY
    position_impact: str = "WATCHLIST_STRUCTURE_BREAKOUT"


@dataclass(frozen=True, slots=True)
class CryptoDecisionBuildResult:
    """确定性构建器一次执行产生的证据与提案。"""

    evidence: EvidenceSet
    proposal: DecisionProposal


class DeterministicDecisionBuilder:
    """Crypto 结构突破的确定性 Decision Builder。

    业务描述:
        把 LONG/SHORT 结构突破 Candidate 映射为 MARKET_STRUCTURE Signal 的 ARMED 提案。

    业务场景:
        Phase 0 在没有 Agent、LLM 和 Skill Runtime 时验证 Candidate 到 Policy 的契约链。

    业务原因:
        固定输入必须产生稳定 Evidence 和 Proposal identity，才能支撑重复投递与 Replay。

    调用链:
        validate Candidate/Signal identity -> build stable EvidenceSet
        -> build stable DecisionProposal -> Policy Gate

    业务规则:
        - 只接受 Crypto STRUCTURE_BREAKOUT 的 LONG 或 SHORT Candidate。
        - 只对同方向 OBSERVING MARKET_STRUCTURE Signal 提议 ARMED。
        - builder 不创建 DecisionTicket，也不修改 Signal。
    """

    @property
    def rule_version(self) -> str:
        """返回参与 Proposal identity 的确定性规则版本。"""

        return _BUILDER_RULE_VERSION

    def build(
            self,
            context: CryptoDecisionContext,
    ) -> CryptoDecisionBuildResult:
        """生成稳定 EvidenceSet 和 DecisionProposal。

        调用链:
            validate context -> derive evidence identity -> derive proposal identity
            -> return immutable build result

        幂等逻辑:
            Candidate、Signal、版本上下文和 builder 版本相同时，Evidence/Proposal ID 与
            dedupe_key 完全相同。
        """

        self._validate_context(context)
        evidence = self._build_evidence(context)
        proposal = self._build_proposal(context, evidence)
        return CryptoDecisionBuildResult(
            evidence=evidence,
            proposal=proposal,
        )

    def _build_evidence(self, context: CryptoDecisionContext) -> EvidenceSet:
        """构造直接绑定 Candidate 和方向的确定性证据。"""

        candidate = context.candidate
        signal = context.signal
        dedupe_key = ":".join(
            (
                "crypto.evidence",
                self.rule_version,
                str(candidate.id),
                candidate.direction.value,
                str(signal.id),
                str(signal.version),
                context.context_digest,
            )
        )
        return EvidenceSet(
            id=uuid5(NAMESPACE_URL, dedupe_key),
            candidate_event_id=candidate.id,
            skill_run_id=uuid5(NAMESPACE_URL, f"{dedupe_key}:skill-run"),
            skill_id=_SKILL_ID,
            skill_version=_SKILL_VERSION,
            input_snapshot_id=candidate.snapshot_id,
            direction=candidate.direction,
            quality=Decimal("1"),
            observed_at=candidate.occurred_at,
            expires_at=candidate.expires_at,
            dedupe_key=dedupe_key,
            output={
                "candidate_type": candidate.candidate_type.value,
                "trigger_reason": candidate.trigger_reason,
                "target_signal_state": SignalState.ARMED.value,
            },
        )

    def _build_proposal(
            self,
            context: CryptoDecisionContext,
            evidence: EvidenceSet,
    ) -> DecisionProposal:
        """构造绑定 Signal 与业务版本的 ARMED 提案。"""

        candidate = context.candidate
        signal = context.signal
        target_state = SignalState.ARMED
        trading_plan_version = (
            str(context.trading_plan_config_version)
            if context.trading_plan_config_version is not None
            else "none"
        )
        position_version = (
            str(context.position_version)
            if context.position_version is not None
            else "none"
        )
        dedupe_key = ":".join(
            (
                "crypto.proposal",
                self.rule_version,
                str(candidate.id),
                candidate.direction.value,
                str(signal.id),
                str(signal.version),
                target_state.value,
                str(context.watch_item_version),
                trading_plan_version,
                position_version,
                context.context_digest,
                context.actionability.value,
                context.position_impact,
            )
        )
        return DecisionProposal(
            id=uuid5(NAMESPACE_URL, dedupe_key),
            candidate_event_id=candidate.id,
            market=signal.market,
            instrument_id=signal.instrument_id,
            timeframe=signal.timeframe,
            signal_type=signal.signal_type,
            direction=candidate.direction,
            signal_id=signal.id,
            suggested_transition=target_state,
            evidence_refs=(evidence.id,),
            skill_versions={evidence.skill_id: evidence.skill_version},
            rule_version=self.rule_version,
            actionability=context.actionability,
            position_impact=context.position_impact,
            input_snapshot_id=candidate.snapshot_id,
            expected_signal_version=signal.version,
            watch_item_version=context.watch_item_version,
            trading_plan_config_version=context.trading_plan_config_version,
            position_version=context.position_version,
            context_digest=context.context_digest,
            decision_summary=(
                f"{candidate.direction.value} structure breakout is ready for ARMED"
            ),
            created_at=candidate.occurred_at,
            dedupe_key=dedupe_key,
        )

    @staticmethod
    def _validate_context(context: CryptoDecisionContext) -> None:
        """拒绝跨市场、跨身份或方向不一致的构建请求。"""

        candidate = context.candidate
        signal = context.signal
        if signal.market != Market.CRYPTO:
            raise ValueError("DeterministicDecisionBuilder only accepts CRYPTO signals")
        if candidate.candidate_type != CandidateType.STRUCTURE_BREAKOUT:
            raise ValueError("only STRUCTURE_BREAKOUT candidate is supported")
        if candidate.direction not in {Direction.LONG, Direction.SHORT}:
            raise ValueError("structure breakout direction must be LONG or SHORT")
        if signal.signal_type != SignalType.MARKET_STRUCTURE:
            raise ValueError("structure breakout requires MARKET_STRUCTURE signal")
        if signal.state != SignalState.OBSERVING:
            raise ValueError("structure breakout decision requires OBSERVING signal")
        if signal.direction != candidate.direction:
            raise ValueError("candidate direction does not match signal direction")
        if signal.watch_item_id != candidate.watch_item_id:
            raise ValueError("candidate watch item does not match signal")
        if context.watch_item_version < 0:
            raise ValueError("watch_item_version must be non-negative")
        if context.trading_plan_config_version is not None:
            if context.trading_plan_config_version < 1:
                raise ValueError("trading_plan_config_version must be positive")
        if context.position_version is not None and context.position_version < 0:
            raise ValueError("position_version must be non-negative")
