"""Crypto WatchItem 与 MonitoringSubscription PostgreSQL Repository。

业务描述:
    在一个事务中保存 Instrument、WatchItem、派生 Subscription、Inbox 和 Outbox，并加载
    Run-Once 可使用的 ACTIVE 监控配置。

业务场景:
    本地管理命令创建或变更 Crypto WatchItem；Run-Once 和未来 Worker 读取持久化配置。

业务原因:
    命令重投、并发恢复和进程重启不能产生重复监控身份或让 WatchItem 与 Subscription 状态漂移。

调用链:
    CryptoWatchlistService -> PostgresWatchlistRepository -> PostgreSQL/Outbox

业务规则:
    所有写操作复用 Inbox 幂等；生命周期使用行锁和 expected_version；ARCHIVED 不可恢复；
    重投从首次 Outbox 事件恢复结果。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from loot.application.watchlist import (
    ChangeWatchItemStatusCommand,
    CryptoRunConfiguration,
    WatchlistMutationResult,
)
from loot.contracts import (
    EventEnvelope,
    Instrument,
    InstrumentStatus,
    Market,
    MonitoringSubscription,
    MonitoringSubscriptionStatus,
    Timeframe,
    WatchItem,
    WatchItemStatus,
)
from loot.contracts.base import ensure_utc_datetime
from loot.contracts.serialization import json_compatible, payload_fingerprint
from loot.persistence.locking import acquire_advisory_locks
from loot.persistence.mappers import (
    contract_from_payload,
    instrument_values,
    subscription_values,
    validate_stored_fingerprint,
    watch_item_values,
)
from loot.persistence.outbox import (
    OutboxMessage,
    build_outbox_message,
    insert_outbox_message,
)
from loot.persistence.schema import (
    inbox_messages,
    instruments,
    monitoring_subscriptions,
    outbox_events,
    watch_items,
)
from loot.watchlist import WatchItemAction, transition_watch_item

_CONSUMER_NAME = "loot.application.crypto_watchlist.v1"
_EVENT_TYPE_BY_ACTION = {
    WatchItemAction.PAUSE: "loot.watchlist.WatchItemPaused",
    WatchItemAction.RESUME: "loot.watchlist.WatchItemResumed",
    WatchItemAction.ARCHIVE: "loot.watchlist.WatchItemArchived",
}


class WatchlistPersistenceError(RuntimeError):
    """Watchlist 持久化基类错误。"""


class WatchlistFactConflictError(WatchlistPersistenceError):
    """稳定业务身份已经绑定不同事实。"""


class ActiveWatchItemConflictError(WatchlistPersistenceError):
    """相同用户、Instrument 和 profile 已有 ACTIVE WatchItem。"""


class WatchItemNotFoundError(WatchlistPersistenceError):
    """目标 WatchItem 不存在。"""


class WatchItemVersionConflictError(WatchlistPersistenceError):
    """WatchItem expected_version 已过期。"""


class WatchItemTransitionError(WatchlistPersistenceError):
    """WatchItem 生命周期动作不合法。"""


class WatchItemNotRunnableError(WatchlistPersistenceError):
    """WatchItem、Instrument 或 Subscription 当前不可运行。"""


class PostgresWatchlistRepository:
    """持久化 Crypto WatchItem 与派生订阅。

    业务描述:
        提供创建、生命周期迁移和 ACTIVE 运行配置读取三个原子边界。

    调用链:
        Application -> Inbox/locks -> facts -> Outbox -> commit

    幂等与补偿:
        相同 request_id/payload 返回首次事件投影；事务失败整体回滚，由调用方重投原命令。
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record_creation(
            self,
            *,
            request_id: UUID,
            message_payload: Any,
            instrument: Instrument,
            watch_item: WatchItem,
            subscriptions: tuple[MonitoringSubscription, ...],
            occurred_at: datetime,
    ) -> WatchlistMutationResult:
        """原子创建 Instrument、WatchItem、Subscription 和事件。"""

        normalized_time = ensure_utc_datetime(occurred_at)
        self._validate_creation(instrument, watch_item, subscriptions)
        message_fingerprint = payload_fingerprint(message_payload)
        event_type = "loot.watchlist.WatchItemCreated"
        result_event_id = _event_id(request_id, event_type, watch_item.id)

        with self._engine.begin() as connection:
            acquire_advisory_locks(
                connection,
                f"inbox:{_CONSUMER_NAME}:{request_id}",
                _active_watch_item_lock_identity(watch_item),
                f"instrument-id:{instrument.instrument_id}",
                _instrument_natural_lock_identity(instrument),
            )
            duplicate = self._claim_inbox(
                connection,
                request_id=request_id,
                message_fingerprint=message_fingerprint,
                received_at=normalized_time,
            )
            if duplicate:
                return self._result_from_event(connection, result_event_id)

            self._ensure_instrument(connection, instrument)
            if connection.execute(
                    sa.select(watch_items.c.id).where(watch_items.c.id == watch_item.id)
            ).scalar_one_or_none() is not None:
                raise WatchlistFactConflictError(
                    "watch_item_id already exists for a different request"
                )
            active_id = connection.execute(
                sa.select(watch_items.c.id).where(
                    watch_items.c.user_id == watch_item.user_id,
                    watch_items.c.instrument_id == watch_item.instrument_id,
                    watch_items.c.monitoring_profile == watch_item.monitoring_profile,
                    watch_items.c.status == WatchItemStatus.ACTIVE.value,
                )
            ).scalar_one_or_none()
            if active_id is not None:
                raise ActiveWatchItemConflictError(
                    "an ACTIVE WatchItem already exists for this identity"
                )

            connection.execute(sa.insert(watch_items).values(**watch_item_values(watch_item)))
            connection.execute(
                sa.insert(monitoring_subscriptions),
                [subscription_values(item) for item in subscriptions],
            )
            result = WatchlistMutationResult(
                instrument=instrument,
                watch_item=watch_item,
                subscriptions=subscriptions,
                duplicate=False,
            )
            insert_outbox_message(
                connection,
                self._result_event(
                    result_event_id,
                    event_type=event_type,
                    request_id=request_id,
                    result=result,
                    occurred_at=normalized_time,
                ),
            )
            for subscription in subscriptions:
                insert_outbox_message(
                    connection,
                    self._subscription_event(
                        request_id=request_id,
                        event_type="loot.monitoring.SubscriptionConfigured",
                        subscription=subscription,
                        occurred_at=normalized_time,
                    ),
                )
            self._mark_inbox_processed(connection, request_id, normalized_time)
            return result

    def record_transition(
            self,
            command: ChangeWatchItemStatusCommand,
    ) -> WatchlistMutationResult:
        """按行锁和 expected_version 原子迁移 WatchItem 与全部订阅。"""

        normalized_time = ensure_utc_datetime(command.occurred_at)
        event_type = _EVENT_TYPE_BY_ACTION[command.action]
        result_event_id = _event_id(command.request_id, event_type, command.watch_item_id)

        with self._engine.begin() as connection:
            acquire_advisory_locks(
                connection,
                f"inbox:{_CONSUMER_NAME}:{command.request_id}",
                f"watch-item:{command.watch_item_id}",
            )
            duplicate = self._claim_inbox(
                connection,
                request_id=command.request_id,
                message_fingerprint=payload_fingerprint(command.as_payload()),
                received_at=normalized_time,
            )
            if duplicate:
                return self._result_from_event(connection, result_event_id)

            instrument, watch_item, subscriptions = self._load_projection(
                connection,
                command.watch_item_id,
                for_update=True,
            )
            if command.action == WatchItemAction.RESUME:
                acquire_advisory_locks(
                    connection,
                    _active_watch_item_lock_identity(watch_item),
                )
                conflicting_active_id = connection.execute(
                    sa.select(watch_items.c.id).where(
                        watch_items.c.user_id == watch_item.user_id,
                        watch_items.c.instrument_id == watch_item.instrument_id,
                        watch_items.c.monitoring_profile == watch_item.monitoring_profile,
                        watch_items.c.status == WatchItemStatus.ACTIVE.value,
                        watch_items.c.id != watch_item.id,
                    )
                ).scalar_one_or_none()
                if conflicting_active_id is not None:
                    raise ActiveWatchItemConflictError(
                        "another ACTIVE WatchItem already exists for this identity"
                    )
            if watch_item.version != command.expected_version:
                raise WatchItemVersionConflictError(
                    "watch_item version does not match expected_version"
                )
            try:
                updated_watch_item, updated_subscriptions = transition_watch_item(
                    watch_item,
                    subscriptions,
                    action=command.action,
                    expected_version=command.expected_version,
                    occurred_at=normalized_time,
                )
            except ValueError as exc:
                raise WatchItemTransitionError(str(exc)) from exc

            updated_count = connection.execute(
                sa.update(watch_items)
                .where(
                    watch_items.c.id == watch_item.id,
                    watch_items.c.version == command.expected_version,
                )
                .values(
                    status=updated_watch_item.status.value,
                    updated_at=updated_watch_item.updated_at,
                    version=updated_watch_item.version,
                    payload=json_compatible(updated_watch_item),
                )
            ).rowcount
            if updated_count != 1:
                raise WatchItemVersionConflictError("watch_item version changed concurrently")
            for previous, updated in zip(
                    subscriptions,
                    updated_subscriptions,
                    strict=True,
            ):
                updated_count = connection.execute(
                    sa.update(monitoring_subscriptions)
                    .where(
                        monitoring_subscriptions.c.id == previous.id,
                        monitoring_subscriptions.c.config_version == previous.config_version,
                    )
                    .values(
                        next_run_at=updated.next_run_at,
                        status=updated.status.value,
                        config_version=updated.config_version,
                        updated_at=updated.updated_at,
                        payload=json_compatible(updated),
                    )
                ).rowcount
                if updated_count != 1:
                    raise WatchItemVersionConflictError(
                        "subscription config_version changed concurrently"
                    )

            result = WatchlistMutationResult(
                instrument=instrument,
                watch_item=updated_watch_item,
                subscriptions=updated_subscriptions,
                duplicate=False,
            )
            insert_outbox_message(
                connection,
                self._result_event(
                    result_event_id,
                    event_type=event_type,
                    request_id=command.request_id,
                    result=result,
                    occurred_at=normalized_time,
                ),
            )
            for subscription in updated_subscriptions:
                insert_outbox_message(
                    connection,
                    self._subscription_event(
                        request_id=command.request_id,
                        event_type="loot.monitoring.SubscriptionStatusChanged",
                        subscription=subscription,
                        occurred_at=normalized_time,
                    ),
                )
            self._mark_inbox_processed(connection, command.request_id, normalized_time)
            return result

    def load_run_configuration(
            self,
            watch_item_id: UUID,
            timeframe: Timeframe,
    ) -> CryptoRunConfiguration:
        """在只读事务中加载可运行的 Crypto 监控配置。"""

        with self._engine.connect() as connection:
            with connection.begin():
                connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                instrument, watch_item, subscriptions = self._load_projection(
                    connection,
                    watch_item_id,
                    for_update=False,
                )
        matching = tuple(item for item in subscriptions if item.timeframe == timeframe)
        if len(matching) != 1:
            raise WatchItemNotRunnableError(
                "WatchItem does not have exactly one subscription for the timeframe"
            )
        subscription = matching[0]
        if (
                instrument.market != Market.CRYPTO
                or instrument.status != InstrumentStatus.ACTIVE
                or watch_item.market != Market.CRYPTO
                or watch_item.status != WatchItemStatus.ACTIVE
                or subscription.status != MonitoringSubscriptionStatus.ACTIVE
        ):
            raise WatchItemNotRunnableError("monitoring configuration is not ACTIVE")
        return CryptoRunConfiguration(
            instrument=instrument,
            watch_item=watch_item,
            subscription=subscription,
        )

    @staticmethod
    def _validate_creation(
            instrument: Instrument,
            watch_item: WatchItem,
            subscriptions: tuple[MonitoringSubscription, ...],
    ) -> None:
        """校验创建事务中三个契约层级完全一致。"""

        if instrument.market != Market.CRYPTO or instrument.status != InstrumentStatus.ACTIVE:
            raise ValueError("creation requires an ACTIVE CRYPTO instrument")
        if (
                watch_item.market != instrument.market
                or watch_item.instrument_id != instrument.instrument_id
                or watch_item.venue != instrument.venue
                or watch_item.status != WatchItemStatus.ACTIVE
                or watch_item.version != 0
        ):
            raise ValueError("WatchItem must match the ACTIVE instrument and initial state")
        expected_timeframes = set(watch_item.timeframes)
        actual_timeframes = {item.timeframe for item in subscriptions}
        if actual_timeframes != expected_timeframes or len(subscriptions) != len(expected_timeframes):
            raise ValueError("subscriptions must match WatchItem timeframes exactly")
        if any(
                item.watch_item_id != watch_item.id
                or item.instrument_id != instrument.instrument_id
                or item.market != Market.CRYPTO
                or item.status != MonitoringSubscriptionStatus.ACTIVE
                or item.config_version != 1
                for item in subscriptions
        ):
            raise ValueError("subscriptions must be initial ACTIVE WatchItem projections")

    @staticmethod
    def _claim_inbox(
            connection: Connection,
            *,
            request_id: UUID,
            message_fingerprint: str,
            received_at: datetime,
    ) -> bool:
        """认领命令 Inbox，并区分一致重投与 request_id 冲突。"""

        row = connection.execute(
            sa.select(inbox_messages)
            .where(
                inbox_messages.c.consumer_name == _CONSUMER_NAME,
                inbox_messages.c.message_id == request_id,
            )
            .with_for_update()
        ).mappings().one_or_none()
        if row is not None:
            if row["payload_fingerprint"] != message_fingerprint:
                raise WatchlistFactConflictError(
                    "request_id was reused with a different command payload"
                )
            return row["status"] == "PROCESSED"
        connection.execute(
            sa.insert(inbox_messages).values(
                consumer_name=_CONSUMER_NAME,
                message_id=request_id,
                payload_fingerprint=message_fingerprint,
                received_at=received_at,
                status="RECEIVED",
            )
        )
        return False

    @staticmethod
    def _mark_inbox_processed(
            connection: Connection,
            request_id: UUID,
            processed_at: datetime,
    ) -> None:
        connection.execute(
            sa.update(inbox_messages)
            .where(
                inbox_messages.c.consumer_name == _CONSUMER_NAME,
                inbox_messages.c.message_id == request_id,
            )
            .values(status="PROCESSED", processed_at=processed_at, last_error=None)
        )

    @staticmethod
    def _ensure_instrument(connection: Connection, instrument: Instrument) -> None:
        """插入 Instrument，或验证稳定 ID/自然身份对应同一事实。"""

        rows = connection.execute(
            sa.select(instruments).where(
                sa.or_(
                    instruments.c.instrument_id == instrument.instrument_id,
                    sa.and_(
                        instruments.c.market == instrument.market.value,
                        instruments.c.venue == instrument.venue,
                        instruments.c.symbol == instrument.symbol,
                        instruments.c.instrument_type == instrument.instrument_type.value,
                    ),
                )
            )
        ).mappings().all()
        if rows:
            if len(rows) != 1:
                raise WatchlistFactConflictError(
                    "instrument ID and natural identity resolve to different facts"
                )
            stored = _instrument_from_row(rows[0])
            if stored != instrument:
                raise WatchlistFactConflictError(
                    "instrument identity already exists with a different payload"
                )
            return
        connection.execute(sa.insert(instruments).values(**instrument_values(instrument)))

    @staticmethod
    def _load_projection(
            connection: Connection,
            watch_item_id: UUID,
            *,
            for_update: bool,
    ) -> tuple[Instrument, WatchItem, tuple[MonitoringSubscription, ...]]:
        query = sa.select(watch_items).where(watch_items.c.id == watch_item_id)
        if for_update:
            query = query.with_for_update()
        row = connection.execute(query).mappings().one_or_none()
        if row is None:
            raise WatchItemNotFoundError("WatchItem does not exist")
        watch_item = _watch_item_from_row(row)
        instrument_row = connection.execute(
            sa.select(instruments).where(
                instruments.c.instrument_id == watch_item.instrument_id
            )
        ).mappings().one()
        subscription_query = (
            sa.select(monitoring_subscriptions)
            .where(monitoring_subscriptions.c.watch_item_id == watch_item.id)
            .order_by(monitoring_subscriptions.c.timeframe)
        )
        if for_update:
            subscription_query = subscription_query.with_for_update()
        subscription_rows = connection.execute(subscription_query).mappings().all()
        return (
            _instrument_from_row(instrument_row),
            watch_item,
            tuple(_subscription_from_row(item) for item in subscription_rows),
        )

    @staticmethod
    def _result_event(
            event_id: UUID,
            *,
            event_type: str,
            request_id: UUID,
            result: WatchlistMutationResult,
            occurred_at: datetime,
    ) -> OutboxMessage:
        return build_outbox_message(
            event_id=event_id,
            event_type=event_type,
            producer="loot.persistence.watchlist",
            aggregate_type="WatchItem",
            aggregate_id=result.watch_item.id,
            correlation_id=request_id,
            causation_id=request_id,
            partition_key=str(result.watch_item.id),
            payload=_result_payload(result),
            occurred_at=occurred_at,
        )

    @staticmethod
    def _subscription_event(
            *,
            request_id: UUID,
            event_type: str,
            subscription: MonitoringSubscription,
            occurred_at: datetime,
    ) -> OutboxMessage:
        return build_outbox_message(
            event_id=_event_id(request_id, event_type, subscription.id),
            event_type=event_type,
            producer="loot.persistence.watchlist",
            aggregate_type="MonitoringSubscription",
            aggregate_id=subscription.id,
            correlation_id=request_id,
            causation_id=request_id,
            partition_key=subscription.route_key,
            payload={"subscription": json_compatible(subscription)},
            occurred_at=occurred_at,
        )

    @staticmethod
    def _result_from_event(
            connection: Connection,
            event_id: UUID,
    ) -> WatchlistMutationResult:
        row = connection.execute(
            sa.select(outbox_events.c.payload).where(outbox_events.c.event_id == event_id)
        ).scalar_one_or_none()
        if row is None:
            raise WatchlistFactConflictError(
                "processed command is missing its result Outbox event"
            )
        event = EventEnvelope.model_validate(row)
        payload = event.payload
        return WatchlistMutationResult(
            instrument=Instrument.model_validate(payload["instrument"]),
            watch_item=WatchItem.model_validate(payload["watch_item"]),
            subscriptions=tuple(
                MonitoringSubscription.model_validate(item)
                for item in payload["subscriptions"]
            ),
            duplicate=True,
        )


def _event_id(request_id: UUID, event_type: str, aggregate_id: UUID) -> UUID:
    """按命令、事件类型和聚合生成稳定 Outbox event_id。"""

    return uuid5(NAMESPACE_URL, f"{request_id}:{event_type}:{aggregate_id}")


def _active_watch_item_lock_identity(watch_item: WatchItem) -> str:
    """返回 ACTIVE 唯一约束对应的事务锁身份。"""

    return (
        "watch-item-active:"
        f"{watch_item.user_id}:{watch_item.instrument_id}:"
        f"{watch_item.monitoring_profile}"
    )


def _instrument_natural_lock_identity(instrument: Instrument) -> str:
    """返回 Instrument 自然唯一约束对应的事务锁身份。"""

    return (
        f"instrument-natural:{instrument.market.value}:{instrument.venue}:"
        f"{instrument.symbol}:{instrument.instrument_type.value}"
    )


def _result_payload(result: WatchlistMutationResult) -> dict[str, Any]:
    return {
        "instrument": json_compatible(result.instrument),
        "watch_item": json_compatible(result.watch_item),
        "subscriptions": [json_compatible(item) for item in result.subscriptions],
    }


def _instrument_from_row(row: sa.RowMapping) -> Instrument:
    instrument = contract_from_payload(Instrument, row["payload"])
    validate_stored_fingerprint(row["payload_fingerprint"], instrument)
    if (
            instrument.instrument_id != row["instrument_id"]
            or instrument.market.value != row["market"]
            or instrument.venue != row["venue"]
            or instrument.symbol != row["symbol"]
            or instrument.instrument_type.value != row["instrument_type"]
            or instrument.status.value != row["status"]
    ):
        raise WatchlistFactConflictError(
            "Instrument indexed columns differ from validated payload"
        )
    return instrument


def _watch_item_from_row(row: sa.RowMapping) -> WatchItem:
    watch_item = contract_from_payload(WatchItem, row["payload"])
    if (
            watch_item.id != row["id"]
            or watch_item.user_id != row["user_id"]
            or watch_item.instrument_id != row["instrument_id"]
            or watch_item.market.value != row["market"]
            or watch_item.status.value != row["status"]
            or watch_item.version != row["version"]
    ):
        raise WatchlistFactConflictError(
            "WatchItem indexed columns differ from validated payload"
        )
    return watch_item


def _subscription_from_row(row: sa.RowMapping) -> MonitoringSubscription:
    subscription = contract_from_payload(MonitoringSubscription, row["payload"])
    if (
            subscription.id != row["id"]
            or subscription.watch_item_id != row["watch_item_id"]
            or subscription.instrument_id != row["instrument_id"]
            or subscription.timeframe.value != row["timeframe"]
            or subscription.route_key != row["route_key"]
            or subscription.status.value != row["status"]
            or subscription.config_version != row["config_version"]
    ):
        raise WatchlistFactConflictError(
            "Subscription indexed columns differ from validated payload"
        )
    return subscription
