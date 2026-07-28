"""Crypto MonitoringRun PostgreSQL Repository。

业务描述:
    持久化到期 Run、追加 Attempt、Worker 租约、Snapshot 输入绑定和跨事务恢复游标。

业务场景:
    Scheduler 周期性物化 ACTIVE H1 Subscription；一个或多个 Worker 并发认领、重试和恢复。

业务原因:
    任务事实必须独立于进程生命周期；租约只表达当前执行权，最终业务幂等继续由下游事实仓库负责。

调用链:
    Scheduler -> materialize_due_runs -> MonitoringRun/Outbox
    Worker -> claim_due_run -> bind_input -> record_checkpoint -> complete/retry/fail

业务规则:
    网络调用期间不持有本 Repository 事务；状态更新必须匹配 lease_token 和 version；过期租约的
    STARTED Attempt 必须先标记 ABANDONED；调度游标推进不提升 Subscription config_version。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection

from loot.application.monitoring import (
    MonitoringFactConflictError,
    MonitoringInputChangedError,
    MonitoringLeaseLostError,
    MonitoringRunNotFoundError,
)

from loot.contracts import (
    CRYPTO_MONITORING_WORKFLOW_VERSION,
    Instrument,
    InstrumentStatus,
    Market,
    MarketSnapshot,
    MonitoringAttemptStatus,
    MonitoringRun,
    MonitoringRunAttempt,
    MonitoringRunOutcome,
    MonitoringRunPhase,
    MonitoringRunStatus,
    MonitoringSubscription,
    MonitoringSubscriptionStatus,
    Timeframe,
    WatchItem,
    WatchItemStatus,
    monitoring_execution_context_digest,
    monitoring_run_id,
    monitoring_run_key,
)
from loot.contracts.base import ensure_non_empty, ensure_utc_datetime
from loot.contracts.serialization import json_compatible
from loot.persistence.locking import acquire_advisory_locks
from loot.persistence.mappers import contract_from_payload, subscription_values
from loot.persistence.outbox import build_outbox_message, insert_outbox_message
from loot.persistence.schema import (
    decision_tickets,
    instruments,
    monitoring_run_attempts,
    monitoring_runs,
    monitoring_subscriptions,
    watch_items,
)

DEFAULT_WORKFLOW_VERSION = CRYPTO_MONITORING_WORKFLOW_VERSION
DEFAULT_AVAILABILITY_DELAY = timedelta(seconds=90)
DEFAULT_LEASE_DURATION = timedelta(minutes=5)
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_MAX_CATCH_UP = 24
_H1 = timedelta(hours=1)
_PHASE_ORDER = {phase: index for index, phase in enumerate(MonitoringRunPhase)}


class PostgresMonitoringRepository:
    """实现 Crypto H1 Run 账本、租约和恢复检查点。

    业务描述:
        负责 Run 物化、并发认领、Attempt 追加、输入绑定、阶段推进和终态事件写入。

    业务场景:
        Scheduler 周期性补齐 H1 Run；多个 Worker 通过短租约竞争任务，并在失败或重启后恢复。

    业务原因:
        PostgreSQL 是运行状态事实源，必须让执行权、恢复位置和业务事实不依赖单个进程生命周期。

    调用链:
        CryptoMonitoringWorker -> PostgresMonitoringRepository -> PostgreSQL/Outbox

    业务规则:
        Run 使用确定性业务键幂等物化；claim 使用 ``FOR UPDATE SKIP LOCKED``；状态写入校验
        ``lease_token + version``；外部网络调用期间不保持本仓库事务。
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def materialize_due_runs(
            self,
            *,
            now: datetime | None = None,
            workflow_version: str = DEFAULT_WORKFLOW_VERSION,
            subscription_ids: tuple[UUID, ...] | None = None,
            availability_delay: timedelta = DEFAULT_AVAILABILITY_DELAY,
            max_attempts: int = DEFAULT_MAX_ATTEMPTS,
            max_catch_up: int = DEFAULT_MAX_CATCH_UP,
    ) -> tuple[MonitoringRun, ...]:
        """为所有到期 ACTIVE Crypto H1 Subscription 物化稳定 Run。

        调用链:
            discover due subscriptions -> lock WatchItem/Subscription -> insert Run/Outbox
            -> advance next_run_at
        """

        version = ensure_non_empty(workflow_version)
        if availability_delay < timedelta(0):
            raise ValueError("availability_delay must not be negative")
        if max_attempts < 1 or max_catch_up < 1:
            raise ValueError("attempt and catch-up budgets must be positive")
        if subscription_ids is not None and not subscription_ids:
            return ()
        effective_now = self._database_now() if now is None else ensure_utc_datetime(now)
        scope_filter = (
            monitoring_subscriptions.c.id.in_(subscription_ids)
            if subscription_ids is not None
            else sa.true()
        )
        with self._engine.connect() as connection:
            candidate_ids = tuple(
                connection.execute(
                    sa.select(monitoring_subscriptions.c.id)
                    .join(watch_items, watch_items.c.id == monitoring_subscriptions.c.watch_item_id)
                    .join(instruments, instruments.c.instrument_id == monitoring_subscriptions.c.instrument_id)
                    .where(
                        monitoring_subscriptions.c.market == Market.CRYPTO.value,
                        monitoring_subscriptions.c.timeframe == Timeframe.H1.value,
                        monitoring_subscriptions.c.status == MonitoringSubscriptionStatus.ACTIVE.value,
                        watch_items.c.status == WatchItemStatus.ACTIVE.value,
                        instruments.c.status == InstrumentStatus.ACTIVE.value,
                        scope_filter,
                        sa.or_(
                            monitoring_subscriptions.c.next_run_at.is_(None),
                            monitoring_subscriptions.c.next_run_at <= effective_now,
                        ),
                    )
                    .order_by(
                        monitoring_subscriptions.c.next_run_at.asc().nullsfirst(),
                        monitoring_subscriptions.c.id,
                    )
                ).scalars()
            )

        created: list[MonitoringRun] = []
        for subscription_id in candidate_ids:
            created.extend(
                self._materialize_subscription(
                    subscription_id,
                    now=effective_now,
                    workflow_version=version,
                    availability_delay=availability_delay,
                    max_attempts=max_attempts,
                    max_catch_up=max_catch_up,
                )
            )
        return tuple(created)

    def claim_due_run(
            self,
            *,
            worker_id: str,
            now: datetime | None = None,
            lease_duration: timedelta = DEFAULT_LEASE_DURATION,
            workflow_version: str = DEFAULT_WORKFLOW_VERSION,
    ) -> MonitoringRun | None:
        """使用 SKIP LOCKED 认领一个到期 Run，并追加 STARTED Attempt。"""

        owner = ensure_non_empty(worker_id)
        version = ensure_non_empty(workflow_version)
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        effective_now = self._database_now() if now is None else ensure_utc_datetime(now)
        with self._engine.begin() as connection:
            while True:
                row = connection.execute(
                    sa.select(monitoring_runs)
                    .where(
                        monitoring_runs.c.workflow_version == version,
                        sa.or_(
                            monitoring_runs.c.status == MonitoringRunStatus.PENDING.value,
                            sa.and_(
                                monitoring_runs.c.status == MonitoringRunStatus.RETRY_WAIT.value,
                                monitoring_runs.c.next_attempt_at <= effective_now,
                            ),
                            sa.and_(
                                monitoring_runs.c.status == MonitoringRunStatus.RUNNING.value,
                                monitoring_runs.c.lease_expires_at <= effective_now,
                            ),
                        )
                    )
                    .order_by(monitoring_runs.c.target_bar_closed_at, monitoring_runs.c.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).mappings().one_or_none()
                if row is None:
                    return None

                current = _run_from_row(row)
                if current.status == MonitoringRunStatus.RUNNING:
                    self._abandon_current_attempt(connection, current, effective_now)
                    if current.attempt_count >= current.max_attempts:
                        self._finalize_exhausted_run(connection, current, effective_now)
                        continue
                elif not self._claim_configuration_is_current(connection, current):
                    self._cancel_unclaimed_run(connection, current, effective_now)
                    continue

                lease_token = uuid5(
                    NAMESPACE_URL,
                    f"loot:monitoring-lease:{current.id}:{current.attempt_count + 1}:{owner}",
                )
                claimed = MonitoringRun.model_validate(
                    {
                        **current.model_dump(),
                        "status": MonitoringRunStatus.RUNNING,
                        "attempt_count": current.attempt_count + 1,
                        "next_attempt_at": None,
                        "lease_token": lease_token,
                        "lease_owner": owner,
                        "lease_expires_at": effective_now + lease_duration,
                        "last_error_code": None,
                        "updated_at": effective_now,
                        "version": current.version + 1,
                    }
                )
                self._update_run(connection, current, claimed)
                attempt = MonitoringRunAttempt(
                    id=_attempt_id(claimed.id, claimed.attempt_count),
                    run_id=claimed.id,
                    attempt_number=claimed.attempt_count,
                    lease_token=lease_token,
                    worker_id=owner,
                    status=MonitoringAttemptStatus.STARTED,
                    started_at=effective_now,
                )
                connection.execute(
                    sa.insert(monitoring_run_attempts).values(**_attempt_values(attempt))
                )
                return claimed

    def load_bound_instrument(self, run: MonitoringRun) -> Instrument:
        """加载 Run 已绑定的不可变 Instrument，不用当前生命周期回滚 RUNNING。"""

        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(instruments).where(
                    instruments.c.instrument_id == run.instrument_id
                )
            ).mappings().one_or_none()
        if row is None:
            raise MonitoringFactConflictError("bound Instrument does not exist")
        instrument = contract_from_payload(Instrument, row["payload"])
        if instrument.instrument_id != run.instrument_id or instrument.market != run.market:
            raise MonitoringFactConflictError("bound Instrument identity changed")
        return instrument

    def decision_ticket_is_expired(
            self,
            decision_ticket_id: UUID,
            *,
            now: datetime,
    ) -> bool:
        """使用事实仓库中的 Ticket 有效期判断恢复阶段是否仍可消费。"""

        effective_now = ensure_utc_datetime(now)
        with self._engine.connect() as connection:
            expires_at = connection.execute(
                sa.select(decision_tickets.c.expires_at).where(
                    decision_tickets.c.id == decision_ticket_id
                )
            ).scalar_one_or_none()
        if expires_at is None:
            raise MonitoringFactConflictError("bound DecisionTicket does not exist")
        if not isinstance(expires_at, datetime):
            raise MonitoringFactConflictError("DecisionTicket expiry is not a datetime")
        return effective_now >= ensure_utc_datetime(expires_at)

    def bind_input(
            self,
            *,
            run_id: UUID,
            lease_token: UUID,
            expected_version: int,
            snapshot: MarketSnapshot,
            evaluated_at: datetime,
            now: datetime | None = None,
    ) -> MonitoringRun:
        """首次绑定 Snapshot 与评估时间，或验证重试输入完全一致。"""

        effective_now = ensure_utc_datetime(now or datetime.now(UTC))
        stable_evaluated_at = ensure_utc_datetime(evaluated_at)
        with self._engine.begin() as connection:
            current = self._locked_owned_run(
                connection,
                run_id,
                lease_token=lease_token,
                expected_version=expected_version,
            )
            if snapshot.market != current.market or snapshot.instrument_id != current.instrument_id:
                raise MonitoringFactConflictError("snapshot does not match monitoring run")
            if snapshot.timeframe != current.timeframe:
                raise MonitoringFactConflictError("snapshot timeframe does not match run")
            latest = snapshot.latest_closed_bar
            if latest is None or latest.closed_at != current.target_bar_closed_at:
                raise MonitoringFactConflictError("snapshot does not end at target_bar_closed_at")
            incoming_identity = (
                snapshot.id,
                snapshot.snapshot_content_hash,
                snapshot.source_provider,
            )
            stored_identity = (
                current.input_snapshot_id,
                current.snapshot_content_hash,
                current.source_provider,
            )
            if current.input_snapshot_id is not None:
                if incoming_identity != stored_identity:
                    raise MonitoringInputChangedError(
                        "target window changed after the monitoring run bound its input"
                    )
                if current.decision_evaluated_at != stable_evaluated_at:
                    raise MonitoringFactConflictError(
                        "decision_evaluated_at changed after first binding"
                    )
                return current

            updated = MonitoringRun.model_validate(
                {
                    **current.model_dump(),
                    "phase": MonitoringRunPhase.INPUT_BOUND,
                    "input_snapshot_id": snapshot.id,
                    "snapshot_content_hash": snapshot.snapshot_content_hash,
                    "source_provider": snapshot.source_provider,
                    "decision_evaluated_at": stable_evaluated_at,
                    "updated_at": effective_now,
                    "version": current.version + 1,
                }
            )
            self._update_run(connection, current, updated, require_lease=True)
            return updated

    def record_checkpoint(
            self,
            *,
            run_id: UUID,
            lease_token: UUID,
            expected_version: int,
            phase: MonitoringRunPhase,
            now: datetime | None = None,
            candidate_id: UUID | None = None,
            signal_id: UUID | None = None,
            proposal_id: UUID | None = None,
            policy_evaluation_id: UUID | None = None,
            decision_ticket_id: UUID | None = None,
    ) -> MonitoringRun:
        """推进已提交事实的恢复游标，并拒绝阶段身份冲突。"""

        if phase in {
            MonitoringRunPhase.MATERIALIZED,
            MonitoringRunPhase.INPUT_BOUND,
            MonitoringRunPhase.FINISHED,
        }:
            raise ValueError("record_checkpoint requires a Run-Once fact phase")
        effective_now = ensure_utc_datetime(now or datetime.now(UTC))
        identifiers = {
            "candidate_id": candidate_id,
            "signal_id": signal_id,
            "proposal_id": proposal_id,
            "policy_evaluation_id": policy_evaluation_id,
            "decision_ticket_id": decision_ticket_id,
        }
        with self._engine.begin() as connection:
            current = self._locked_owned_run(
                connection,
                run_id,
                lease_token=lease_token,
                expected_version=expected_version,
            )
            for field_name, incoming in identifiers.items():
                stored = getattr(current, field_name)
                if stored is not None and incoming is not None and stored != incoming:
                    raise MonitoringFactConflictError(
                        f"{field_name} changed across monitoring attempts"
                    )
            if _PHASE_ORDER[phase] < _PHASE_ORDER[current.phase]:
                return current
            values = current.model_dump()
            values.update(
                {
                    field_name: incoming if incoming is not None else getattr(current, field_name)
                    for field_name, incoming in identifiers.items()
                }
            )
            values.update(
                {
                    "phase": phase,
                    "updated_at": effective_now,
                    "version": current.version + 1,
                }
            )
            updated = MonitoringRun.model_validate(values)
            self._update_run(connection, current, updated, require_lease=True)
            return updated

    def complete_run(
            self,
            *,
            run_id: UUID,
            lease_token: UUID,
            expected_version: int,
            outcome: MonitoringRunOutcome,
            now: datetime | None = None,
    ) -> MonitoringRun:
        """把正常业务结果写为 COMPLETED，并完成当前 Attempt。"""

        effective_now = ensure_utc_datetime(now or datetime.now(UTC))
        with self._engine.begin() as connection:
            current = self._locked_owned_run(
                connection,
                run_id,
                lease_token=lease_token,
                expected_version=expected_version,
            )
            completed = MonitoringRun.model_validate(
                {
                    **current.model_dump(),
                    "status": MonitoringRunStatus.COMPLETED,
                    "phase": MonitoringRunPhase.FINISHED,
                    "outcome": outcome,
                    "lease_token": None,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": effective_now,
                    "completed_at": effective_now,
                    "version": current.version + 1,
                }
            )
            self._update_run(connection, current, completed, require_lease=True)
            self._finish_attempt(connection, current, MonitoringAttemptStatus.COMPLETED, effective_now)
            self._append_run_event(connection, completed)
            return completed

    def record_failure(
            self,
            *,
            run_id: UUID,
            lease_token: UUID,
            expected_version: int,
            error_code: str,
            retryable: bool,
            next_attempt_at: datetime | None = None,
            now: datetime | None = None,
    ) -> MonitoringRun:
        """记录当前 Attempt 失败，并进入 RETRY_WAIT 或终态 FAILED。"""

        code = ensure_non_empty(error_code)
        effective_now = ensure_utc_datetime(now or datetime.now(UTC))
        retry_at = ensure_utc_datetime(next_attempt_at) if next_attempt_at is not None else None
        with self._engine.begin() as connection:
            current = self._locked_owned_run(
                connection,
                run_id,
                lease_token=lease_token,
                expected_version=expected_version,
            )
            should_retry = retryable and current.attempt_count < current.max_attempts
            if should_retry and (retry_at is None or retry_at <= effective_now):
                raise ValueError("retryable failure requires a future next_attempt_at")
            terminal_code = code if should_retry else (
                "RETRY_EXHAUSTED" if retryable else code
            )
            status = (
                MonitoringRunStatus.RETRY_WAIT
                if should_retry
                else MonitoringRunStatus.FAILED
            )
            updated = MonitoringRun.model_validate(
                {
                    **current.model_dump(),
                    "status": status,
                    "next_attempt_at": retry_at if should_retry else None,
                    "lease_token": None,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": terminal_code,
                    "updated_at": effective_now,
                    "completed_at": None if should_retry else effective_now,
                    "version": current.version + 1,
                }
            )
            self._update_run(connection, current, updated, require_lease=True)
            self._finish_attempt(
                connection,
                current,
                MonitoringAttemptStatus.FAILED,
                effective_now,
                error_code=terminal_code,
                retryable=should_retry,
                next_attempt_at=retry_at if should_retry else None,
            )
            self._append_run_event(connection, updated)
            return updated

    def cancel_run(
            self,
            *,
            run_id: UUID,
            lease_token: UUID,
            expected_version: int,
            error_code: str,
            now: datetime | None = None,
    ) -> MonitoringRun:
        """在 Provider 访问前取消配置失效的已认领 Run。"""

        code = ensure_non_empty(error_code)
        effective_now = ensure_utc_datetime(now or datetime.now(UTC))
        with self._engine.begin() as connection:
            current = self._locked_owned_run(
                connection,
                run_id,
                lease_token=lease_token,
                expected_version=expected_version,
            )
            canceled = MonitoringRun.model_validate(
                {
                    **current.model_dump(),
                    "status": MonitoringRunStatus.CANCELED,
                    "lease_token": None,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": code,
                    "updated_at": effective_now,
                    "completed_at": effective_now,
                    "version": current.version + 1,
                }
            )
            self._update_run(connection, current, canceled, require_lease=True)
            self._finish_attempt(connection, current, MonitoringAttemptStatus.COMPLETED, effective_now)
            self._append_run_event(connection, canceled)
            return canceled

    def get_run(self, run_id: UUID) -> MonitoringRun:
        """按主键读取并完整校验当前 Run 投影。"""

        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(monitoring_runs).where(monitoring_runs.c.id == run_id)
            ).mappings().one_or_none()
        if row is None:
            raise MonitoringRunNotFoundError("MonitoringRun does not exist")
        return _run_from_row(row)

    def list_attempts(self, run_id: UUID) -> tuple[MonitoringRunAttempt, ...]:
        """按 attempt_number 返回追加式执行证据。"""

        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.select(monitoring_run_attempts)
                .where(monitoring_run_attempts.c.run_id == run_id)
                .order_by(monitoring_run_attempts.c.attempt_number)
            ).mappings().all()
        return tuple(_attempt_from_row(row) for row in rows)

    def _materialize_subscription(
            self,
            subscription_id: UUID,
            *,
            now: datetime,
            workflow_version: str,
            availability_delay: timedelta,
            max_attempts: int,
            max_catch_up: int,
    ) -> tuple[MonitoringRun, ...]:
        with self._engine.begin() as connection:
            probe = connection.execute(
                sa.select(monitoring_subscriptions.c.watch_item_id).where(
                    monitoring_subscriptions.c.id == subscription_id
                )
            ).scalar_one_or_none()
            if probe is None:
                return ()
            acquire_advisory_locks(connection, f"monitoring-subscription:{subscription_id}")
            watch_row = connection.execute(
                sa.select(watch_items).where(watch_items.c.id == probe).with_for_update()
            ).mappings().one()
            subscription_row = connection.execute(
                sa.select(monitoring_subscriptions)
                .where(monitoring_subscriptions.c.id == subscription_id)
                .with_for_update()
            ).mappings().one()
            instrument_row = connection.execute(
                sa.select(instruments).where(
                    instruments.c.instrument_id == subscription_row["instrument_id"]
                )
            ).mappings().one()
            watch_item = contract_from_payload(WatchItem, watch_row["payload"])
            subscription = contract_from_payload(
                MonitoringSubscription,
                subscription_row["payload"],
            )
            instrument = contract_from_payload(Instrument, instrument_row["payload"])
            if not _configuration_is_active(instrument, watch_item, subscription):
                return ()

            next_run_at = subscription.next_run_at
            if next_run_at is None:
                target = _latest_available_h1_target(now, availability_delay)
                next_run_at = target + availability_delay
            created: list[MonitoringRun] = []
            cycle_count = 0
            while next_run_at <= now and cycle_count < max_catch_up:
                target = next_run_at - availability_delay
                run = _new_run(
                    subscription=subscription,
                    watch_item=watch_item,
                    target_bar_closed_at=target,
                    workflow_version=workflow_version,
                    max_attempts=max_attempts,
                    created_at=now,
                )
                inserted_id = connection.execute(
                    postgresql_insert(monitoring_runs)
                    .values(**_run_values(run))
                    .on_conflict_do_nothing(
                        index_elements=[
                            monitoring_runs.c.subscription_id,
                            monitoring_runs.c.target_bar_closed_at,
                            monitoring_runs.c.workflow_version,
                        ]
                    )
                    .returning(monitoring_runs.c.id)
                ).scalar_one_or_none()
                if inserted_id is not None:
                    created.append(run)
                    self._append_run_event(connection, run)
                else:
                    existing_row = connection.execute(
                        sa.select(monitoring_runs).where(monitoring_runs.c.id == run.id)
                    ).mappings().one_or_none()
                    if existing_row is None or _run_from_row(existing_row).run_key != run.run_key:
                        raise MonitoringFactConflictError(
                            "monitoring run identity conflicts with an existing fact"
                        )
                next_run_at += _H1
                cycle_count += 1

            updated_subscription = MonitoringSubscription.model_validate(
                {
                    **subscription.model_dump(),
                    "next_run_at": next_run_at,
                    "updated_at": max(now, subscription.updated_at),
                }
            )
            connection.execute(
                sa.update(monitoring_subscriptions)
                .where(
                    monitoring_subscriptions.c.id == subscription.id,
                    monitoring_subscriptions.c.config_version == subscription.config_version,
                )
                .values(**subscription_values(updated_subscription))
            )
            return tuple(created)

    def _database_now(self) -> datetime:
        with self._engine.connect() as connection:
            value = connection.execute(sa.select(sa.func.current_timestamp())).scalar_one()
        return ensure_utc_datetime(value)

    @staticmethod
    def _claim_configuration_is_current(
            connection: Connection,
            run: MonitoringRun,
    ) -> bool:
        """在认领前锁定并复核 Run 物化时绑定的配置版本。"""

        watch_row = connection.execute(
            sa.select(watch_items)
            .where(watch_items.c.id == run.watch_item_id)
            .with_for_update()
        ).mappings().one_or_none()
        subscription_row = connection.execute(
            sa.select(monitoring_subscriptions)
            .where(monitoring_subscriptions.c.id == run.subscription_id)
            .with_for_update()
        ).mappings().one_or_none()
        if watch_row is None or subscription_row is None:
            return False
        return (
                watch_row["status"] == WatchItemStatus.ACTIVE.value
                and watch_row["version"] == run.watch_item_version
                and subscription_row["status"] == MonitoringSubscriptionStatus.ACTIVE.value
                and subscription_row["config_version"] == run.subscription_config_version
                and subscription_row["instrument_id"] == run.instrument_id
                and subscription_row["timeframe"] == run.timeframe.value
        )

    def _cancel_unclaimed_run(
            self,
            connection: Connection,
            current: MonitoringRun,
            now: datetime,
    ) -> None:
        canceled = MonitoringRun.model_validate(
            {
                **current.model_dump(),
                "status": MonitoringRunStatus.CANCELED,
                "next_attempt_at": None,
                "last_error_code": "CONFIGURATION_INACTIVE",
                "updated_at": now,
                "completed_at": now,
                "version": current.version + 1,
            }
        )
        self._update_run(connection, current, canceled)
        self._append_run_event(connection, canceled)

    @staticmethod
    def _locked_owned_run(
            connection: Connection,
            run_id: UUID,
            *,
            lease_token: UUID,
            expected_version: int,
    ) -> MonitoringRun:
        row = connection.execute(
            sa.select(monitoring_runs)
            .where(monitoring_runs.c.id == run_id)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise MonitoringRunNotFoundError("MonitoringRun does not exist")
        run = _run_from_row(row)
        if (
                run.status != MonitoringRunStatus.RUNNING
                or run.lease_token != lease_token
                or run.version != expected_version
        ):
            raise MonitoringLeaseLostError("monitoring run lease or version is no longer current")
        return run

    @staticmethod
    def _update_run(
            connection: Connection,
            current: MonitoringRun,
            updated: MonitoringRun,
            *,
            require_lease: bool = False,
    ) -> None:
        conditions = [
            monitoring_runs.c.id == current.id,
            monitoring_runs.c.version == current.version,
        ]
        if require_lease:
            conditions.append(monitoring_runs.c.lease_token == current.lease_token)
        count = connection.execute(
            sa.update(monitoring_runs).where(*conditions).values(**_run_values(updated))
        ).rowcount
        if count != 1:
            raise MonitoringLeaseLostError("monitoring run changed before update")

    @staticmethod
    def _abandon_current_attempt(
            connection: Connection,
            run: MonitoringRun,
            finished_at: datetime,
    ) -> None:
        count = connection.execute(
            sa.update(monitoring_run_attempts)
            .where(
                monitoring_run_attempts.c.run_id == run.id,
                monitoring_run_attempts.c.lease_token == run.lease_token,
                monitoring_run_attempts.c.status == MonitoringAttemptStatus.STARTED.value,
            )
            .values(
                status=MonitoringAttemptStatus.ABANDONED.value,
                finished_at=finished_at,
                details={"reason": "LEASE_EXPIRED"},
            )
        ).rowcount
        if count != 1:
            raise MonitoringFactConflictError("expired lease is missing its STARTED attempt")

    def _finalize_exhausted_run(
            self,
            connection: Connection,
            current: MonitoringRun,
            now: datetime,
    ) -> None:
        failed = MonitoringRun.model_validate(
            {
                **current.model_dump(),
                "status": MonitoringRunStatus.FAILED,
                "lease_token": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "last_error_code": "RETRY_EXHAUSTED",
                "updated_at": now,
                "completed_at": now,
                "version": current.version + 1,
            }
        )
        self._update_run(connection, current, failed, require_lease=True)
        self._append_run_event(connection, failed)

    @staticmethod
    def _finish_attempt(
            connection: Connection,
            run: MonitoringRun,
            status: MonitoringAttemptStatus,
            finished_at: datetime,
            *,
            error_code: str | None = None,
            retryable: bool | None = None,
            next_attempt_at: datetime | None = None,
    ) -> None:
        count = connection.execute(
            sa.update(monitoring_run_attempts)
            .where(
                monitoring_run_attempts.c.run_id == run.id,
                monitoring_run_attempts.c.lease_token == run.lease_token,
                monitoring_run_attempts.c.status == MonitoringAttemptStatus.STARTED.value,
            )
            .values(
                status=status.value,
                finished_at=finished_at,
                error_code=error_code,
                retryable=retryable,
                next_attempt_at=next_attempt_at,
            )
        ).rowcount
        if count != 1:
            raise MonitoringFactConflictError("current lease is missing its STARTED attempt")

    @staticmethod
    def _append_run_event(connection: Connection, run: MonitoringRun) -> None:
        event_type = {
            MonitoringRunStatus.PENDING: "loot.monitoring.RunScheduled",
            MonitoringRunStatus.COMPLETED: "loot.monitoring.RunCompleted",
            MonitoringRunStatus.RETRY_WAIT: "loot.monitoring.RunRetryScheduled",
            MonitoringRunStatus.FAILED: "loot.monitoring.RunFailed",
            MonitoringRunStatus.CANCELED: "loot.monitoring.RunCanceled",
        }.get(run.status)
        if event_type is None:
            return
        insert_outbox_message(
            connection,
            build_outbox_message(
                event_id=uuid5(
                    NAMESPACE_URL,
                    f"loot:monitoring-event:{run.id}:{run.status.value}:{run.version}",
                ),
                event_type=event_type,
                producer="loot.persistence.monitoring",
                aggregate_type="MonitoringRun",
                aggregate_id=run.id,
                correlation_id=run.id,
                causation_id=run.lease_token,
                partition_key=str(run.subscription_id),
                payload={"monitoring_run": json_compatible(run)},
                occurred_at=run.updated_at,
            ),
        )


def _new_run(
        *,
        subscription: MonitoringSubscription,
        watch_item: WatchItem,
        target_bar_closed_at: datetime,
        workflow_version: str,
        max_attempts: int,
        created_at: datetime,
) -> MonitoringRun:
    target = ensure_utc_datetime(target_bar_closed_at)
    return MonitoringRun(
        id=monitoring_run_id(subscription.id, target, workflow_version),
        run_key=monitoring_run_key(subscription.id, target, workflow_version),
        subscription_id=subscription.id,
        watch_item_id=watch_item.id,
        instrument_id=subscription.instrument_id,
        market=subscription.market,
        timeframe=subscription.timeframe,
        target_bar_closed_at=target,
        workflow_version=workflow_version,
        execution_context_digest=monitoring_execution_context_digest(
            subscription_id=subscription.id,
            watch_item_id=watch_item.id,
            instrument_id=subscription.instrument_id,
            watch_item_version=watch_item.version,
            subscription_config_version=subscription.config_version,
            workflow_version=workflow_version,
        ),
        watch_item_version=watch_item.version,
        subscription_config_version=subscription.config_version,
        status=MonitoringRunStatus.PENDING,
        phase=MonitoringRunPhase.MATERIALIZED,
        attempt_count=0,
        max_attempts=max_attempts,
        created_at=created_at,
        updated_at=created_at,
        version=0,
    )


def _configuration_is_active(
        instrument: Instrument,
        watch_item: WatchItem,
        subscription: MonitoringSubscription,
) -> bool:
    return (
            instrument.market == Market.CRYPTO
            and instrument.status == InstrumentStatus.ACTIVE
            and watch_item.market == Market.CRYPTO
            and watch_item.status == WatchItemStatus.ACTIVE
            and subscription.market == Market.CRYPTO
            and subscription.timeframe == Timeframe.H1
            and subscription.status == MonitoringSubscriptionStatus.ACTIVE
            and watch_item.id == subscription.watch_item_id
            and instrument.instrument_id == subscription.instrument_id
    )


def _latest_available_h1_target(now: datetime, availability_delay: timedelta) -> datetime:
    available_time = ensure_utc_datetime(now) - availability_delay
    return available_time.replace(minute=0, second=0, microsecond=0)


def _attempt_id(run_id: UUID, attempt_number: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"loot:monitoring-attempt:{run_id}:{attempt_number}")


def _run_values(run: MonitoringRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "run_key": run.run_key,
        "subscription_id": run.subscription_id,
        "watch_item_id": run.watch_item_id,
        "instrument_id": run.instrument_id,
        "market": run.market.value,
        "timeframe": run.timeframe.value,
        "target_bar_closed_at": run.target_bar_closed_at,
        "workflow_version": run.workflow_version,
        "execution_context_digest": run.execution_context_digest,
        "watch_item_version": run.watch_item_version,
        "subscription_config_version": run.subscription_config_version,
        "status": run.status.value,
        "phase": run.phase.value,
        "outcome": run.outcome.value if run.outcome is not None else None,
        "attempt_count": run.attempt_count,
        "max_attempts": run.max_attempts,
        "next_attempt_at": run.next_attempt_at,
        "lease_token": run.lease_token,
        "lease_owner": run.lease_owner,
        "lease_expires_at": run.lease_expires_at,
        "input_snapshot_id": run.input_snapshot_id,
        "snapshot_content_hash": run.snapshot_content_hash,
        "source_provider": run.source_provider,
        "decision_evaluated_at": run.decision_evaluated_at,
        "candidate_id": run.candidate_id,
        "proposal_id": run.proposal_id,
        "policy_evaluation_id": run.policy_evaluation_id,
        "decision_ticket_id": run.decision_ticket_id,
        "signal_id": run.signal_id,
        "last_error_code": run.last_error_code,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "completed_at": run.completed_at,
        "version": run.version,
        "payload": json_compatible(run),
    }


def _attempt_values(attempt: MonitoringRunAttempt) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "run_id": attempt.run_id,
        "attempt_number": attempt.attempt_number,
        "lease_token": attempt.lease_token,
        "worker_id": attempt.worker_id,
        "status": attempt.status.value,
        "started_at": attempt.started_at,
        "finished_at": attempt.finished_at,
        "error_code": attempt.error_code,
        "retryable": attempt.retryable,
        "next_attempt_at": attempt.next_attempt_at,
        "details": json_compatible(attempt.details),
    }


def _run_from_row(row: sa.RowMapping) -> MonitoringRun:
    run = contract_from_payload(MonitoringRun, row["payload"])
    indexed = _run_values(run)
    for column, expected in indexed.items():
        if column == "payload":
            continue
        if row[column] != expected:
            raise MonitoringFactConflictError(
                f"MonitoringRun indexed column differs from payload: {column}"
            )
    return run


def _attempt_from_row(row: sa.RowMapping) -> MonitoringRunAttempt:
    return MonitoringRunAttempt(
        id=row["id"],
        run_id=row["run_id"],
        attempt_number=row["attempt_number"],
        lease_token=row["lease_token"],
        worker_id=row["worker_id"],
        status=MonitoringAttemptStatus(row["status"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_code=row["error_code"],
        retryable=row["retryable"],
        next_attempt_at=row["next_attempt_at"],
        details=row["details"],
    )
