"""Crypto 最小 Policy Gate。

业务描述:
    审核 Crypto DecisionProposal 的证据、Signal 身份、方向和业务上下文版本，始终生成
    PolicyEvaluation，并仅在 APPROVED 时签发 DecisionTicket。

业务原因:
    Policy 是分析建议与 Signal 事实之间不可绕过的授权边界。V0.1 只实现 REQ-0007
    所需 Guard，不提前引入完整 Guard 框架。

调用链:
    DecisionProposal + Evidence + current context -> CryptoPolicyGate.evaluate
    -> PolicyEvaluation -> [APPROVED] DecisionTicket -> AuthorizationRepository
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from loot.contracts import (
    DecisionProposal,
    DecisionTicket,
    EvidenceSet,
    Market,
    PolicyEvaluation,
    PolicyGuardResult,
    PolicyOutcome,
    SignalInstance,
)
from loot.contracts.base import ensure_utc_datetime
from loot.signals.authorization import (
    PolicyAuthorizationRepository,
)

_POLICY_VERSION = "crypto.signal-authorization.v1"


class CryptoPolicyError(ValueError):
    """Crypto Policy Gate 错误基类。"""


class PolicyEvaluationConflictError(CryptoPolicyError):
    """同一 evaluation_request_id 被用于不同评估输入。"""


class ProposalEvaluationFinalizedError(CryptoPolicyError):
    """已终结 Proposal 被再次请求评估。"""


class PolicyReevaluationNotReadyError(CryptoPolicyError):
    """DEFERRED Proposal 尚未到允许重评的时间且上下文没有改善。"""


@dataclass(frozen=True, slots=True)
class CryptoPolicyEvaluationRequest:
    """Crypto Policy Gate 的完整评估输入。

    业务描述:
        提供 Proposal、证据、当前 Signal、当前业务版本和数据可用性，供 Policy 生成
        可审计且可幂等的评估事实。

    业务规则:
        current_context_digest 和各版本代表评估时事实；DEFERRED 场景必须提供未来的
        defer_until；authorization_expires_at 限定 Evaluation 和 Ticket 的最长有效期。
    """

    evaluation_request_id: UUID
    proposal: DecisionProposal
    evidence_sets: tuple[EvidenceSet, ...]
    signal: SignalInstance
    current_context_digest: str
    watch_item_version: int
    trading_plan_config_version: int | None
    position_version: int | None
    evaluated_at: datetime
    authorization_expires_at: datetime
    data_quality_ready: bool = True
    market_rule_allows: bool = True
    defer_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class CryptoPolicyDecision:
    """Policy Gate 返回的 Evaluation、可选 Ticket 和幂等标记。"""

    evaluation: PolicyEvaluation
    ticket: DecisionTicket | None
    duplicate: bool = False


class CryptoPolicyGate:
    """Crypto 决策授权的最小 Policy Gate。

    业务描述:
        校验 Proposal 的来源事实和当前上下文，记录三态 PolicyEvaluation，并在批准时
        签发唯一 DecisionTicket。

    业务场景:
        Crypto Candidate 完成确定性分析后，在调用 Signal State Machine 前执行准入。

    业务原因:
        Policy 不得改写 direction 或目标状态；需要改变 Proposal 语义时必须重新建提案。

    调用链:
        idempotency lookup -> validate current facts -> evaluate guards
        -> append PolicyEvaluation -> [APPROVED] issue unique DecisionTicket

    业务规则:
        - 每次有效评估都产生 PolicyEvaluation。
        - REJECTED/DEFERRED 不签发 Ticket。
        - DEFERRED 在到期或数据上下文改善后可以追加评估。
        - 同一 Proposal 整个生命周期最多签发一张 Ticket。
    """

    def __init__(self, repository: PolicyAuthorizationRepository) -> None:
        self._repository = repository

    @property
    def policy_version(self) -> str:
        """返回参与评估和 Ticket identity 的 Policy 版本。"""

        return _POLICY_VERSION

    def evaluate(
            self,
            request: CryptoPolicyEvaluationRequest,
    ) -> CryptoPolicyDecision:
        """评估 Proposal，并记录 Evaluation 与可选 Ticket。

        调用链:
            normalize times -> calculate evaluation context -> idempotency/finality check
            -> evaluate guards -> build evaluation -> [APPROVED] build ticket -> record

        幂等逻辑:
            同一 evaluation_request_id 或相同 Proposal/Policy/evaluation context 返回首次
            事实；请求 ID 对应不同上下文时拒绝，避免把两个审核解释成一次重试。
        """

        evaluated_at = ensure_utc_datetime(request.evaluated_at)
        authorization_expires_at = ensure_utc_datetime(
            request.authorization_expires_at
        )
        defer_until = (
            ensure_utc_datetime(request.defer_until)
            if request.defer_until is not None
            else None
        )
        self._validate_request_times(
            evaluated_at,
            authorization_expires_at,
            data_quality_ready=request.data_quality_ready,
            defer_until=defer_until,
        )

        proposal_digest = request.proposal.content_digest()
        evaluation_context_digest = self._evaluation_context_digest(
            request,
            proposal_digest=proposal_digest,
            evaluated_at=evaluated_at,
            authorization_expires_at=authorization_expires_at,
            defer_until=defer_until,
        )
        duplicate = self._find_duplicate(
            request,
            proposal_digest=proposal_digest,
            evaluation_context_digest=evaluation_context_digest,
        )
        if duplicate is not None:
            return duplicate

        finalized = self._resolve_finalized_proposal(request, evaluated_at)
        if finalized is not None:
            return finalized
        guard_results, outcome, reason_codes = self._evaluate_guards(
            request,
            evaluated_at=evaluated_at,
        )
        attempt_number = self._repository.evaluation_count(request.proposal.id) + 1
        evaluation = self._build_evaluation(
            request,
            outcome=outcome,
            reason_codes=reason_codes,
            guard_results=guard_results,
            proposal_digest=proposal_digest,
            evaluation_context_digest=evaluation_context_digest,
            attempt_number=attempt_number,
            evaluated_at=evaluated_at,
            expires_at=authorization_expires_at,
            next_check_at=defer_until if outcome == PolicyOutcome.DEFERRED else None,
        )
        ticket = (
            self._build_ticket(
                request.proposal,
                evaluation,
                evidence_sets=request.evidence_sets,
            )
            if outcome == PolicyOutcome.APPROVED
            else None
        )
        recorded = self._repository.record_policy_result(
            request.proposal,
            evaluation,
            ticket,
        )
        return CryptoPolicyDecision(
            evaluation=recorded.evaluation,
            ticket=recorded.ticket,
            duplicate=bool(recorded.duplicate),
        )

    def _find_duplicate(
            self,
            request: CryptoPolicyEvaluationRequest,
            *,
            proposal_digest: str,
            evaluation_context_digest: str,
    ) -> CryptoPolicyDecision | None:
        """返回同一请求或同一评估事实的首次结果。"""

        existing_request = self._repository.get_evaluation_by_request(
            request.evaluation_request_id
        )
        if existing_request is not None:
            if (
                    existing_request.proposal_id != request.proposal.id
                    or existing_request.policy_version != self.policy_version
                    or existing_request.proposal_digest != proposal_digest
                    or existing_request.evaluation_context_digest
                    != evaluation_context_digest
            ):
                raise PolicyEvaluationConflictError(
                    "evaluation_request_id was reused with different input"
                )
            return CryptoPolicyDecision(
                evaluation=existing_request,
                ticket=self._repository.get_ticket_by_proposal(request.proposal.id),
                duplicate=True,
            )

        existing_identity = self._repository.get_evaluation_by_identity(
            request.proposal.id,
            self.policy_version,
            evaluation_context_digest,
        )
        if existing_identity is None:
            return None
        return CryptoPolicyDecision(
            evaluation=existing_identity,
            ticket=self._repository.get_ticket_by_proposal(request.proposal.id),
            duplicate=True,
        )

    def _resolve_finalized_proposal(
            self,
            request: CryptoPolicyEvaluationRequest,
            evaluated_at: datetime,
    ) -> CryptoPolicyDecision | None:
        """返回已批准结果，并只允许 DEFERRED Proposal 进入新评估。"""

        latest = self._repository.get_latest_evaluation(request.proposal.id)
        if latest is None:
            return None
        if latest.proposal_digest != request.proposal.content_digest():
            raise PolicyEvaluationConflictError(
                "proposal ID was reused with a different payload"
            )
        if latest.outcome == PolicyOutcome.APPROVED:
            return CryptoPolicyDecision(
                evaluation=latest,
                ticket=self._repository.get_ticket_by_proposal(request.proposal.id),
                duplicate=True,
            )
        if latest.outcome == PolicyOutcome.REJECTED:
            raise ProposalEvaluationFinalizedError(
                "rejected proposal requires a new DecisionProposal"
            )
        if (
                latest.next_check_at is not None
                and evaluated_at < latest.next_check_at
                and not request.data_quality_ready
                and request.current_context_digest == request.proposal.context_digest
                and request.watch_item_version == request.proposal.watch_item_version
                and request.trading_plan_config_version
                == request.proposal.trading_plan_config_version
                and request.position_version == request.proposal.position_version
        ):
            raise PolicyReevaluationNotReadyError(
                "deferred proposal is not ready for reevaluation"
            )
        return None

    def _evaluate_guards(
            self,
            request: CryptoPolicyEvaluationRequest,
            *,
            evaluated_at: datetime,
    ) -> tuple[
        tuple[PolicyGuardResult, ...],
        PolicyOutcome,
        tuple[str, ...],
    ]:
        """运行 REQ-0007 所需的最小结构化 Guard 集。"""

        proposal = request.proposal
        signal = request.signal
        evidence_by_id = {evidence.id: evidence for evidence in request.evidence_sets}

        identity_matches = (
                proposal.market == Market.CRYPTO
                and signal.id == proposal.signal_id
                and signal.market == proposal.market
                and signal.instrument_id == proposal.instrument_id
                and signal.timeframe == proposal.timeframe
                and signal.signal_type == proposal.signal_type
        )
        direction_matches = signal.direction == proposal.direction and all(
            evidence.direction == proposal.direction
            for evidence in request.evidence_sets
        )
        version_matches = (
                signal.version == proposal.expected_signal_version
                and request.watch_item_version == proposal.watch_item_version
                and request.trading_plan_config_version
                == proposal.trading_plan_config_version
                and request.position_version == proposal.position_version
        )
        context_matches = request.current_context_digest == proposal.context_digest
        evidence_matches = all(
            evidence_id in evidence_by_id
            and evidence_by_id[evidence_id].candidate_event_id
            == proposal.candidate_event_id
            and evidence_by_id[evidence_id].input_snapshot_id
            == proposal.input_snapshot_id
            and evidence_by_id[evidence_id].expires_at > evaluated_at
            and proposal.skill_versions.get(evidence_by_id[evidence_id].skill_id)
            == evidence_by_id[evidence_id].skill_version
            for evidence_id in proposal.evidence_refs
        )

        guard_results = (
            self._guard("crypto.identity", identity_matches, "IDENTITY_MISMATCH"),
            self._guard("crypto.direction", direction_matches, "DIRECTION_MISMATCH"),
            self._guard("context.versions", version_matches, "VERSION_CONFLICT"),
            self._guard("context.digest", context_matches, "CONTEXT_CONFLICT"),
            self._guard("evidence.validity", evidence_matches, "EVIDENCE_INVALID"),
            self._guard(
                "data.quality",
                request.data_quality_ready,
                "DATA_QUALITY_NOT_READY",
            ),
            self._guard(
                "crypto.market_rule",
                request.market_rule_allows,
                "MARKET_RULE_REJECTED",
            ),
        )
        hard_failure_ids = {
            "crypto.identity",
            "crypto.direction",
            "context.versions",
            "context.digest",
            "evidence.validity",
            "crypto.market_rule",
        }
        hard_failures = tuple(
            guard.reason_code
            for guard in guard_results
            if not guard.passed and guard.guard_id in hard_failure_ids
        )
        if hard_failures:
            return guard_results, PolicyOutcome.REJECTED, hard_failures
        if not request.data_quality_ready:
            return (
                guard_results,
                PolicyOutcome.DEFERRED,
                ("DATA_QUALITY_NOT_READY",),
            )
        return guard_results, PolicyOutcome.APPROVED, ()

    @staticmethod
    def _guard(
            guard_id: str,
            passed: bool,
            failure_reason: str,
    ) -> PolicyGuardResult:
        """构造稳定 Guard 结果，成功时统一使用 PASS 原因码。"""

        return PolicyGuardResult(
            guard_id=guard_id,
            passed=passed,
            reason_code="PASS" if passed else failure_reason,
        )

    def _build_evaluation(
            self,
            request: CryptoPolicyEvaluationRequest,
            *,
            outcome: PolicyOutcome,
            reason_codes: tuple[str, ...],
            guard_results: tuple[PolicyGuardResult, ...],
            proposal_digest: str,
            evaluation_context_digest: str,
            attempt_number: int,
            evaluated_at: datetime,
            expires_at: datetime,
            next_check_at: datetime | None,
    ) -> PolicyEvaluation:
        """构造只追加 PolicyEvaluation 事实。"""

        dedupe_key = ":".join(
            (
                "crypto.policy-evaluation",
                str(request.proposal.id),
                self.policy_version,
                evaluation_context_digest,
            )
        )
        return PolicyEvaluation(
            id=uuid5(NAMESPACE_URL, dedupe_key),
            evaluation_request_id=request.evaluation_request_id,
            proposal_id=request.proposal.id,
            outcome=outcome,
            policy_version=self.policy_version,
            proposal_digest=proposal_digest,
            evaluation_context_digest=evaluation_context_digest,
            attempt_number=attempt_number,
            guard_results=guard_results,
            reason_codes=reason_codes,
            evaluated_at=evaluated_at,
            expires_at=expires_at,
            next_check_at=next_check_at,
            dedupe_key=dedupe_key,
        )

    @staticmethod
    def _build_ticket(
            proposal: DecisionProposal,
            evaluation: PolicyEvaluation,
            *,
            evidence_sets: tuple[EvidenceSet, ...],
    ) -> DecisionTicket:
        """从 APPROVED Evaluation 签发唯一有限期 Ticket。"""

        evidence_expiry = min(evidence.expires_at for evidence in evidence_sets)
        expires_at = min(evaluation.expires_at, evidence_expiry)
        dedupe_key = ":".join(
            (
                "crypto.decision-ticket",
                str(proposal.id),
                str(evaluation.id),
                evaluation.proposal_digest,
            )
        )
        return DecisionTicket(
            id=uuid5(NAMESPACE_URL, dedupe_key),
            proposal_id=proposal.id,
            policy_evaluation_id=evaluation.id,
            policy_version=evaluation.policy_version,
            proposal_digest=evaluation.proposal_digest,
            market=proposal.market,
            instrument_id=proposal.instrument_id,
            timeframe=proposal.timeframe,
            direction=proposal.direction,
            signal_id=proposal.signal_id,
            authorized_transition=proposal.suggested_transition,
            actionability=proposal.actionability,
            position_impact=proposal.position_impact,
            input_snapshot_id=proposal.input_snapshot_id,
            expected_signal_version=proposal.expected_signal_version,
            watch_item_version=proposal.watch_item_version,
            trading_plan_config_version=proposal.trading_plan_config_version,
            position_version=proposal.position_version,
            context_digest=proposal.context_digest,
            issued_at=evaluation.evaluated_at,
            expires_at=expires_at,
            dedupe_key=dedupe_key,
        )

    def _evaluation_context_digest(
            self,
            request: CryptoPolicyEvaluationRequest,
            *,
            proposal_digest: str,
            evaluated_at: datetime,
            authorization_expires_at: datetime,
            defer_until: datetime | None,
    ) -> str:
        """计算绑定 Policy 输入、版本和评估时间窗口的摘要。"""

        evidence_payload = sorted(
            (
                evidence.id.hex,
                evidence.dedupe_key,
                evidence.expires_at.isoformat(),
            )
            for evidence in request.evidence_sets
        )
        payload = {
            "proposal_digest": proposal_digest,
            "policy_version": self.policy_version,
            "signal_id": request.signal.id.hex,
            "signal_version": request.signal.version,
            "signal_direction": request.signal.direction.value,
            "current_context_digest": request.current_context_digest,
            "watch_item_version": request.watch_item_version,
            "trading_plan_config_version": request.trading_plan_config_version,
            "position_version": request.position_version,
            "evidence": evidence_payload,
            "data_quality_ready": request.data_quality_ready,
            "market_rule_allows": request.market_rule_allows,
            "evaluated_at": evaluated_at.isoformat(),
            "authorization_expires_at": authorization_expires_at.isoformat(),
            "defer_until": defer_until.isoformat() if defer_until else None,
        }
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_request_times(
            evaluated_at: datetime,
            authorization_expires_at: datetime,
            *,
            data_quality_ready: bool,
            defer_until: datetime | None,
    ) -> None:
        """校验 Evaluation/Ticket 有效期和 DEFERRED 调度时间。"""

        if authorization_expires_at <= evaluated_at:
            raise ValueError(
                "authorization_expires_at must be later than evaluated_at"
            )
        if not data_quality_ready:
            if defer_until is None:
                raise ValueError("data quality deferral requires defer_until")
            if not evaluated_at < defer_until <= authorization_expires_at:
                raise ValueError(
                    "defer_until must be after evaluated_at and not after authorization expiry"
                )
