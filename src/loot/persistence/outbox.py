"""PostgreSQL Outbox 写入和未发布事实查询。

业务描述:
    把领域事件信封与业务事实放在同一数据库事务中，并提供按可用时间查询未发布事件的
    恢复入口。

业务场景:
    Analysis、Policy 和 Signal workflow 写入 Outbox；后续 dispatcher 从未发布查询恢复。

业务原因:
    业务事务成功但消息发送失败时，事件必须仍可从 PostgreSQL 找回，不能依赖进程内存。

调用链:
    Domain transaction -> insert_outbox_message
    Dispatcher/recovery -> PostgresOutboxRepository.list_unpublished

业务规则:
    event_id 相同且完整消息一致视为幂等；payload 不同按不可变事实冲突拒绝。本需求不
    实现认领、发送或确认发布调度器。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from loot.contracts import EventEnvelope
from loot.contracts.base import ensure_non_empty, ensure_utc_datetime
from loot.contracts.serialization import json_compatible
from loot.persistence.schema import outbox_events


class OutboxConflictError(ValueError):
    """相同 event_id 对应了不同的不可变 Outbox 消息。"""


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    """Outbox 表所需的领域事件和聚合路由信息。"""

    event: EventEnvelope
    aggregate_type: str
    aggregate_id: UUID
    available_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "aggregate_type",
            ensure_non_empty(self.aggregate_type),
        )
        object.__setattr__(
            self,
            "available_at",
            ensure_utc_datetime(self.available_at),
        )


def build_outbox_message(
        *,
        event_id: UUID,
        event_type: str,
        producer: str,
        aggregate_type: str,
        aggregate_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None,
        partition_key: str,
        payload: dict[str, Any],
        occurred_at: datetime,
        available_at: datetime | None = None,
) -> OutboxMessage:
    """构造完整版本化事件信封和 Outbox 路由信息。"""

    normalized_time = ensure_utc_datetime(occurred_at)
    return OutboxMessage(
        event=EventEnvelope(
            event_id=event_id,
            event_type=event_type,
            event_version=1,
            occurred_at=normalized_time,
            producer=producer,
            correlation_id=correlation_id,
            causation_id=causation_id,
            partition_key=partition_key,
            payload=payload,
        ),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        available_at=available_at or normalized_time,
    )


def insert_outbox_message(
        connection: Connection,
        message: OutboxMessage,
) -> bool:
    """写入 Outbox 消息；完全一致的已存在消息返回 False。"""

    existing = connection.execute(
        sa.select(outbox_events).where(
            outbox_events.c.event_id == message.event.event_id
        )
    ).mappings().one_or_none()
    if existing is not None:
        if _message_from_row(existing) != message:
            raise OutboxConflictError(
                "outbox event ID already exists with a different payload"
            )
        return False

    event = message.event
    connection.execute(
        sa.insert(outbox_events).values(
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            aggregate_type=message.aggregate_type,
            aggregate_id=message.aggregate_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            partition_key=event.partition_key,
            payload=json_compatible(event),
            occurred_at=event.occurred_at,
            available_at=message.available_at,
        )
    )
    return True


class PostgresOutboxRepository:
    """只读 Outbox 恢复仓库。

    业务描述:
        查询已经可用但尚未发布的事件事实，供 dispatcher 或人工恢复检查使用。

    调用链:
        recovery/dispatcher -> list_unpublished -> ordered OutboxMessage

    业务规则:
        查询不修改认领字段；真实并发认领将在后续 dispatcher 需求中使用
        `FOR UPDATE SKIP LOCKED` 单独实现。
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_unpublished(
            self,
            *,
            limit: int = 100,
            available_at: datetime | None = None,
    ) -> tuple[OutboxMessage, ...]:
        """按 available_at、occurred_at 返回未发布消息。"""

        if limit < 1:
            raise ValueError("limit must be positive")
        cutoff = ensure_utc_datetime(available_at or datetime.now(UTC))
        query = (
            sa.select(outbox_events)
            .where(
                outbox_events.c.published_at.is_(None),
                outbox_events.c.available_at <= cutoff,
            )
            .order_by(
                outbox_events.c.available_at,
                outbox_events.c.occurred_at,
                outbox_events.c.event_id,
            )
            .limit(limit)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return tuple(_message_from_row(row) for row in rows)


def _message_from_row(row: sa.RowMapping) -> OutboxMessage:
    """从数据库行恢复并重新校验完整事件信封。"""

    event = EventEnvelope.model_validate(row["payload"])
    if (
            event.event_id != row["event_id"]
            or event.event_type != row["event_type"]
            or event.event_version != row["event_version"]
            or event.correlation_id != row["correlation_id"]
            or event.causation_id != row["causation_id"]
            or event.partition_key != row["partition_key"]
            or event.occurred_at != row["occurred_at"]
    ):
        raise OutboxConflictError("outbox indexed columns differ from event payload")
    return OutboxMessage(
        event=event,
        aggregate_type=row["aggregate_type"],
        aggregate_id=row["aggregate_id"],
        available_at=row["available_at"],
    )
