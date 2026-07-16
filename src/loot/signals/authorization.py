"""Policy 授权事实仓库端口与 Phase 0 内存适配器。

业务描述:
    保存 DecisionProposal、PolicyEvaluation 和 DecisionTicket 的不可变授权事实，并向
    Signal State Machine 提供完整授权链查询。

业务原因:
    状态机不能信任调用方传入的 Ticket。生产环境将由 PostgreSQL 适配器实现该端口，
    Phase 0 使用内存适配器先固定唯一性、幂等和冲突语义。

调用链:
    Policy Gate -> InMemoryAuthorizationRepository.record_policy_result
    SignalStateMachine -> AuthorizationRepository.get_authorization
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from loot.contracts import (
    DecisionProposal,
    DecisionTicket,
    PolicyEvaluation,
    PolicyOutcome,
)


class AuthorizationRepositoryError(ValueError):
    """授权事实仓库错误基类。"""


class AuthorizationConflictError(AuthorizationRepositoryError):
    """不可变授权事实的 ID 或唯一业务身份发生冲突。"""


@dataclass(frozen=True, slots=True)
class AuthorizationFacts:
    """状态机一次校验需要的完整授权事实。"""

    proposal: DecisionProposal
    evaluation: PolicyEvaluation
    ticket: DecisionTicket


@dataclass(frozen=True, slots=True)
class PolicyRecordResult:
    """Policy 评估事实写入结果。"""

    evaluation: PolicyEvaluation
    ticket: DecisionTicket | None
    duplicate: bool


class AuthorizationRepository(Protocol):
    """Signal State Machine 读取授权事实的最小端口。"""

    def get_authorization(self, ticket_id: UUID) -> AuthorizationFacts | None:
        """按 Ticket ID 返回完整授权链；不存在时返回 None。"""

        ...


class PolicyAuthorizationRepository(AuthorizationRepository, Protocol):
    """Policy Gate 读写只追加授权事实所需的仓库端口。"""

    def get_evaluation_by_request(
            self,
            evaluation_request_id: UUID,
    ) -> PolicyEvaluation | None:
        """查询同一评估请求的首次事实。"""

        ...

    def get_evaluation_by_identity(
            self,
            proposal_id: UUID,
            policy_version: str,
            evaluation_context_digest: str,
    ) -> PolicyEvaluation | None:
        """查询同一 Proposal 和评估上下文的唯一事实。"""

        ...

    def get_latest_evaluation(
            self,
            proposal_id: UUID,
    ) -> PolicyEvaluation | None:
        """返回 Proposal 最近写入的评估事实。"""

        ...

    def evaluation_count(self, proposal_id: UUID) -> int:
        """返回 Proposal 已追加的评估次数。"""

        ...

    def get_ticket_by_proposal(
            self,
            proposal_id: UUID,
    ) -> DecisionTicket | None:
        """返回 Proposal 生命周期内唯一 Ticket。"""

        ...

    def record_policy_result(
            self,
            proposal: DecisionProposal,
            evaluation: PolicyEvaluation,
            ticket: DecisionTicket | None,
    ) -> PolicyRecordResult:
        """记录一次 Policy 结果并执行唯一性约束。"""

        ...


class InMemoryAuthorizationRepository:
    """Phase 0 的只追加授权事实仓库。

    业务描述:
        在单进程内模拟 Proposal、Evaluation 和 Ticket 的事实表及唯一约束。

    业务场景:
        REQ-0007 单元测试、Golden Case 和本地调试；REQ-0008 将补 PostgreSQL 事务实现。

    业务原因:
        先固定仓库端口和冲突语义，避免状态机直接相信任意构造的 Ticket。

    调用链:
        Policy Gate -> find idempotent fact -> record_policy_result
        SignalStateMachine -> get_authorization -> validate immutable chain

    业务规则:
        - evaluation_request_id 唯一。
        - proposal_id + policy_version + evaluation_context_digest 唯一。
        - 一个 Proposal 最多一张 DecisionTicket。
        - 相同 ID 的不同 payload 必须按冲突拒绝。
    """

    def __init__(self) -> None:
        self._proposals: dict[UUID, DecisionProposal] = {}
        self._evaluations: dict[UUID, PolicyEvaluation] = {}
        self._evaluation_by_request: dict[UUID, UUID] = {}
        self._evaluation_by_identity: dict[tuple[UUID, str, str], UUID] = {}
        self._evaluation_ids_by_proposal: dict[UUID, list[UUID]] = {}
        self._tickets: dict[UUID, DecisionTicket] = {}
        self._ticket_by_proposal: dict[UUID, UUID] = {}

    def get_evaluation_by_request(
            self,
            evaluation_request_id: UUID,
    ) -> PolicyEvaluation | None:
        """查询同一评估请求的首次事实。"""

        evaluation_id = self._evaluation_by_request.get(evaluation_request_id)
        return self._evaluations.get(evaluation_id) if evaluation_id else None

    def get_evaluation_by_identity(
            self,
            proposal_id: UUID,
            policy_version: str,
            evaluation_context_digest: str,
    ) -> PolicyEvaluation | None:
        """查询同一 Proposal 和评估上下文的唯一事实。"""

        evaluation_id = self._evaluation_by_identity.get(
            (proposal_id, policy_version, evaluation_context_digest)
        )
        return self._evaluations.get(evaluation_id) if evaluation_id else None

    def get_latest_evaluation(
            self,
            proposal_id: UUID,
    ) -> PolicyEvaluation | None:
        """返回 Proposal 最近写入的 PolicyEvaluation。"""

        evaluation_ids = self._evaluation_ids_by_proposal.get(proposal_id, [])
        if not evaluation_ids:
            return None
        return self._evaluations[evaluation_ids[-1]]

    def evaluation_count(self, proposal_id: UUID) -> int:
        """返回 Proposal 已追加的评估次数。"""

        return len(self._evaluation_ids_by_proposal.get(proposal_id, []))

    def get_ticket_by_proposal(
            self,
            proposal_id: UUID,
    ) -> DecisionTicket | None:
        """返回 Proposal 生命周期内唯一签发的 Ticket。"""

        ticket_id = self._ticket_by_proposal.get(proposal_id)
        return self._tickets.get(ticket_id) if ticket_id else None

    def record_policy_result(
            self,
            proposal: DecisionProposal,
            evaluation: PolicyEvaluation,
            ticket: DecisionTicket | None,
    ) -> PolicyRecordResult:
        """原子语义记录一次 Policy 结果。

        调用链:
            validate references -> check immutable identities -> append evaluation
            -> [APPROVED] append unique ticket

        幂等逻辑:
            完全相同的 evaluation_request_id 和 payload 返回首次结果；相同身份但 payload
            不同按冲突拒绝。
        """

        self._validate_references(proposal, evaluation, ticket)

        existing_proposal = self._proposals.get(proposal.id)
        if existing_proposal is not None and existing_proposal != proposal:
            raise AuthorizationConflictError(
                "proposal ID already exists with a different payload"
            )

        existing_by_request = self.get_evaluation_by_request(
            evaluation.evaluation_request_id
        )
        if existing_by_request is not None:
            if existing_by_request != evaluation:
                raise AuthorizationConflictError(
                    "evaluation_request_id already exists with a different payload"
                )
            existing_evaluation = cast(PolicyEvaluation, existing_by_request)
            return PolicyRecordResult(
                evaluation=existing_evaluation,
                ticket=self.get_ticket_by_proposal(proposal.id),
                duplicate=True,
            )

        identity = (
            proposal.id,
            evaluation.policy_version,
            evaluation.evaluation_context_digest,
        )
        existing_identity_id = self._evaluation_by_identity.get(identity)
        if existing_identity_id is not None:
            raise AuthorizationConflictError(
                "evaluation identity already exists with a different request"
            )

        if evaluation.id in self._evaluations:
            raise AuthorizationConflictError(
                "evaluation ID already exists with a different payload"
            )

        if ticket is not None:
            existing_ticket = self.get_ticket_by_proposal(proposal.id)
            if existing_ticket is not None and existing_ticket != ticket:
                raise AuthorizationConflictError(
                    "proposal already has a different decision ticket"
                )
            if ticket.id in self._tickets and self._tickets[ticket.id] != ticket:
                raise AuthorizationConflictError(
                    "decision ticket ID already exists with a different payload"
                )

        self._proposals.setdefault(proposal.id, proposal)
        self._evaluations[evaluation.id] = evaluation
        self._evaluation_by_request[evaluation.evaluation_request_id] = evaluation.id
        self._evaluation_by_identity[identity] = evaluation.id
        self._evaluation_ids_by_proposal.setdefault(proposal.id, []).append(
            evaluation.id
        )

        if ticket is not None:
            self._tickets[ticket.id] = ticket
            self._ticket_by_proposal[proposal.id] = ticket.id

        return PolicyRecordResult(
            evaluation=evaluation,
            ticket=ticket,
            duplicate=False,
        )

    def get_authorization(self, ticket_id: UUID) -> AuthorizationFacts | None:
        """按 Ticket ID 加载 Proposal、Evaluation 和 Ticket。"""

        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            return None
        proposal = self._proposals.get(ticket.proposal_id)
        evaluation = self._evaluations.get(ticket.policy_evaluation_id)
        if proposal is None or evaluation is None:
            raise AuthorizationConflictError(
                "stored decision ticket has an incomplete authorization chain"
            )
        return AuthorizationFacts(
            proposal=proposal,
            evaluation=evaluation,
            ticket=ticket,
        )

    @staticmethod
    def _validate_references(
            proposal: DecisionProposal,
            evaluation: PolicyEvaluation,
            ticket: DecisionTicket | None,
    ) -> None:
        """拒绝引用关系不一致的授权事实。"""

        proposal_digest = proposal.content_digest()
        if evaluation.proposal_id != proposal.id:
            raise AuthorizationConflictError(
                "policy evaluation does not reference the proposal"
            )
        if evaluation.proposal_digest != proposal_digest:
            raise AuthorizationConflictError(
                "policy evaluation proposal digest does not match the proposal"
            )

        if ticket is None:
            if evaluation.outcome == PolicyOutcome.APPROVED:
                raise AuthorizationConflictError(
                    "approved evaluation requires a decision ticket"
                )
            return

        if evaluation.outcome != PolicyOutcome.APPROVED:
            raise AuthorizationConflictError(
                "rejected or deferred evaluation cannot issue a decision ticket"
            )
        if ticket.proposal_id != proposal.id:
            raise AuthorizationConflictError(
                "decision ticket does not reference the proposal"
            )
        if ticket.policy_evaluation_id != evaluation.id:
            raise AuthorizationConflictError(
                "decision ticket does not reference the policy evaluation"
            )
        if ticket.policy_version != evaluation.policy_version:
            raise AuthorizationConflictError(
                "decision ticket policy version does not match the evaluation"
            )
        if ticket.proposal_digest != proposal_digest:
            raise AuthorizationConflictError(
                "decision ticket proposal digest does not match the proposal"
            )
        if ticket.issued_at != evaluation.evaluated_at:
            raise AuthorizationConflictError(
                "decision ticket issued_at does not match the evaluation"
            )
        if ticket.expires_at > evaluation.expires_at:
            raise AuthorizationConflictError(
                "decision ticket validity exceeds the evaluation"
            )
