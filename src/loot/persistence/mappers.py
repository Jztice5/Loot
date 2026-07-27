"""Loot 契约与 PostgreSQL 行之间的显式映射。

业务描述:
    为决策授权链的契约生成可索引列和完整 JSONB payload，并在读取时重新执行 Pydantic
    契约校验。

业务原因:
    数据库列服务于约束和查询，JSONB 保存完整事实；任何一侧都不能静默替代另一侧。

调用链:
    Repository -> contract_to_*_values -> SQLAlchemy Core
    SQLAlchemy Row -> contract_from_payload -> Pydantic validation
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from loot.contracts import (
    DecisionProposal,
    DecisionTicket,
    EvidenceSet,
    Instrument,
    MonitoringSubscription,
    PolicyEvaluation,
    SignalInstance,
    WatchItem,
)
from loot.contracts.serialization import json_compatible, payload_fingerprint

_ContractT = TypeVar("_ContractT", bound=BaseModel)


class StoredPayloadConflictError(ValueError):
    """数据库保存的 payload 与 canonical 指纹不一致。"""


def contract_from_payload(model_type: type[_ContractT], payload: Any) -> _ContractT:
    """从 JSONB payload 重建并完整校验领域契约。"""

    return model_type.model_validate(payload)


def validate_stored_fingerprint(
        stored_fingerprint: str,
        contract: BaseModel,
) -> None:
    """核对不可变 JSONB payload 与写入时保存的 canonical 指纹。"""

    if stored_fingerprint != payload_fingerprint(contract):
        raise StoredPayloadConflictError(
            "stored payload fingerprint differs from validated contract"
        )


def evidence_values(evidence: EvidenceSet) -> dict[str, Any]:
    """生成 EvidenceSet 的数据库列值。"""

    return {
        "id": evidence.id,
        "candidate_event_id": evidence.candidate_event_id,
        "skill_run_id": evidence.skill_run_id,
        "skill_id": evidence.skill_id,
        "skill_version": evidence.skill_version,
        "input_snapshot_id": evidence.input_snapshot_id,
        "direction": evidence.direction.value,
        "quality": evidence.quality,
        "observed_at": evidence.observed_at,
        "expires_at": evidence.expires_at,
        "dedupe_key": evidence.dedupe_key,
        "payload_fingerprint": payload_fingerprint(evidence),
        "payload": json_compatible(evidence),
    }


def instrument_values(instrument: Instrument) -> dict[str, Any]:
    """生成不可变 Instrument 事实的数据库列值。"""

    return {
        "instrument_id": instrument.instrument_id,
        "market": instrument.market.value,
        "venue": instrument.venue,
        "symbol": instrument.symbol,
        "instrument_type": instrument.instrument_type.value,
        "quote_currency": instrument.quote_currency,
        "timezone": instrument.timezone,
        "price_scale": instrument.price_scale,
        "status": instrument.status.value,
        "payload_fingerprint": payload_fingerprint(instrument),
        "payload": json_compatible(instrument),
    }


def watch_item_values(watch_item: WatchItem) -> dict[str, Any]:
    """生成 WatchItem 当前投影的数据库列值。"""

    return {
        "id": watch_item.id,
        "user_id": watch_item.user_id,
        "instrument_id": watch_item.instrument_id,
        "market": watch_item.market.value,
        "venue": watch_item.venue,
        "status": watch_item.status.value,
        "monitoring_profile": watch_item.monitoring_profile,
        "priority": watch_item.priority.value,
        "created_at": watch_item.created_at,
        "updated_at": watch_item.updated_at,
        "version": watch_item.version,
        "payload": json_compatible(watch_item),
    }


def subscription_values(
        subscription: MonitoringSubscription,
) -> dict[str, Any]:
    """生成 MonitoringSubscription 当前投影的数据库列值。"""

    return {
        "id": subscription.id,
        "watch_item_id": subscription.watch_item_id,
        "market": subscription.market.value,
        "instrument_id": subscription.instrument_id,
        "timeframe": subscription.timeframe.value,
        "route_key": subscription.route_key,
        "next_run_at": subscription.next_run_at,
        "status": subscription.status.value,
        "config_version": subscription.config_version,
        "created_at": subscription.created_at,
        "updated_at": subscription.updated_at,
        "payload": json_compatible(subscription),
    }


def proposal_values(proposal: DecisionProposal) -> dict[str, Any]:
    """生成 DecisionProposal 的数据库列值。"""

    return {
        "id": proposal.id,
        "candidate_event_id": proposal.candidate_event_id,
        "market": proposal.market.value,
        "instrument_id": proposal.instrument_id,
        "timeframe": proposal.timeframe.value,
        "signal_type": proposal.signal_type.value,
        "direction": proposal.direction.value,
        "signal_id": proposal.signal_id,
        "suggested_transition": proposal.suggested_transition.value,
        "rule_version": proposal.rule_version,
        "input_snapshot_id": proposal.input_snapshot_id,
        "expected_signal_version": proposal.expected_signal_version,
        "watch_item_version": proposal.watch_item_version,
        "trading_plan_config_version": proposal.trading_plan_config_version,
        "position_version": proposal.position_version,
        "context_digest": proposal.context_digest,
        "proposal_digest": proposal.content_digest(),
        "created_at": proposal.created_at,
        "dedupe_key": proposal.dedupe_key,
        "payload_fingerprint": payload_fingerprint(proposal),
        "payload": json_compatible(proposal),
    }


def evaluation_values(evaluation: PolicyEvaluation) -> dict[str, Any]:
    """生成 PolicyEvaluation 的数据库列值。"""

    return {
        "id": evaluation.id,
        "evaluation_request_id": evaluation.evaluation_request_id,
        "proposal_id": evaluation.proposal_id,
        "outcome": evaluation.outcome.value,
        "policy_version": evaluation.policy_version,
        "proposal_digest": evaluation.proposal_digest,
        "evaluation_context_digest": evaluation.evaluation_context_digest,
        "attempt_number": evaluation.attempt_number,
        "evaluated_at": evaluation.evaluated_at,
        "expires_at": evaluation.expires_at,
        "next_check_at": evaluation.next_check_at,
        "dedupe_key": evaluation.dedupe_key,
        "payload_fingerprint": payload_fingerprint(evaluation),
        "payload": json_compatible(evaluation),
    }


def ticket_values(ticket: DecisionTicket) -> dict[str, Any]:
    """生成 DecisionTicket 的数据库列值。"""

    return {
        "id": ticket.id,
        "proposal_id": ticket.proposal_id,
        "policy_evaluation_id": ticket.policy_evaluation_id,
        "policy_version": ticket.policy_version,
        "proposal_digest": ticket.proposal_digest,
        "market": ticket.market.value,
        "instrument_id": ticket.instrument_id,
        "timeframe": ticket.timeframe.value,
        "direction": ticket.direction.value,
        "signal_id": ticket.signal_id,
        "authorized_transition": ticket.authorized_transition.value,
        "input_snapshot_id": ticket.input_snapshot_id,
        "expected_signal_version": ticket.expected_signal_version,
        "watch_item_version": ticket.watch_item_version,
        "trading_plan_config_version": ticket.trading_plan_config_version,
        "position_version": ticket.position_version,
        "context_digest": ticket.context_digest,
        "issued_at": ticket.issued_at,
        "expires_at": ticket.expires_at,
        "dedupe_key": ticket.dedupe_key,
        "payload_fingerprint": payload_fingerprint(ticket),
        "payload": json_compatible(ticket),
    }


def signal_values(signal: SignalInstance) -> dict[str, Any]:
    """生成 SignalInstance 当前投影的数据库列值。"""

    return {
        "id": signal.id,
        "watch_item_id": signal.watch_item_id,
        "position_id": signal.position_id,
        "market": signal.market.value,
        "instrument_id": signal.instrument_id,
        "timeframe": signal.timeframe.value,
        "signal_type": signal.signal_type.value,
        "direction": signal.direction.value,
        "state": signal.state.value,
        "priority": signal.priority.value,
        "actionability": signal.actionability.value,
        "generation": signal.generation,
        "setup_key": signal.setup_key,
        "latest_decision_ticket_id": signal.latest_decision_ticket_id,
        "dedupe_key": signal.dedupe_key,
        "last_transition_at": signal.last_transition_at,
        "expires_at": signal.expires_at,
        "version": signal.version,
        "payload": json_compatible(signal),
    }
