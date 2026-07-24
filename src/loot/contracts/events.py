"""跨模块事件信封契约。

业务描述:
    统一所有生产者和消费者之间的事件外壳，承载版本、链路追踪和分区信息。

业务场景:
    - WatchItem、PositionEvent、CandidateEvent、SignalEvent 等领域事实发布。
    - Replay 和 Golden Case 复盘时按事件链重放业务路径。
    - 消费者基于 event_id、correlation_id 和 partition_key 做幂等处理。

调用链:
    Domain Producer -> EventEnvelope -> Outbox/Stream -> Consumer -> Projection

业务规则:
    - event_version 从 1 开始，事件升级必须显式演进。
    - occurred_at 必须是 timezone-aware UTC 时间。
    - producer、event_type 和 partition_key 不能为空。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from loot.contracts.base import ContractModel, ensure_non_empty, ensure_utc_datetime


class EventEnvelope(ContractModel):
    """至少一次投递场景下的版本化事件信封。

    业务描述:
        为领域事件提供统一外壳，让消费者可以在不理解 payload 细节前先完成
        路由、去重、追踪和回放。

    调用链:
        build domain event -> wrap EventEnvelope -> publish -> consume -> dedupe

    业务规则:
        所有事件生产者必须写入 correlation_id；重放和排障依赖它串起完整链路。
    """

    event_id: UUID
    event_type: str
    event_version: int = Field(ge=1)
    occurred_at: datetime
    producer: str
    correlation_id: UUID
    causation_id: UUID | None = None
    partition_key: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type", "producer", "partition_key")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)
