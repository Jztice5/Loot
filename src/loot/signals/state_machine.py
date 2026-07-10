"""Signal State Machine 最小运行时。

业务描述:
    控制 SignalInstance 的状态迁移，负责把已通过 Policy Gate 的 DecisionTicket
    转换为新的 Signal 投影和 SignalEvent。

业务场景:
    - Market Domain 产生 DecisionTicket 后申请信号状态迁移。
    - Alert Center 只消费状态机产出的 SignalEvent。
    - Replay 使用相同迁移表验证历史事件是否可复现。

业务原因:
    Agent 只能提出分析建议，不能直接写 Signal。状态机是信号事实变更的唯一入口。

调用链:
    DecisionTicket -> Policy Gate -> SignalStateMachine.apply
    -> SignalInstance/SignalEvent -> Alert Center

业务规则:
    - 只允许 V0.1 迁移表内的状态变化。
    - 同一个 DecisionTicket 重复消费必须返回首次结果，不产生新事件。
    - suggested_transition 等于当前状态时不产生 SignalEvent。
    - DecisionTicket 的市场、标的和周期必须与 SignalInstance 一致。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from loot.contracts import (
    Actionability,
    DecisionTicket,
    SignalEvent,
    SignalInstance,
    SignalState,
)


class SignalStateMachineError(ValueError):
    """Signal 状态机错误基类。"""


class SignalTransitionMismatchError(SignalStateMachineError):
    """DecisionTicket 与 SignalInstance 身份不一致。"""


class InvalidSignalTransitionError(SignalStateMachineError):
    """请求的 Signal 状态迁移不在合法迁移表中。"""

    def __init__(self, from_state: SignalState, to_state: SignalState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"invalid signal transition: {from_state} -> {to_state}")


class DuplicateDecisionConflictError(SignalStateMachineError):
    """相同 DecisionTicket ID 被用于不一致的信号迁移。"""


@dataclass(frozen=True, slots=True)
class SignalTransitionResult:
    """Signal 状态机迁移结果。

    业务描述:
        表达一次 DecisionTicket 消费后的结果，可能是状态变化、重复消费或无变化。

    业务规则:
        event 为 None 表示没有真实状态变化；duplicate 为 True 表示命中了内存幂等账本。
    """

    signal: SignalInstance
    event: SignalEvent | None
    decision_ticket_id: UUID
    changed: bool
    duplicate: bool = False


class SignalStateMachine:
    """Signal 状态机 V0.1。

    业务描述:
        用固定迁移表执行 SignalInstance 状态迁移，并用内存账本模拟未来数据库幂等表。

    业务场景:
        - 单元测试和 Golden Case 在没有数据库时验证状态机语义。
        - 后续 Repository 接入前，先固定合法迁移和重复消费行为。

    业务原因:
        先把状态机语义独立出来，能防止后续 Agent、Provider 或 Alert 反向影响信号事实。

    调用链:
        apply -> check_duplicate -> validate_identity -> validate_transition
        -> update_signal -> build_event -> remember_result

    业务规则:
        - 内存幂等账本只用于 Phase 0，本类不承担持久化职责。
        - 重复 DecisionTicket 返回首次 SignalTransitionResult，不再次增加 version。
        - 非法迁移抛出 InvalidSignalTransitionError。
    """

    _ALLOWED_TRANSITIONS: frozenset[tuple[SignalState, SignalState]] = frozenset(
        {
            (SignalState.OBSERVING, SignalState.ARMED),
            (SignalState.ARMED, SignalState.TRIGGERED),
            (SignalState.TRIGGERED, SignalState.CONFIRMED),
            (SignalState.TRIGGERED, SignalState.INVALIDATED),
            (SignalState.CONFIRMED, SignalState.WEAKENING),
            (SignalState.WEAKENING, SignalState.CONFIRMED),
            (SignalState.WEAKENING, SignalState.RESOLVED),
            (SignalState.OBSERVING, SignalState.EXPIRED),
            (SignalState.ARMED, SignalState.EXPIRED),
        }
    )

    def __init__(self) -> None:
        self._applied_results: dict[UUID, SignalTransitionResult] = {}

    @classmethod
    def can_transition(cls, from_state: SignalState, to_state: SignalState) -> bool:
        """判断状态迁移是否在 V0.1 合法迁移表中。"""

        return (from_state, to_state) in cls._ALLOWED_TRANSITIONS

    @classmethod
    def allowed_transitions(cls) -> frozenset[tuple[SignalState, SignalState]]:
        """返回 V0.1 合法迁移表。"""

        return cls._ALLOWED_TRANSITIONS

    def apply(
        self,
        current_signal: SignalInstance,
        decision_ticket: DecisionTicket,
        *,
        occurred_at: datetime | None = None,
        event_id: UUID | None = None,
    ) -> SignalTransitionResult:
        """应用 DecisionTicket 并返回状态机结果。

        业务点:
            Policy Gate 准入后的唯一 Signal 写入口，负责幂等、合法迁移校验和事件生成。

        调用链:
            check_duplicate -> validate_identity -> no_change_or_transition
            -> build_signal_projection -> build_signal_event

        幂等逻辑:
            使用 decision_ticket.id 作为内存去重键。重复消费返回首次结果，不生成新事件。

        Args:
            current_signal: 当前 Signal 投影。
            decision_ticket: 已通过 Policy Gate 的决策票据。
            occurred_at: 本次迁移发生时间；未传入时使用当前 UTC 时间。
            event_id: 外部指定事件 ID，便于测试和 replay 固定结果。

        Returns:
            状态机迁移结果。

        Raises:
            SignalTransitionMismatchError: 决策票据与 Signal 身份不一致。
            InvalidSignalTransitionError: 请求的状态迁移不合法。
            DuplicateDecisionConflictError: 相同票据 ID 被用于不一致迁移。
        """

        duplicate = self._applied_results.get(decision_ticket.id)
        if duplicate is not None:
            self._ensure_duplicate_is_consistent(
                duplicate,
                current_signal,
                decision_ticket,
            )
            return replace(duplicate, duplicate=True)

        self._ensure_ticket_matches_signal(current_signal, decision_ticket)

        # 决策: 相同状态不是事实变化，不能发布 SignalEvent 触发重复提醒。
        if current_signal.state == decision_ticket.suggested_transition:
            result = SignalTransitionResult(
                signal=current_signal,
                event=None,
                decision_ticket_id=decision_ticket.id,
                changed=False,
            )
            self._applied_results[decision_ticket.id] = result
            return result

        if not self.can_transition(
            current_signal.state,
            decision_ticket.suggested_transition,
        ):
            raise InvalidSignalTransitionError(
                current_signal.state,
                decision_ticket.suggested_transition,
            )

        transition_time = occurred_at or datetime.now(UTC)
        updated_signal = current_signal.model_copy(
            update={
                "state": decision_ticket.suggested_transition,
                "actionability": decision_ticket.actionability,
                "latest_decision_ticket_id": decision_ticket.id,
                "last_transition_at": transition_time,
                "version": current_signal.version + 1,
            }
        )
        event = self._build_signal_event(
            current_signal,
            updated_signal,
            decision_ticket,
            occurred_at=transition_time,
            event_id=event_id or uuid4(),
        )
        result = SignalTransitionResult(
            signal=updated_signal,
            event=event,
            decision_ticket_id=decision_ticket.id,
            changed=True,
        )
        self._applied_results[decision_ticket.id] = result
        return result

    def applied_decision_count(self) -> int:
        """返回当前内存幂等账本中已消费的 DecisionTicket 数量。"""

        return len(self._applied_results)

    @staticmethod
    def _ensure_ticket_matches_signal(
        signal: SignalInstance,
        ticket: DecisionTicket,
    ) -> None:
        # 决策: 状态机不能把其他市场、标的或周期的决策票据应用到当前 Signal。
        if (
            signal.market != ticket.market
            or signal.instrument_id != ticket.instrument_id
            or signal.timeframe != ticket.timeframe
        ):
            raise SignalTransitionMismatchError(
                "decision ticket market, instrument, or timeframe does not match signal"
            )

    @staticmethod
    def _ensure_duplicate_is_consistent(
        existing: SignalTransitionResult,
        current_signal: SignalInstance,
        decision_ticket: DecisionTicket,
    ) -> None:
        if existing.signal.id != current_signal.id:
            raise DuplicateDecisionConflictError(
                "decision ticket was already applied to a different signal"
            )

        expected_state = (
            existing.event.to_state if existing.event is not None else existing.signal.state
        )
        if expected_state != decision_ticket.suggested_transition:
            raise DuplicateDecisionConflictError(
                "decision ticket was already applied with a different target state"
            )

    @staticmethod
    def _build_signal_event(
        previous_signal: SignalInstance,
        updated_signal: SignalInstance,
        decision_ticket: DecisionTicket,
        *,
        occurred_at: datetime,
        event_id: UUID,
    ) -> SignalEvent:
        dedupe_key = (
            f"{previous_signal.dedupe_key}:"
            f"{decision_ticket.id}:"
            f"{previous_signal.state}->{updated_signal.state}"
        )
        return SignalEvent(
            event_id=event_id,
            signal_id=previous_signal.id,
            market=previous_signal.market,
            instrument_id=previous_signal.instrument_id,
            signal_type=previous_signal.signal_type,
            from_state=previous_signal.state,
            to_state=updated_signal.state,
            priority=updated_signal.priority,
            actionable_now=decision_ticket.actionability
            == Actionability.ACTIONABLE_NOW,
            position_impact=decision_ticket.position_impact,
            decision_ticket_id=decision_ticket.id,
            occurred_at=occurred_at,
            dedupe_key=dedupe_key,
        )
