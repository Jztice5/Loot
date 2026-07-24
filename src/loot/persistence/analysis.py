"""Crypto Analysis Inbox、Evidence 和 Proposal 原子持久化。

业务描述:
    消费一个至少一次投递的 Candidate 分析消息，并在同一事务中保存 Inbox 账本、
    EvidenceSet、DecisionProposal、有序证据引用和 Proposal Outbox。

业务场景:
    DeterministicDecisionBuilder 或未来受控 Skill Runtime 产出证据和提案后落库。

业务原因:
    消息重投和进程崩溃不能产生重复 Proposal，也不能留下 Inbox 已完成但业务事实缺失的
    中间状态。

调用链:
    Candidate consumer -> record_analysis_result -> Inbox/Evidence/Proposal/Outbox -> commit

业务规则:
    同一 consumer_name + message_id 完整 payload 一致时返回首次事实；message、Evidence
    或 Proposal 身份被不同 payload 复用时拒绝；所有读取重新执行 Pydantic 校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from loot.contracts import DecisionProposal, EvidenceSet
from loot.contracts.base import ensure_non_empty, ensure_utc_datetime
from loot.contracts.serialization import json_compatible, payload_fingerprint
from loot.persistence.locking import acquire_advisory_locks
from loot.persistence.mappers import (
    contract_from_payload,
    evidence_values,
    proposal_values,
    validate_stored_fingerprint,
)
from loot.persistence.outbox import (
    OutboxMessage,
    build_outbox_message,
    insert_outbox_message,
)
from loot.persistence.schema import (
    decision_proposal_evidence,
    decision_proposals,
    evidence_sets,
    inbox_messages,
)


class AnalysisPersistenceError(ValueError):
    """Analysis 持久化错误基类。"""


class InboxMessageConflictError(AnalysisPersistenceError):
    """同一 Inbox 消息身份被不同 payload 复用。"""


class AnalysisFactConflictError(AnalysisPersistenceError):
    """Evidence 或 Proposal 不可变身份发生 payload 冲突。"""


@dataclass(frozen=True, slots=True)
class AnalysisRecordResult:
    """Analysis 原子写入结果。"""

    evidence_sets: tuple[EvidenceSet, ...]
    proposal: DecisionProposal
    duplicate: bool


class PostgresAnalysisRepository:
    """Crypto Analysis 事务仓库。

    业务描述:
        将一个 Candidate 消费结果作为不可分割事务写入 PostgreSQL。

    业务场景:
        REQ-0008 的确定性分析链，后续 Agent/Skill 仍复用相同事实边界。

    业务原因:
        Inbox 只负责消息去重，Evidence/Proposal 唯一约束负责业务事实去重，两层都必须
        比较完整 payload 才能区分安全重试和语义冲突。

    调用链:
        claim inbox -> validate evidence order -> ensure Evidence facts
        -> ensure Proposal -> link evidence -> Outbox -> mark processed

    业务规则:
        - Proposal.evidence_refs 必须与传入 Evidence 顺序完全一致。
        - Evidence 必须绑定同一 Candidate、snapshot 和 direction。
        - 任一步失败时 Inbox RECEIVED 记录也随事务回滚。
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
    ) -> AnalysisRecordResult:
        """原子记录一个 Analysis 消费结果。

        调用链:
            normalize/validate -> advisory lock -> claim Inbox -> persist facts/refs
            -> append Proposal Outbox -> mark processed -> commit

        幂等与补偿:
            完整相同消息重投时验证并返回已存 Evidence/Proposal；事务异常整体回滚，调用方
            可按至少一次投递策略重试原消息。
        """

        normalized_consumer = ensure_non_empty(consumer_name)
        normalized_received_at = ensure_utc_datetime(received_at)
        normalized_processed_at = ensure_utc_datetime(processed_at)
        if normalized_processed_at < normalized_received_at:
            raise ValueError("processed_at must not be earlier than received_at")
        self._validate_analysis_facts(evidence, proposal)
        message_fingerprint = payload_fingerprint(message_payload)

        with self._engine.begin() as connection:
            acquire_advisory_locks(
                connection,
                f"inbox:{normalized_consumer}:{message_id}",
                f"analysis:proposal:{proposal.id}",
            )
            duplicate = self._claim_inbox(
                connection,
                consumer_name=normalized_consumer,
                message_id=message_id,
                message_fingerprint=message_fingerprint,
                received_at=normalized_received_at,
            )
            stored_evidence = tuple(
                self._ensure_evidence(connection, item) for item in evidence
            )
            stored_proposal, proposal_created = self._ensure_proposal(
                connection,
                proposal,
            )
            self._ensure_evidence_links(
                connection,
                stored_proposal,
                stored_evidence,
            )
            if proposal_created:
                insert_outbox_message(
                    connection,
                    self._proposal_outbox(stored_proposal, message_id),
                )
            connection.execute(
                sa.update(inbox_messages)
                .where(
                    inbox_messages.c.consumer_name == normalized_consumer,
                    inbox_messages.c.message_id == message_id,
                )
                .values(
                    status="PROCESSED",
                    processed_at=normalized_processed_at,
                    last_error=None,
                )
            )

        return AnalysisRecordResult(
            evidence_sets=stored_evidence,
            proposal=stored_proposal,
            duplicate=duplicate,
        )

    @staticmethod
    def _claim_inbox(
            connection: Connection,
            *,
            consumer_name: str,
            message_id: UUID,
            message_fingerprint: str,
            received_at: datetime,
    ) -> bool:
        """认领 Inbox 消息并返回是否为已完成重投。"""

        query = (
            sa.select(inbox_messages)
            .where(
                inbox_messages.c.consumer_name == consumer_name,
                inbox_messages.c.message_id == message_id,
            )
            .with_for_update()
        )
        row = connection.execute(query).mappings().one_or_none()
        if row is not None:
            if row["payload_fingerprint"] != message_fingerprint:
                raise InboxMessageConflictError(
                    "inbox message ID was reused with a different payload"
                )
            return row["status"] == "PROCESSED"

        connection.execute(
            sa.insert(inbox_messages).values(
                consumer_name=consumer_name,
                message_id=message_id,
                payload_fingerprint=message_fingerprint,
                received_at=received_at,
                status="RECEIVED",
            )
        )
        return False

    @staticmethod
    def _ensure_evidence(
            connection: Connection,
            evidence: EvidenceSet,
    ) -> EvidenceSet:
        """插入或返回完整一致的 EvidenceSet 事实。"""

        query = sa.select(evidence_sets).where(
            sa.or_(
                evidence_sets.c.id == evidence.id,
                evidence_sets.c.dedupe_key == evidence.dedupe_key,
            )
        )
        rows = connection.execute(query).mappings().all()
        if rows:
            if len(rows) != 1:
                raise AnalysisFactConflictError(
                    "evidence ID and dedupe key resolve to different facts"
                )
            stored = contract_from_payload(EvidenceSet, rows[0]["payload"])
            validate_stored_fingerprint(
                rows[0]["payload_fingerprint"],
                stored,
            )
            if stored != evidence:
                raise AnalysisFactConflictError(
                    "evidence identity already exists with a different payload"
                )
            return stored
        connection.execute(sa.insert(evidence_sets).values(**evidence_values(evidence)))
        return evidence

    @staticmethod
    def _ensure_proposal(
            connection: Connection,
            proposal: DecisionProposal,
    ) -> tuple[DecisionProposal, bool]:
        """插入或返回完整一致的 DecisionProposal 事实。"""

        query = sa.select(decision_proposals).where(
            sa.or_(
                decision_proposals.c.id == proposal.id,
                decision_proposals.c.dedupe_key == proposal.dedupe_key,
            )
        )
        rows = connection.execute(query).mappings().all()
        if rows:
            if len(rows) != 1:
                raise AnalysisFactConflictError(
                    "proposal ID and dedupe key resolve to different facts"
                )
            row = rows[0]
            stored = contract_from_payload(DecisionProposal, row["payload"])
            validate_stored_fingerprint(row["payload_fingerprint"], stored)
            if stored != proposal or row["proposal_digest"] != proposal.content_digest():
                raise AnalysisFactConflictError(
                    "proposal identity already exists with a different payload"
                )
            return stored, False
        connection.execute(
            sa.insert(decision_proposals).values(**proposal_values(proposal))
        )
        return proposal, True

    @staticmethod
    def _ensure_evidence_links(
            connection: Connection,
            proposal: DecisionProposal,
            evidence: tuple[EvidenceSet, ...],
    ) -> None:
        """确保 Proposal 到 Evidence 的有序引用与契约完全一致。"""

        query = (
            sa.select(decision_proposal_evidence)
            .where(decision_proposal_evidence.c.proposal_id == proposal.id)
            .order_by(decision_proposal_evidence.c.position)
        )
        rows = connection.execute(query).mappings().all()
        expected_ids = tuple(item.id for item in evidence)
        if rows:
            stored_ids = tuple(row["evidence_id"] for row in rows)
            if stored_ids != expected_ids:
                raise AnalysisFactConflictError(
                    "proposal evidence order differs from stored references"
                )
            return
        connection.execute(
            sa.insert(decision_proposal_evidence),
            [
                {
                    "proposal_id": proposal.id,
                    "position": position,
                    "evidence_id": item.id,
                }
                for position, item in enumerate(evidence)
            ],
        )

    @staticmethod
    def _validate_analysis_facts(
            evidence: tuple[EvidenceSet, ...],
            proposal: DecisionProposal,
    ) -> None:
        """校验 Proposal 与有序 Evidence 的来源、快照和方向绑定。"""

        if not evidence:
            raise ValueError("analysis result requires evidence")
        if proposal.evidence_refs != tuple(item.id for item in evidence):
            raise ValueError("proposal evidence_refs must match evidence order")
        if any(
                item.candidate_event_id != proposal.candidate_event_id
                or item.input_snapshot_id != proposal.input_snapshot_id
                or item.direction != proposal.direction
                or proposal.skill_versions.get(item.skill_id) != item.skill_version
                for item in evidence
        ):
            raise ValueError(
                "evidence must match proposal candidate, snapshot, direction and skill version"
            )

    @staticmethod
    def _proposal_outbox(
            proposal: DecisionProposal,
            correlation_id: UUID,
    ) -> OutboxMessage:
        event_id = uuid5(NAMESPACE_URL, f"{proposal.dedupe_key}:outbox")
        return build_outbox_message(
            event_id=event_id,
            event_type="loot.crypto.DecisionProposalRecorded",
            producer="loot.persistence.analysis",
            aggregate_type="DecisionProposal",
            aggregate_id=proposal.id,
            correlation_id=correlation_id,
            causation_id=proposal.candidate_event_id,
            partition_key=str(proposal.signal_id),
            payload={"proposal": json_compatible(proposal)},
            occurred_at=proposal.created_at,
        )
