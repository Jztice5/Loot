"""PostgreSQL Signal 初始化与授权迁移事务 workflow。

业务描述:
    在 PostgreSQL 事实源上初始化 Signal generation，并消费已授权 DecisionTicket 完成
    Signal 投影、迁移账本、消费账本和 Outbox 的原子更新。

业务场景:
    REQ-0008 Crypto First Vertical Slice 在进程重启、多实例和至少一次投递下运行状态机。

业务原因:
    单纯把内存状态机对象写入数据库无法解决首次 generation 并发、重复 Ticket 或业务事实
    与事件发布之间的原子性；这些可靠性约束必须由数据库事务实现。

调用链:
    Monitoring lifecycle -> initialize -> SignalInstance + SignalInitialized Outbox
    DecisionTicket -> apply -> lock/load/verify -> SignalStateMachine -> persist all facts

业务规则:
    同一监控身份最多一个活跃 generation；同一 Ticket 首次结果永久保存；相同 Ticket ID
    不同 payload 拒绝；任何写入失败都回滚完整迁移事务。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from loot.contracts import (
    DecisionTicket,
    SignalEvent,
    SignalInstance,
    SignalState,
)
from loot.contracts.base import ensure_non_empty, ensure_utc_datetime
from loot.contracts.serialization import json_compatible, payload_fingerprint
from loot.persistence.authorization import PostgresAuthorizationRepository
from loot.persistence.locking import acquire_advisory_locks
from loot.persistence.mappers import contract_from_payload, signal_values
from loot.persistence.outbox import (
    OutboxMessage,
    build_outbox_message,
    insert_outbox_message,
)
from loot.persistence.schema import (
    decision_ticket_consumptions,
    signal_instances,
    signal_transitions,
)
from loot.signals import (
    AuthorizationFacts,
    DuplicateDecisionConflictError,
    SignalAuthorizationContext,
    SignalExpiryResult,
    SignalInitializationConflictError,
    SignalInitializationRequest,
    SignalInitializationResult,
    SignalStateMachine,
    SignalTransitionResult,
    SignalVersionConflictError,
)

_TERMINAL_STATES = {
    SignalState.INVALIDATED,
    SignalState.RESOLVED,
    SignalState.EXPIRED,
}


class _TransactionAuthorizationRepository:
    """把状态机授权查询固定在当前 Signal 数据库事务。"""

    def __init__(
            self,
            repository: PostgresAuthorizationRepository,
            connection: Connection,
    ) -> None:
        self._repository = repository
        self._connection = connection

    def get_authorization(self, ticket_id: UUID) -> AuthorizationFacts | None:
        """在当前连接中加载不可变授权链。"""

        return self._repository.get_authorization_in_connection(
            self._connection,
            ticket_id,
        )


class PostgresSignalWorkflow:
    """数据库事实源上的 Signal State Machine 编排器。

    业务描述:
        为现有纯业务状态机提供事务、并发锁、持久化和重启幂等能力。

    业务场景:
        应用服务接收初始化命令或 DecisionTicket 时调用；调用结束后无需保留进程内状态。

    业务原因:
        状态迁移规则仍由 SignalStateMachine 唯一定义，workflow 只负责从数据库恢复当前
        投影并把计算结果原子提交，避免出现两套迁移规则。

    调用链:
        initialize: identity lock -> latest generation -> build projection -> insert/outbox
        apply: ticket lock -> consumption -> signal row lock -> authorization facts
        -> restore/apply state machine -> optimistic update/transition/consumption/outbox

    业务规则:
        - 初始化必须先锁业务身份，再读取最新 generation。
        - apply 必须先检查持久化 consumption，再运行状态机。
        - Signal 更新必须同时满足 id 和 expected version，影响行数必须为 1。
        - Outbox 与业务事实使用同一 Connection 和事务。
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._authorization_repository = PostgresAuthorizationRepository(engine)

    def initialize(
            self,
            request: SignalInitializationRequest,
            *,
            correlation_id: UUID,
            detected_at: datetime | None = None,
    ) -> SignalInitializationResult:
        """幂等初始化数据库中的 OBSERVING Signal generation。

        调用链:
            normalize identity -> advisory lock -> find same setup/latest generation
            -> reject parallel active setup -> build validated signal -> insert/outbox

        幂等与补偿:
            相同 setup 和完整初始 payload 返回首次 Signal；不同 setup 在活跃 Signal 存在
            时拒绝；插入或 Outbox 失败时事务整体回滚。
        """

        normalized_request = replace(
            request,
            setup_key=ensure_non_empty(request.setup_key),
            initialized_at=ensure_utc_datetime(request.initialized_at),
            expires_at=(
                ensure_utc_datetime(request.expires_at)
                if request.expires_at is not None
                else None
            ),
        )
        expiry_detection_time = ensure_utc_datetime(detected_at or datetime.now(UTC))
        identity_values = self._request_identity_values(normalized_request)
        identity_key = self._identity_lock_key(identity_values)
        with self._engine.begin() as connection:
            acquire_advisory_locks(connection, identity_key)
            same_setup = self._find_setup_signal(
                connection,
                identity_values,
                normalized_request.setup_key,
            )
            if same_setup is not None:
                expected = SignalStateMachine.build_initial_signal(
                    normalized_request,
                    generation=same_setup.generation,
                )
                if expected != same_setup:
                    raise SignalInitializationConflictError(
                        "signal setup identity already exists with different input"
                    )
                return SignalInitializationResult(
                    signal=same_setup,
                    created=False,
                )

            latest = self._find_latest_signal(
                connection,
                identity_values,
                for_update=True,
            )
            if latest is not None:
                state_machine = SignalStateMachine(self._authorization_repository)
                state_machine.restore_projection(latest)
                expiry_result = state_machine.expire_if_due(
                    latest,
                    detected_at=expiry_detection_time,
                )
                if expiry_result.changed:
                    self._persist_expiry_result(
                        connection,
                        previous_signal=latest,
                        result=expiry_result,
                        correlation_id=correlation_id,
                    )
                    latest = expiry_result.signal
            if latest is not None and latest.state not in _TERMINAL_STATES:
                raise SignalInitializationConflictError(
                    "active signal already exists for the monitoring identity"
                )
            generation = latest.generation + 1 if latest is not None else 1
            signal = SignalStateMachine.build_initial_signal(
                normalized_request,
                generation=generation,
            )
            connection.execute(
                sa.insert(signal_instances).values(**signal_values(signal))
            )
            insert_outbox_message(
                connection,
                self._initialization_outbox(signal, correlation_id),
            )
        return SignalInitializationResult(signal=signal, created=True)

    def get_signal(self, signal_id: UUID) -> SignalInstance | None:
        """按 ID 读取并重新校验当前 Signal 投影。"""

        query = sa.select(signal_instances).where(signal_instances.c.id == signal_id)
        with self._engine.connect() as connection:
            row = connection.execute(query).mappings().one_or_none()
        return self._signal_from_row(row) if row is not None else None

    def apply(
            self,
            decision_ticket: DecisionTicket,
            authorization_context: SignalAuthorizationContext,
            *,
            correlation_id: UUID,
            occurred_at: datetime | None = None,
    ) -> SignalTransitionResult:
        """原子消费 Ticket 并持久化首次迁移结果。

        调用链:
            normalize time/fingerprint -> ticket advisory lock -> load consumption
            -> SELECT Signal FOR UPDATE -> load authorization -> restore/apply state machine
            -> optimistic update -> transition -> consumption -> SignalEvent Outbox

        幂等与补偿:
            已消费 Ticket 先比较完整指纹并返回首次结果；任一数据库写入失败时 Signal、
            Transition、Consumption 和 Outbox 全部回滚，重投可重新执行。
        """

        transition_time = ensure_utc_datetime(occurred_at or datetime.now(UTC))
        ticket_fingerprint = payload_fingerprint(decision_ticket)
        with self._engine.begin() as connection:
            acquire_advisory_locks(
                connection,
                f"signal:ticket:{decision_ticket.id}",
            )
            duplicate = self._get_consumed_result(
                connection,
                decision_ticket,
                ticket_fingerprint,
            )
            if duplicate is not None:
                return replace(duplicate, duplicate=True)

            signal = self._load_signal_for_update(
                connection,
                decision_ticket.signal_id,
            )
            repository = _TransactionAuthorizationRepository(
                self._authorization_repository,
                connection,
            )
            state_machine = SignalStateMachine(repository)
            state_machine.restore_projection(signal)
            event_id = uuid5(
                NAMESPACE_URL,
                f"signal-transition:{decision_ticket.id}",
            )
            result = state_machine.apply(
                signal,
                decision_ticket,
                authorization_context,
                occurred_at=transition_time,
                event_id=event_id,
            )
            transition_id = self._persist_transition_result(
                connection,
                previous_signal=signal,
                result=result,
                ticket_fingerprint=ticket_fingerprint,
                correlation_id=correlation_id,
                consumed_at=transition_time,
            )
            self._insert_consumption(
                connection,
                result=result,
                transition_id=transition_id,
                ticket_fingerprint=ticket_fingerprint,
                consumed_at=transition_time,
            )
        return result

    @staticmethod
    def _persist_transition_result(
            connection: Connection,
            *,
            previous_signal: SignalInstance,
            result: SignalTransitionResult,
            ticket_fingerprint: str,
            correlation_id: UUID,
            consumed_at: datetime,
    ) -> UUID | None:
        """持久化真实迁移；无状态变化时不写 Transition 或 Outbox。"""

        if not result.changed:
            return None
        event = result.event
        if event is None:
            raise ValueError("changed transition requires SignalEvent")

        updated_values = signal_values(result.signal)
        updated_values.pop("id")
        update_result = connection.execute(
            sa.update(signal_instances)
            .where(
                signal_instances.c.id == previous_signal.id,
                signal_instances.c.version == previous_signal.version,
            )
            .values(**updated_values, updated_at=consumed_at)
        )
        if update_result.rowcount != 1:
            raise SignalVersionConflictError(
                "signal projection changed before optimistic update"
            )

        transition_id = uuid5(
            NAMESPACE_URL,
            f"signal-transition-fact:{result.decision_ticket_id}",
        )
        connection.execute(
            sa.insert(signal_transitions).values(
                id=transition_id,
                signal_id=result.signal.id,
                decision_ticket_id=result.decision_ticket_id,
                event_id=event.event_id,
                from_state=previous_signal.state.value,
                to_state=result.signal.state.value,
                from_version=previous_signal.version,
                to_version=result.signal.version,
                occurred_at=event.occurred_at,
                payload=json_compatible(event),
            )
        )
        insert_outbox_message(
            connection,
            build_outbox_message(
                event_id=event.event_id,
                event_type="loot.crypto.SignalTransitioned",
                producer="loot.persistence.signal_workflow",
                aggregate_type="SignalInstance",
                aggregate_id=result.signal.id,
                correlation_id=correlation_id,
                causation_id=result.decision_ticket_id,
                partition_key=str(result.signal.id),
                payload={
                    "signal_event": json_compatible(event),
                    "ticket_fingerprint": ticket_fingerprint,
                },
                occurred_at=event.occurred_at,
            ),
        )
        return transition_id

    @staticmethod
    def _persist_expiry_result(
            connection: Connection,
            *,
            previous_signal: SignalInstance,
            result: SignalExpiryResult,
            correlation_id: UUID,
    ) -> UUID | None:
        """持久化状态机产生的确定性到期事实，不创建或消费 DecisionTicket。"""

        if not result.changed:
            return None
        event = result.event
        if event is None:
            raise ValueError("changed expiry transition requires SignalExpiryEvent")

        updated_values = signal_values(result.signal)
        updated_values.pop("id")
        update_result = connection.execute(
            sa.update(signal_instances)
            .where(
                signal_instances.c.id == previous_signal.id,
                signal_instances.c.version == previous_signal.version,
            )
            .values(**updated_values, updated_at=event.detected_at)
        )
        if update_result.rowcount != 1:
            raise SignalVersionConflictError(
                "signal projection changed before deterministic expiry update"
            )

        transition_id = uuid5(
            NAMESPACE_URL,
            f"signal-expiry-transition-fact:{event.event_id}",
        )
        connection.execute(
            sa.insert(signal_transitions).values(
                id=transition_id,
                signal_id=result.signal.id,
                decision_ticket_id=None,
                event_id=event.event_id,
                from_state=previous_signal.state.value,
                to_state=result.signal.state.value,
                from_version=previous_signal.version,
                to_version=result.signal.version,
                occurred_at=event.expires_at,
                payload=json_compatible(event),
            )
        )
        insert_outbox_message(
            connection,
            build_outbox_message(
                event_id=event.event_id,
                event_type="loot.crypto.SignalExpired",
                producer="loot.persistence.signal_workflow",
                aggregate_type="SignalInstance",
                aggregate_id=result.signal.id,
                correlation_id=correlation_id,
                causation_id=None,
                partition_key=str(result.signal.id),
                payload={"signal_expiry_event": json_compatible(event)},
                occurred_at=event.expires_at,
            ),
        )
        return transition_id

    @staticmethod
    def _insert_consumption(
            connection: Connection,
            *,
            result: SignalTransitionResult,
            transition_id: UUID | None,
            ticket_fingerprint: str,
            consumed_at: datetime,
    ) -> None:
        """保存 Ticket 首次消费结果，供进程重启后的重复投递返回。"""

        connection.execute(
            sa.insert(decision_ticket_consumptions).values(
                decision_ticket_id=result.decision_ticket_id,
                signal_id=result.signal.id,
                transition_id=transition_id,
                ticket_fingerprint=ticket_fingerprint,
                consumed_at=consumed_at,
                result_payload=PostgresSignalWorkflow._result_payload(result),
            )
        )

    @staticmethod
    def _get_consumed_result(
            connection: Connection,
            ticket: DecisionTicket,
            ticket_fingerprint: str,
    ) -> SignalTransitionResult | None:
        """加载首次消费结果，并拒绝 Ticket ID 或目标 Signal 冲突。"""

        query = sa.select(decision_ticket_consumptions).where(
            decision_ticket_consumptions.c.decision_ticket_id == ticket.id
        )
        row = connection.execute(query).mappings().one_or_none()
        if row is None:
            return None
        if (
                row["signal_id"] != ticket.signal_id
                or row["ticket_fingerprint"] != ticket_fingerprint
        ):
            raise DuplicateDecisionConflictError(
                "decision ticket payload differs from first consumption"
            )
        result = PostgresSignalWorkflow._result_from_payload(row["result_payload"])
        if result.decision_ticket_id != ticket.id or result.signal.id != ticket.signal_id:
            raise DuplicateDecisionConflictError(
                "stored consumption result differs from ticket identity"
            )
        return result

    @staticmethod
    def _load_signal_for_update(
            connection: Connection,
            signal_id: UUID,
    ) -> SignalInstance:
        """锁定并恢复 Ticket 目标 Signal 当前投影。"""

        query = (
            sa.select(signal_instances)
            .where(signal_instances.c.id == signal_id)
            .with_for_update()
        )
        row = connection.execute(query).mappings().one_or_none()
        if row is None:
            raise SignalInitializationConflictError(
                "decision ticket target signal does not exist"
            )
        return PostgresSignalWorkflow._signal_from_row(row)

    @staticmethod
    def _find_setup_signal(
            connection: Connection,
            identity_values: dict[str, Any],
            setup_key: str,
    ) -> SignalInstance | None:
        query = sa.select(signal_instances).where(
            *(signal_instances.c[key] == value for key, value in identity_values.items()),
            signal_instances.c.setup_key == setup_key,
        )
        row = connection.execute(query).mappings().one_or_none()
        return (
            PostgresSignalWorkflow._signal_from_row(row)
            if row is not None
            else None
        )

    @staticmethod
    def _find_latest_signal(
            connection: Connection,
            identity_values: dict[str, Any],
            *,
            for_update: bool,
    ) -> SignalInstance | None:
        query = (
            sa.select(signal_instances)
            .where(
                *(
                    signal_instances.c[key] == value
                    for key, value in identity_values.items()
                )
            )
            .order_by(signal_instances.c.generation.desc())
            .limit(1)
        )
        if for_update:
            query = query.with_for_update()
        row = connection.execute(query).mappings().one_or_none()
        return (
            PostgresSignalWorkflow._signal_from_row(row)
            if row is not None
            else None
        )

    @staticmethod
    def _signal_from_row(row: sa.RowMapping) -> SignalInstance:
        """重建 Signal 并核对关键索引列与完整 payload。"""

        signal = contract_from_payload(SignalInstance, row["payload"])
        indexed_values = (
            row["id"],
            row["state"],
            row["version"],
            row["generation"],
            row["dedupe_key"],
            row["latest_decision_ticket_id"],
        )
        payload_values = (
            signal.id,
            signal.state.value,
            signal.version,
            signal.generation,
            signal.dedupe_key,
            signal.latest_decision_ticket_id,
        )
        if indexed_values != payload_values:
            raise SignalVersionConflictError(
                "signal indexed columns differ from payload projection"
            )
        return signal

    @staticmethod
    def _request_identity_values(
            request: SignalInitializationRequest,
    ) -> dict[str, Any]:
        return {
            "watch_item_id": request.watch_item_id,
            "market": request.market.value,
            "instrument_id": request.instrument_id,
            "timeframe": request.timeframe.value,
            "signal_type": request.signal_type.value,
            "direction": request.direction.value,
        }

    @staticmethod
    def _identity_lock_key(identity_values: dict[str, Any]) -> str:
        return "signal:identity:" + ":".join(
            str(identity_values[key])
            for key in (
                "watch_item_id",
                "market",
                "instrument_id",
                "timeframe",
                "signal_type",
                "direction",
            )
        )

    @staticmethod
    def _initialization_outbox(
            signal: SignalInstance,
            correlation_id: UUID,
    ) -> OutboxMessage:
        event_id = uuid5(NAMESPACE_URL, f"{signal.dedupe_key}:initialized")
        return build_outbox_message(
            event_id=event_id,
            event_type="loot.crypto.SignalInitialized",
            producer="loot.persistence.signal_workflow",
            aggregate_type="SignalInstance",
            aggregate_id=signal.id,
            correlation_id=correlation_id,
            causation_id=None,
            partition_key=str(signal.id),
            payload={"signal": json_compatible(signal)},
            occurred_at=signal.last_transition_at,
        )

    @staticmethod
    def _result_payload(result: SignalTransitionResult) -> dict[str, Any]:
        return {
            "signal": json_compatible(result.signal),
            "event": json_compatible(result.event) if result.event is not None else None,
            "decision_ticket_id": str(result.decision_ticket_id),
            "changed": result.changed,
            "duplicate": False,
        }

    @staticmethod
    def _result_from_payload(payload: dict[str, Any]) -> SignalTransitionResult:
        event_payload = payload.get("event")
        return SignalTransitionResult(
            signal=SignalInstance.model_validate(payload["signal"]),
            event=(
                SignalEvent.model_validate(event_payload)
                if event_payload is not None
                else None
            ),
            decision_ticket_id=UUID(payload["decision_ticket_id"]),
            changed=bool(payload["changed"]),
            duplicate=bool(payload.get("duplicate", False)),
        )
