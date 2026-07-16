"""带授权事实校验的 Signal State Machine 最小运行时。

业务描述:
    幂等初始化 OBSERVING Signal，并把 Policy Gate 已授权的 DecisionTicket 转换为新的
    Signal 投影和 SignalEvent。

业务原因:
    Signal State Machine 是信号事实的唯一写入口。它必须从事实仓库验证完整授权链，
    不能信任调用方传入的 Ticket，也不能让 Agent、Skill 或 Policy 直接写 Signal。

调用链:
    Monitoring lifecycle -> initialize -> OBSERVING SignalInstance
    DecisionTicket -> AuthorizationRepository -> apply -> SignalInstance/SignalEvent
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from loot.contracts import (
    Actionability,
    DecisionProposal,
    DecisionTicket,
    Direction,
    Market,
    PolicyEvaluation,
    PolicyOutcome,
    Priority,
    SignalEvent,
    SignalInstance,
    SignalState,
    SignalType,
    Timeframe,
)
from loot.contracts.base import ensure_non_empty, ensure_utc_datetime
from loot.signals.authorization import (
    AuthorizationFacts,
    AuthorizationRepository,
)


class SignalStateMachineError(ValueError):
    """Signal 状态机错误基类。"""


class SignalTransitionMismatchError(SignalStateMachineError):
    """授权链与目标 Signal 身份或方向不一致。"""


class InvalidSignalTransitionError(SignalStateMachineError):
    """请求的 Signal 状态迁移不在合法迁移表中。"""

    def __init__(self, from_state: SignalState, to_state: SignalState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"invalid signal transition: {from_state} -> {to_state}")


class DuplicateDecisionConflictError(SignalStateMachineError):
    """相同 DecisionTicket ID 被用于不一致的信号迁移。"""


class ExpiredSignalTransitionError(SignalStateMachineError):
    """迁移时间晚于 Signal 当前有效期。"""


class SignalTransitionTimeError(SignalStateMachineError):
    """迁移时间早于 Signal 最后迁移时间。"""


class SignalInitializationConflictError(SignalStateMachineError):
    """同一监控身份仍有活跃 Signal，不能初始化新 setup。"""


class SignalProjectionConflictError(SignalStateMachineError):
    """调用方提供的 Signal 不是状态机当前事实投影。"""


class UntrustedDecisionTicketError(SignalStateMachineError):
    """Ticket 不存在于授权事实仓库或与仓库事实不一致。"""


class InvalidAuthorizationChainError(SignalStateMachineError):
    """Proposal、PolicyEvaluation 与 Ticket 授权链不一致。"""


class ExpiredDecisionTicketError(SignalStateMachineError):
    """Ticket 尚未生效、已过期或对应 Evaluation 已过期。"""


class SignalVersionConflictError(SignalStateMachineError):
    """Ticket 绑定的 expected_signal_version 已经过期。"""


class SignalContextConflictError(SignalStateMachineError):
    """Ticket 绑定的业务上下文版本或摘要已经变化。"""


@dataclass(frozen=True, slots=True)
class SignalInitializationRequest:
    """状态机初始化一个 OBSERVING Signal 所需的监控事实。

    业务规则:
        setup_key 标识本轮市场结构；同一监控身份存在非终态 Signal 时不能用新 setup_key
        初始化，终态后新 setup 自动递增 generation。
    """

    watch_item_id: UUID
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    signal_type: SignalType
    direction: Direction
    priority: Priority
    actionability: Actionability
    setup_key: str
    initialized_at: datetime
    position_id: UUID | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SignalInitializationResult:
    """Signal 初始化结果；created=False 表示命中相同 setup 的首次事实。"""

    signal: SignalInstance
    created: bool


@dataclass(frozen=True, slots=True)
class SignalAuthorizationContext:
    """状态机迁移时从当前业务事实构建的版本上下文。"""

    watch_item_version: int
    context_digest: str
    trading_plan_config_version: int | None = None
    position_version: int | None = None


@dataclass(frozen=True, slots=True)
class SignalTransitionResult:
    """Signal 状态机迁移结果。

    业务规则:
        event 为 None 表示没有真实状态变化；duplicate=True 表示 Ticket 已被成功消费过，
        本次只返回首次结果且不生成新事件。
    """

    signal: SignalInstance
    event: SignalEvent | None
    decision_ticket_id: UUID
    changed: bool
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class _AppliedDecisionRecord:
    """内存幂等账本中的首次 Ticket 指纹和迁移结果。"""

    signal_id: UUID
    ticket_fingerprint: str
    result: SignalTransitionResult


_SignalIdentity = tuple[UUID, Market, UUID, Timeframe, SignalType, Direction]
_TERMINAL_STATES = {
    SignalState.INVALIDATED,
    SignalState.RESOLVED,
    SignalState.EXPIRED,
}


class SignalStateMachine:
    """Signal 状态机 V0.1。

    业务描述:
        管理内存 Signal 事实、generation 和固定迁移表，并在迁移前核验完整授权链。

    业务场景:
        REQ-0007 单进程端到端测试；REQ-0008 将把 Signal、消费账本和事件改为数据库事务。

    业务原因:
        状态机只执行机械迁移，市场判断留在 Crypto 域，授权判断留在 Policy Gate。

    调用链:
        initialize -> register OBSERVING projection
        apply -> check duplicate -> load authorization -> validate chain/context
        -> validate transition -> update projection -> build event -> remember result

    业务规则:
        - 初始 OBSERVING 不需要 Ticket，后续每次状态变化必须有已授权 Ticket。
        - 同一 Ticket ID 只有完整 payload 一致时才返回首次结果。
        - direction、Signal 版本和业务上下文版本不一致时拒绝迁移。
        - 所有投影更新通过完整 Pydantic 校验重建。
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

    def __init__(self, authorization_repository: AuthorizationRepository) -> None:
        self._authorization_repository = authorization_repository
        self._signals_by_id: dict[UUID, SignalInstance] = {}
        self._signals_by_setup: dict[
            tuple[_SignalIdentity, str], SignalInstance
        ] = {}
        self._latest_by_identity: dict[_SignalIdentity, SignalInstance] = {}
        self._applied_results: dict[UUID, _AppliedDecisionRecord] = {}

    @classmethod
    def can_transition(cls, from_state: SignalState, to_state: SignalState) -> bool:
        """判断状态迁移是否在 V0.1 合法迁移表中。"""

        return (from_state, to_state) in cls._ALLOWED_TRANSITIONS

    @classmethod
    def allowed_transitions(cls) -> frozenset[tuple[SignalState, SignalState]]:
        """返回 V0.1 合法迁移表。"""

        return cls._ALLOWED_TRANSITIONS

    def initialize(
            self,
            request: SignalInitializationRequest,
    ) -> SignalInitializationResult:
        """幂等初始化 OBSERVING Signal，并管理 generation。

        调用链:
            normalize identity/time -> lookup setup -> reject parallel active setup
            -> calculate generation -> build validated OBSERVING projection -> register

        幂等逻辑:
            同一监控身份和 setup_key 返回首次 Signal；终态后只有新 setup_key 才创建下一代。
        """

        initialized_at = ensure_utc_datetime(request.initialized_at)
        expires_at = (
            ensure_utc_datetime(request.expires_at)
            if request.expires_at is not None
            else None
        )
        setup_key = ensure_non_empty(request.setup_key)
        identity = self._identity_from_request(request)
        setup_identity = (identity, setup_key)
        existing = self._signals_by_setup.get(setup_identity)
        if existing is not None:
            return SignalInitializationResult(signal=existing, created=False)

        latest = self._latest_by_identity.get(identity)
        if latest is not None and latest.state not in _TERMINAL_STATES:
            raise SignalInitializationConflictError(
                "active signal already exists for the monitoring identity"
            )
        generation = latest.generation + 1 if latest is not None else 1
        dedupe_key = self._signal_dedupe_key(identity, generation, setup_key)
        signal = SignalInstance(
            id=uuid5(NAMESPACE_URL, dedupe_key),
            watch_item_id=request.watch_item_id,
            position_id=request.position_id,
            market=request.market,
            instrument_id=request.instrument_id,
            timeframe=request.timeframe,
            signal_type=request.signal_type,
            direction=request.direction,
            state=SignalState.OBSERVING,
            priority=request.priority,
            actionability=request.actionability,
            generation=generation,
            setup_key=setup_key,
            latest_decision_ticket_id=None,
            dedupe_key=dedupe_key,
            last_transition_at=initialized_at,
            expires_at=expires_at,
            version=0,
        )
        self._register_signal(signal)
        return SignalInitializationResult(signal=signal, created=True)

    def apply(
            self,
            current_signal: SignalInstance,
            decision_ticket: DecisionTicket,
            authorization_context: SignalAuthorizationContext,
            *,
            occurred_at: datetime | None = None,
            event_id: UUID | None = None,
    ) -> SignalTransitionResult:
        """验证授权事实并应用 DecisionTicket。

        调用链:
            check duplicate -> verify current projection -> load authorization facts
            -> validate chain/ticket/context -> validate time/transition
            -> rebuild signal -> build event -> register and remember result

        幂等逻辑:
            使用 Ticket ID 和完整 canonical payload 指纹；完全一致的重复消费返回首次结果。
        """

        ticket_fingerprint = self._decision_ticket_fingerprint(decision_ticket)
        duplicate_record = self._applied_results.get(decision_ticket.id)
        if duplicate_record is not None:
            self._ensure_duplicate_is_consistent(
                duplicate_record,
                current_signal,
                ticket_fingerprint,
            )
            return replace(duplicate_record.result, duplicate=True)

        self._ensure_current_projection(current_signal)
        transition_time = ensure_utc_datetime(occurred_at or datetime.now(UTC))
        facts = self._load_authorization(decision_ticket)
        self._validate_authorization_chain(facts)
        self._ensure_ticket_is_effective(facts, transition_time)
        self._ensure_ticket_matches_signal(current_signal, facts)
        self._ensure_expected_versions(
            current_signal,
            facts,
            authorization_context,
        )
        self._ensure_transition_time_is_valid(current_signal, transition_time)

        target_state = decision_ticket.authorized_transition
        if current_signal.state == target_state:
            result = SignalTransitionResult(
                signal=current_signal,
                event=None,
                decision_ticket_id=decision_ticket.id,
                changed=False,
            )
            self._remember_result(
                current_signal,
                decision_ticket,
                ticket_fingerprint,
                result,
            )
            return result

        if not self.can_transition(current_signal.state, target_state):
            raise InvalidSignalTransitionError(current_signal.state, target_state)

        updated_payload = current_signal.model_dump()
        updated_payload.update(
            {
                "state": target_state,
                "actionability": decision_ticket.actionability,
                "latest_decision_ticket_id": decision_ticket.id,
                "last_transition_at": transition_time,
                "version": current_signal.version + 1,
            }
        )
        updated_signal = SignalInstance.model_validate(updated_payload)
        event = self._build_signal_event(
            current_signal,
            updated_signal,
            facts,
            occurred_at=transition_time,
            event_id=event_id or uuid4(),
        )
        result = SignalTransitionResult(
            signal=updated_signal,
            event=event,
            decision_ticket_id=decision_ticket.id,
            changed=True,
        )
        self._register_signal(updated_signal)
        self._remember_result(
            current_signal,
            decision_ticket,
            ticket_fingerprint,
            result,
        )
        return result

    def applied_decision_count(self) -> int:
        """返回当前内存幂等账本中已消费的 DecisionTicket 数量。"""

        return len(self._applied_results)

    def _load_authorization(self, ticket: DecisionTicket) -> AuthorizationFacts:
        """从事实仓库加载 Ticket 对应的完整授权链。"""

        facts = self._authorization_repository.get_authorization(ticket.id)
        if facts is None:
            raise UntrustedDecisionTicketError(
                "decision ticket does not exist in authorization repository"
            )
        if facts.ticket != ticket:
            raise UntrustedDecisionTicketError(
                "decision ticket payload differs from authorization repository"
            )
        return facts

    @staticmethod
    def _validate_authorization_chain(facts: AuthorizationFacts) -> None:
        """核对 Proposal、Evaluation 与 Ticket 的不可变引用和 payload。"""

        proposal = facts.proposal
        evaluation = facts.evaluation
        ticket = facts.ticket
        proposal_digest = proposal.content_digest()

        if evaluation.outcome != PolicyOutcome.APPROVED:
            raise InvalidAuthorizationChainError(
                "decision ticket requires APPROVED policy evaluation"
            )
        if (
                evaluation.proposal_id != proposal.id
                or ticket.proposal_id != proposal.id
                or ticket.policy_evaluation_id != evaluation.id
                or evaluation.policy_version != ticket.policy_version
                or evaluation.proposal_digest != proposal_digest
                or ticket.proposal_digest != proposal_digest
        ):
            raise InvalidAuthorizationChainError(
                "authorization references, policy version, or proposal digest mismatch"
            )

        expected_ticket_payload = (
            proposal.market,
            proposal.instrument_id,
            proposal.timeframe,
            proposal.direction,
            proposal.signal_id,
            proposal.suggested_transition,
            proposal.actionability,
            proposal.position_impact,
            proposal.input_snapshot_id,
            proposal.expected_signal_version,
            proposal.watch_item_version,
            proposal.trading_plan_config_version,
            proposal.position_version,
            proposal.context_digest,
        )
        actual_ticket_payload = (
            ticket.market,
            ticket.instrument_id,
            ticket.timeframe,
            ticket.direction,
            ticket.signal_id,
            ticket.authorized_transition,
            ticket.actionability,
            ticket.position_impact,
            ticket.input_snapshot_id,
            ticket.expected_signal_version,
            ticket.watch_item_version,
            ticket.trading_plan_config_version,
            ticket.position_version,
            ticket.context_digest,
        )
        if actual_ticket_payload != expected_ticket_payload:
            raise InvalidAuthorizationChainError(
                "decision ticket payload differs from approved proposal"
            )
        if (
                ticket.issued_at != evaluation.evaluated_at
                or ticket.expires_at > evaluation.expires_at
        ):
            raise InvalidAuthorizationChainError(
                "decision ticket validity exceeds policy evaluation"
            )

    @staticmethod
    def _ensure_ticket_is_effective(
            facts: AuthorizationFacts,
            transition_time: datetime,
    ) -> None:
        """拒绝尚未签发、Ticket 过期或 Evaluation 过期的迁移。"""

        ticket = facts.ticket
        evaluation = facts.evaluation
        if transition_time < ticket.issued_at:
            raise ExpiredDecisionTicketError(
                "decision ticket is not effective before issued_at"
            )
        if transition_time > ticket.expires_at:
            raise ExpiredDecisionTicketError("decision ticket has expired")
        if transition_time > evaluation.expires_at:
            raise ExpiredDecisionTicketError("policy evaluation has expired")

    @staticmethod
    def _ensure_ticket_matches_signal(
            signal: SignalInstance,
            facts: AuthorizationFacts,
    ) -> None:
        """校验 Ticket、Proposal 与 Signal 的完整目标身份和方向。"""

        proposal = facts.proposal
        ticket = facts.ticket
        if (
                signal.id != ticket.signal_id
                or signal.market != ticket.market
                or signal.instrument_id != ticket.instrument_id
                or signal.timeframe != ticket.timeframe
                or signal.direction != ticket.direction
                or signal.signal_type != proposal.signal_type
        ):
            raise SignalTransitionMismatchError(
                "decision authorization does not match signal identity or direction"
            )

    @staticmethod
    def _ensure_expected_versions(
            signal: SignalInstance,
            facts: AuthorizationFacts,
            context: SignalAuthorizationContext,
    ) -> None:
        """校验 Signal 乐观版本和当前业务上下文版本。"""

        ticket = facts.ticket
        if signal.version != ticket.expected_signal_version:
            raise SignalVersionConflictError(
                "signal version differs from decision ticket expectation"
            )
        if (
                context.watch_item_version != ticket.watch_item_version
                or context.trading_plan_config_version
                != ticket.trading_plan_config_version
                or context.position_version != ticket.position_version
                or context.context_digest != ticket.context_digest
        ):
            raise SignalContextConflictError(
                "business context differs from decision ticket authorization"
            )

    def _ensure_current_projection(self, signal: SignalInstance) -> None:
        """拒绝未初始化或已经落后的 Signal 投影。"""

        current = self._signals_by_id.get(signal.id)
        if current is None:
            raise SignalProjectionConflictError(
                "signal was not initialized by this state machine"
            )
        if current != signal:
            raise SignalProjectionConflictError(
                "signal projection differs from current state machine fact"
            )

    @staticmethod
    def _ensure_duplicate_is_consistent(
            existing: _AppliedDecisionRecord,
            current_signal: SignalInstance,
            ticket_fingerprint: str,
    ) -> None:
        """核对重复 Ticket 的目标 Signal 和完整 payload。"""

        if existing.signal_id != current_signal.id:
            raise DuplicateDecisionConflictError(
                "decision ticket was already applied to a different signal"
            )
        if existing.ticket_fingerprint != ticket_fingerprint:
            raise DuplicateDecisionConflictError(
                "decision ticket payload differs from the first consumed payload"
            )

    @staticmethod
    def _ensure_transition_time_is_valid(
            signal: SignalInstance,
            transition_time: datetime,
    ) -> None:
        """校验 Signal 本身的单向时间和有效期。"""

        if transition_time < signal.last_transition_at:
            raise SignalTransitionTimeError(
                "occurred_at must not be earlier than signal last_transition_at"
            )
        if signal.expires_at is not None and transition_time > signal.expires_at:
            raise ExpiredSignalTransitionError(
                "signal expired before the requested transition time"
            )

    @staticmethod
    def _decision_ticket_fingerprint(decision_ticket: DecisionTicket) -> str:
        """计算 Ticket 完整 canonical payload 指纹。"""

        canonical_payload = json.dumps(
            decision_ticket.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    def _remember_result(
            self,
            current_signal: SignalInstance,
            decision_ticket: DecisionTicket,
            ticket_fingerprint: str,
            result: SignalTransitionResult,
    ) -> None:
        """记录 Ticket 首次消费结果。"""

        self._applied_results[decision_ticket.id] = _AppliedDecisionRecord(
            signal_id=current_signal.id,
            ticket_fingerprint=ticket_fingerprint,
            result=result,
        )

    def _register_signal(self, signal: SignalInstance) -> None:
        """更新状态机内存 Signal 事实和 setup 索引。"""

        identity = self._identity_from_signal(signal)
        self._signals_by_id[signal.id] = signal
        self._signals_by_setup[(identity, signal.setup_key)] = signal
        self._latest_by_identity[identity] = signal

    @staticmethod
    def _identity_from_request(
            request: SignalInitializationRequest,
    ) -> _SignalIdentity:
        """从初始化请求提取 generation 共享的监控身份。"""

        return (
            request.watch_item_id,
            request.market,
            request.instrument_id,
            request.timeframe,
            request.signal_type,
            request.direction,
        )

    @staticmethod
    def _identity_from_signal(signal: SignalInstance) -> _SignalIdentity:
        """从 Signal 投影提取监控身份。"""

        return (
            signal.watch_item_id,
            signal.market,
            signal.instrument_id,
            signal.timeframe,
            signal.signal_type,
            signal.direction,
        )

    @staticmethod
    def _signal_dedupe_key(
            identity: _SignalIdentity,
            generation: int,
            setup_key: str,
    ) -> str:
        """构造包含 direction、generation 和 setup 的稳定 Signal identity。"""

        (
            watch_item_id,
            market,
            instrument_id,
            timeframe,
            signal_type,
            direction,
        ) = identity
        return ":".join(
            (
                "signal",
                str(watch_item_id),
                market.value,
                str(instrument_id),
                timeframe.value,
                signal_type.value,
                direction.value,
                str(generation),
                setup_key,
            )
        )

    @staticmethod
    def _build_signal_event(
            previous_signal: SignalInstance,
            updated_signal: SignalInstance,
            facts: AuthorizationFacts,
            *,
            occurred_at: datetime,
            event_id: UUID,
    ) -> SignalEvent:
        """构造携带完整授权追踪引用的 SignalEvent。"""

        proposal: DecisionProposal = facts.proposal
        evaluation: PolicyEvaluation = facts.evaluation
        ticket = facts.ticket
        dedupe_key = (
            f"{previous_signal.dedupe_key}:{ticket.id}:"
            f"{previous_signal.state}->{updated_signal.state}"
        )
        return SignalEvent(
            event_id=event_id,
            signal_id=previous_signal.id,
            market=previous_signal.market,
            instrument_id=previous_signal.instrument_id,
            signal_type=previous_signal.signal_type,
            direction=previous_signal.direction,
            from_state=previous_signal.state,
            to_state=updated_signal.state,
            priority=updated_signal.priority,
            actionable_now=ticket.actionability == Actionability.ACTIONABLE_NOW,
            position_impact=ticket.position_impact,
            candidate_event_id=proposal.candidate_event_id,
            decision_proposal_id=proposal.id,
            policy_evaluation_id=evaluation.id,
            decision_ticket_id=ticket.id,
            input_snapshot_id=ticket.input_snapshot_id,
            occurred_at=occurred_at,
            dedupe_key=dedupe_key,
        )
