"""PostgreSQL 决策授权事实仓库。

业务描述:
    持久化不可变 DecisionProposal、PolicyEvaluation 和 DecisionTicket，并向 Signal
    workflow 提供同一事务内的完整授权链查询。

业务场景:
    CryptoPolicyGate 记录审核结果；进程重启后 Signal workflow 重新验证 Ticket 来源。

业务原因:
    内存仓库无法跨进程恢复，也不能处理多实例并发。PostgreSQL 唯一约束和事务锁是授权
    事实的最终防线。

调用链:
    CryptoPolicyGate -> PostgresAuthorizationRepository.record_policy_result
    PostgresSignalWorkflow -> get_authorization_in_connection

业务规则:
    Proposal、Evaluation、Ticket 和对应 Outbox 在同一事务写入；同一请求完整 payload
    一致时返回首次事实，不一致时拒绝；APPROVED 必须且只能签发一张 Ticket。
"""

from __future__ import annotations

from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from loot.contracts import DecisionProposal, DecisionTicket, PolicyEvaluation
from loot.contracts.serialization import json_compatible
from loot.persistence.locking import acquire_advisory_locks
from loot.persistence.mappers import (
    contract_from_payload,
    evaluation_values,
    proposal_values,
    ticket_values,
    validate_stored_fingerprint,
)
from loot.persistence.outbox import (
    OutboxMessage,
    build_outbox_message,
    insert_outbox_message,
)
from loot.persistence.schema import (
    decision_proposals,
    decision_tickets,
    policy_evaluations,
)
from loot.signals.authorization import (
    AuthorizationConflictError,
    AuthorizationFacts,
    PolicyRecordResult,
    validate_authorization_references,
)


class PostgresAuthorizationRepository:
    """PostgreSQL 授权事实适配器。

    业务描述:
        实现 Policy Gate 所需的查询、追加和幂等语义，并保存可恢复的 Outbox 事实。

    业务场景:
        REQ-0008 Crypto First Vertical Slice 的生产型事实仓库。

    业务原因:
        数据库必须同时约束业务唯一身份和完整 payload，不能把 `23505` 一律当作成功。

    调用链:
        Policy Gate -> query duplicate/final state -> record_policy_result
        Signal workflow -> get_authorization_in_connection -> Pydantic validation

    业务规则:
        - evaluation_request_id 和 evaluation identity 分别唯一。
        - Proposal 生命周期最多一张 Ticket。
        - 所有 JSONB 读取重新执行契约校验并核对索引列摘要。
        - 事务 advisory lock 只串行化同一 Proposal/评估身份，不扩大到无关请求。
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_evaluation_by_request(
            self,
            evaluation_request_id: UUID,
    ) -> PolicyEvaluation | None:
        """查询同一评估请求的首次事实。"""

        with self._engine.connect() as connection:
            return self._get_evaluation_by_request(
                connection,
                evaluation_request_id,
            )

    def get_evaluation_by_identity(
            self,
            proposal_id: UUID,
            policy_version: str,
            evaluation_context_digest: str,
    ) -> PolicyEvaluation | None:
        """查询 Proposal、Policy 版本和上下文共同定义的唯一评估。"""

        query = sa.select(policy_evaluations).where(
            policy_evaluations.c.proposal_id == proposal_id,
            policy_evaluations.c.policy_version == policy_version,
            policy_evaluations.c.evaluation_context_digest
            == evaluation_context_digest,
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).mappings().one_or_none()
        return self._evaluation_from_row(row) if row is not None else None

    def get_latest_evaluation(
            self,
            proposal_id: UUID,
    ) -> PolicyEvaluation | None:
        """按评估时间和 attempt 返回 Proposal 最新追加事实。"""

        query = (
            sa.select(policy_evaluations)
            .where(policy_evaluations.c.proposal_id == proposal_id)
            .order_by(
                policy_evaluations.c.evaluated_at.desc(),
                policy_evaluations.c.attempt_number.desc(),
                policy_evaluations.c.id.desc(),
            )
            .limit(1)
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).mappings().one_or_none()
        return self._evaluation_from_row(row) if row is not None else None

    def evaluation_count(self, proposal_id: UUID) -> int:
        """返回 Proposal 已追加的 PolicyEvaluation 数量。"""

        query = sa.select(sa.func.count()).select_from(policy_evaluations).where(
            policy_evaluations.c.proposal_id == proposal_id
        )
        with self._engine.connect() as connection:
            return int(connection.execute(query).scalar_one())

    def get_ticket_by_proposal(
            self,
            proposal_id: UUID,
    ) -> DecisionTicket | None:
        """返回 Proposal 生命周期内唯一 Ticket。"""

        with self._engine.connect() as connection:
            return self._get_ticket_by_proposal(connection, proposal_id)

    def record_policy_result(
            self,
            proposal: DecisionProposal,
            evaluation: PolicyEvaluation,
            ticket: DecisionTicket | None,
    ) -> PolicyRecordResult:
        """原子追加 Policy 结果、可选 Ticket 和 Outbox。

        调用链:
            validate chain -> acquire proposal/evaluation locks -> verify/insert proposal
            -> resolve duplicate -> insert evaluation -> [APPROVED] insert ticket
            -> append Outbox -> commit

        幂等与补偿:
            同一 evaluation_request_id 且完整 Evaluation 一致时返回首次结果；事务任一步骤
            失败会整体回滚，不留下 Evaluation 已写但 Ticket 或 Outbox 缺失的中间状态。
        """

        validate_authorization_references(proposal, evaluation, ticket)
        evaluation_identity = ":".join(
            (
                str(proposal.id),
                evaluation.policy_version,
                evaluation.evaluation_context_digest,
            )
        )
        with self._engine.begin() as connection:
            acquire_advisory_locks(
                connection,
                f"authorization:proposal:{proposal.id}",
                f"authorization:evaluation:{evaluation_identity}",
                f"authorization:request:{evaluation.evaluation_request_id}",
            )
            proposal_created = self._ensure_proposal(connection, proposal)
            existing = self._get_evaluation_by_request(
                connection,
                evaluation.evaluation_request_id,
            )
            if existing is not None:
                if existing != evaluation:
                    raise AuthorizationConflictError(
                        "evaluation_request_id already exists with a different payload"
                    )
                return PolicyRecordResult(
                    evaluation=cast(PolicyEvaluation, existing),
                    ticket=self._get_ticket_by_proposal(connection, proposal.id),
                    duplicate=True,
                )

            self._reject_evaluation_conflicts(connection, evaluation)
            self._validate_attempt_number(connection, evaluation)
            connection.execute(
                sa.insert(policy_evaluations).values(**evaluation_values(evaluation))
            )
            if ticket is not None:
                self._insert_ticket(connection, ticket)

            if proposal_created:
                insert_outbox_message(
                    connection,
                    self._proposal_outbox(proposal, evaluation.evaluation_request_id),
                )
            insert_outbox_message(connection, self._evaluation_outbox(evaluation))
            if ticket is not None:
                insert_outbox_message(
                    connection,
                    self._ticket_outbox(ticket, evaluation.evaluation_request_id),
                )

        return PolicyRecordResult(
            evaluation=evaluation,
            ticket=ticket,
            duplicate=False,
        )

    def get_authorization(self, ticket_id: UUID) -> AuthorizationFacts | None:
        """按 Ticket ID 读取并校验完整授权链。"""

        with self._engine.connect() as connection:
            return self.get_authorization_in_connection(connection, ticket_id)

    def get_authorization_in_connection(
            self,
            connection: Connection,
            ticket_id: UUID,
    ) -> AuthorizationFacts | None:
        """在调用方事务内读取完整授权链，供 Signal 行锁事务复核。"""

        query = (
            sa.select(
                decision_proposals.c.payload.label("proposal_payload"),
                decision_proposals.c.payload_fingerprint.label(
                    "proposal_fingerprint"
                ),
                decision_proposals.c.proposal_digest.label("stored_proposal_digest"),
                policy_evaluations.c.payload.label("evaluation_payload"),
                policy_evaluations.c.payload_fingerprint.label(
                    "evaluation_fingerprint"
                ),
                decision_tickets.c.payload.label("ticket_payload"),
                decision_tickets.c.payload_fingerprint.label("ticket_fingerprint"),
            )
            .select_from(
                decision_tickets.join(
                    decision_proposals,
                    decision_tickets.c.proposal_id == decision_proposals.c.id,
                ).join(
                    policy_evaluations,
                    decision_tickets.c.policy_evaluation_id
                    == policy_evaluations.c.id,
                )
            )
            .where(decision_tickets.c.id == ticket_id)
        )
        row = connection.execute(query).mappings().one_or_none()
        if row is None:
            return None
        proposal = contract_from_payload(
            DecisionProposal,
            row["proposal_payload"],
        )
        evaluation = contract_from_payload(
            PolicyEvaluation,
            row["evaluation_payload"],
        )
        ticket = contract_from_payload(DecisionTicket, row["ticket_payload"])
        validate_stored_fingerprint(row["proposal_fingerprint"], proposal)
        validate_stored_fingerprint(row["evaluation_fingerprint"], evaluation)
        validate_stored_fingerprint(row["ticket_fingerprint"], ticket)
        if proposal.content_digest() != row["stored_proposal_digest"]:
            raise AuthorizationConflictError(
                "stored proposal digest differs from proposal payload"
            )
        validate_authorization_references(proposal, evaluation, ticket)
        return AuthorizationFacts(
            proposal=proposal,
            evaluation=evaluation,
            ticket=ticket,
        )

    @staticmethod
    def _ensure_proposal(
            connection: Connection,
            proposal: DecisionProposal,
    ) -> bool:
        """确保 Proposal 不可变事实存在，返回是否由本事务新建。"""

        query = sa.select(decision_proposals).where(
            sa.or_(
                decision_proposals.c.id == proposal.id,
                decision_proposals.c.dedupe_key == proposal.dedupe_key,
            )
        )
        rows = connection.execute(query).mappings().all()
        if rows:
            if len(rows) != 1:
                raise AuthorizationConflictError(
                    "proposal ID and dedupe key resolve to different facts"
                )
            stored = contract_from_payload(DecisionProposal, rows[0]["payload"])
            validate_stored_fingerprint(
                rows[0]["payload_fingerprint"],
                stored,
            )
            if stored != proposal:
                raise AuthorizationConflictError(
                    "proposal identity already exists with a different payload"
                )
            return False
        connection.execute(
            sa.insert(decision_proposals).values(**proposal_values(proposal))
        )
        return True

    @staticmethod
    def _reject_evaluation_conflicts(
            connection: Connection,
            evaluation: PolicyEvaluation,
    ) -> None:
        """拒绝除 evaluation_request 幂等外的 Evaluation 唯一身份复用。"""

        query = sa.select(policy_evaluations.c.id).where(
            sa.or_(
                policy_evaluations.c.id == evaluation.id,
                policy_evaluations.c.dedupe_key == evaluation.dedupe_key,
                sa.and_(
                    policy_evaluations.c.proposal_id == evaluation.proposal_id,
                    policy_evaluations.c.policy_version == evaluation.policy_version,
                    policy_evaluations.c.evaluation_context_digest
                    == evaluation.evaluation_context_digest,
                ),
            )
        )
        if connection.execute(query).first() is not None:
            raise AuthorizationConflictError(
                "evaluation identity already exists with a different request"
            )

    @staticmethod
    def _validate_attempt_number(
            connection: Connection,
            evaluation: PolicyEvaluation,
    ) -> None:
        """在 Proposal 事务锁内拒绝并发计算出的过期 attempt_number。"""

        query = sa.select(sa.func.count()).select_from(policy_evaluations).where(
            policy_evaluations.c.proposal_id == evaluation.proposal_id
        )
        expected_attempt = int(connection.execute(query).scalar_one()) + 1
        if evaluation.attempt_number != expected_attempt:
            raise AuthorizationConflictError(
                "policy evaluation attempt_number is stale; rebuild and retry"
            )

    @staticmethod
    def _insert_ticket(connection: Connection, ticket: DecisionTicket) -> None:
        """插入 Proposal 生命周期内唯一 Ticket，冲突时比较完整事实。"""

        query = sa.select(decision_tickets).where(
            sa.or_(
                decision_tickets.c.id == ticket.id,
                decision_tickets.c.proposal_id == ticket.proposal_id,
                decision_tickets.c.policy_evaluation_id
                == ticket.policy_evaluation_id,
                decision_tickets.c.dedupe_key == ticket.dedupe_key,
            )
        )
        rows = connection.execute(query).mappings().all()
        if rows:
            if len(rows) == 1:
                stored = contract_from_payload(DecisionTicket, rows[0]["payload"])
                validate_stored_fingerprint(
                    rows[0]["payload_fingerprint"],
                    stored,
                )
                if stored == ticket:
                    return
            raise AuthorizationConflictError(
                "decision ticket identity already exists with a different payload"
            )
        connection.execute(sa.insert(decision_tickets).values(**ticket_values(ticket)))

    @staticmethod
    def _get_evaluation_by_request(
            connection: Connection,
            evaluation_request_id: UUID,
    ) -> PolicyEvaluation | None:
        query = sa.select(policy_evaluations).where(
            policy_evaluations.c.evaluation_request_id == evaluation_request_id
        )
        row = connection.execute(query).mappings().one_or_none()
        return (
            PostgresAuthorizationRepository._evaluation_from_row(row)
            if row is not None
            else None
        )

    @staticmethod
    def _get_ticket_by_proposal(
            connection: Connection,
            proposal_id: UUID,
    ) -> DecisionTicket | None:
        query = sa.select(decision_tickets).where(
            decision_tickets.c.proposal_id == proposal_id
        )
        row = connection.execute(query).mappings().one_or_none()
        return (
            PostgresAuthorizationRepository._ticket_from_row(row)
            if row is not None
            else None
        )

    @staticmethod
    def _evaluation_from_row(row: sa.RowMapping) -> PolicyEvaluation:
        evaluation = contract_from_payload(PolicyEvaluation, row["payload"])
        validate_stored_fingerprint(row["payload_fingerprint"], evaluation)
        if evaluation.proposal_digest != row["proposal_digest"]:
            raise AuthorizationConflictError(
                "evaluation indexed digest differs from payload"
            )
        return evaluation

    @staticmethod
    def _ticket_from_row(row: sa.RowMapping) -> DecisionTicket:
        ticket = contract_from_payload(DecisionTicket, row["payload"])
        validate_stored_fingerprint(row["payload_fingerprint"], ticket)
        return ticket

    @staticmethod
    def _proposal_outbox(
            proposal: DecisionProposal,
            correlation_id: UUID,
    ) -> OutboxMessage:
        event_id = uuid5(NAMESPACE_URL, f"{proposal.dedupe_key}:outbox")
        return build_outbox_message(
            event_id=event_id,
            event_type="loot.crypto.DecisionProposalRecorded",
            producer="loot.persistence.authorization",
            aggregate_type="DecisionProposal",
            aggregate_id=proposal.id,
            correlation_id=correlation_id,
            causation_id=proposal.candidate_event_id,
            partition_key=str(proposal.signal_id),
            payload={"proposal": json_compatible(proposal)},
            occurred_at=proposal.created_at,
        )

    @staticmethod
    def _evaluation_outbox(evaluation: PolicyEvaluation) -> OutboxMessage:
        event_id = uuid5(NAMESPACE_URL, f"{evaluation.dedupe_key}:outbox")
        return build_outbox_message(
            event_id=event_id,
            event_type="loot.crypto.PolicyEvaluationRecorded",
            producer="loot.persistence.authorization",
            aggregate_type="PolicyEvaluation",
            aggregate_id=evaluation.id,
            correlation_id=evaluation.evaluation_request_id,
            causation_id=evaluation.proposal_id,
            partition_key=str(evaluation.proposal_id),
            payload={"evaluation": json_compatible(evaluation)},
            occurred_at=evaluation.evaluated_at,
        )

    @staticmethod
    def _ticket_outbox(
            ticket: DecisionTicket,
            correlation_id: UUID,
    ) -> OutboxMessage:
        event_id = uuid5(NAMESPACE_URL, f"{ticket.dedupe_key}:outbox")
        return build_outbox_message(
            event_id=event_id,
            event_type="loot.crypto.DecisionTicketIssued",
            producer="loot.persistence.authorization",
            aggregate_type="DecisionTicket",
            aggregate_id=ticket.id,
            correlation_id=correlation_id,
            causation_id=ticket.policy_evaluation_id,
            partition_key=str(ticket.signal_id),
            payload={"ticket": json_compatible(ticket)},
            occurred_at=ticket.issued_at,
        )
