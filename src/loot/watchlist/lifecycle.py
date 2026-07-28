"""WatchItem 与 MonitoringSubscription 的确定性生命周期规则。

业务描述:
    从 WatchItem 配置派生稳定订阅，并在暂停、恢复、归档时同步更新所有订阅投影。

业务场景:
    创建 Crypto 自选后生成 H1 调度入口；用户调整生命周期时阻止 Worker 消费失效配置。

业务原因:
    生命周期真假必须由确定性规则和版本控制拥有，不能由 CLI、Repository 或未来 Agent
    各自解释。

调用链:
    Application Command -> lifecycle rule -> Repository transaction -> Outbox

业务规则:
    ARCHIVED 是终态；版本必须精确匹配；订阅 ID 与 route_key 由稳定身份生成。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from loot.contracts import (
    Market,
    MonitoringSubscription,
    MonitoringSubscriptionStatus,
    WatchItem,
    WatchItemStatus,
)
from loot.contracts.base import ensure_utc_datetime


class WatchItemAction(StrEnum):
    """允许用户发起的 WatchItem 生命周期动作。"""

    PAUSE = "PAUSE"
    RESUME = "RESUME"
    ARCHIVE = "ARCHIVE"


_TARGET_STATUS = {
    WatchItemAction.PAUSE: WatchItemStatus.PAUSED,
    WatchItemAction.RESUME: WatchItemStatus.ACTIVE,
    WatchItemAction.ARCHIVE: WatchItemStatus.ARCHIVED,
}

_ALLOWED_ACTIONS = {
    WatchItemStatus.ACTIVE: {WatchItemAction.PAUSE, WatchItemAction.ARCHIVE},
    WatchItemStatus.PAUSED: {WatchItemAction.RESUME, WatchItemAction.ARCHIVE},
    WatchItemStatus.ARCHIVED: set(),
}

_SUBSCRIPTION_STATUS = {
    WatchItemStatus.ACTIVE: MonitoringSubscriptionStatus.ACTIVE,
    WatchItemStatus.PAUSED: MonitoringSubscriptionStatus.PAUSED,
    WatchItemStatus.ARCHIVED: MonitoringSubscriptionStatus.ARCHIVED,
}


def build_monitoring_subscriptions(
        watch_item: WatchItem,
        occurred_at: datetime,
) -> tuple[MonitoringSubscription, ...]:
    """为 WatchItem 的每个周期构造稳定派生订阅。

    调用链:
        create WatchItem -> stable subscription identity -> Repository
    """

    normalized_time = ensure_utc_datetime(occurred_at)
    return tuple(
        MonitoringSubscription(
            id=uuid5(
                NAMESPACE_URL,
                f"loot.monitoring:{watch_item.id}:{timeframe.value}",
            ),
            watch_item_id=watch_item.id,
            market=watch_item.market,
            instrument_id=watch_item.instrument_id,
            timeframe=timeframe,
            route_key=(
                f"{watch_item.market.value.lower()}:"
                f"{watch_item.instrument_id}:{timeframe.value}"
            ),
            next_run_at=None,
            status=_SUBSCRIPTION_STATUS[watch_item.status],
            config_version=1,
            created_at=normalized_time,
            updated_at=normalized_time,
        )
        for timeframe in watch_item.timeframes
    )


def transition_watch_item(
        watch_item: WatchItem,
        subscriptions: tuple[MonitoringSubscription, ...],
        *,
        action: WatchItemAction,
        expected_version: int,
        occurred_at: datetime,
) -> tuple[WatchItem, tuple[MonitoringSubscription, ...]]:
    """执行一次版本化生命周期迁移并重新校验完整契约。

    状态流转:
        ACTIVE -> PAUSED/ARCHIVED | PAUSED -> ACTIVE/ARCHIVED

    幂等策略:
        request_id 重投由 Repository Inbox/Outbox 处理；本函数只接受首次有效迁移。
    """

    normalized_time = ensure_utc_datetime(occurred_at)
    if watch_item.market != Market.CRYPTO:
        raise ValueError("REQ-0014 only supports CRYPTO WatchItems")
    if watch_item.version != expected_version:
        raise ValueError("watch_item version does not match expected_version")
    if normalized_time < watch_item.updated_at:
        raise ValueError("occurred_at must not be earlier than watch_item.updated_at")
    if action not in _ALLOWED_ACTIONS[watch_item.status]:
        raise ValueError(
            f"{action.value} is not allowed from {watch_item.status.value}"
        )

    expected_timeframes = set(watch_item.timeframes)
    actual_timeframes = {item.timeframe for item in subscriptions}
    if actual_timeframes != expected_timeframes or len(subscriptions) != len(expected_timeframes):
        raise ValueError("subscriptions must match WatchItem timeframes exactly")
    if any(item.watch_item_id != watch_item.id for item in subscriptions):
        raise ValueError("subscriptions must belong to the WatchItem")

    target_status = _TARGET_STATUS[action]
    updated_watch_item = WatchItem.model_validate(
        {
            **watch_item.model_dump(),
            "status": target_status,
            "updated_at": normalized_time,
            "version": watch_item.version + 1,
        }
    )
    updated_subscriptions = tuple(
        MonitoringSubscription.model_validate(
            {
                **item.model_dump(),
                "status": _SUBSCRIPTION_STATUS[target_status],
                "next_run_at": None,
                "config_version": item.config_version + 1,
                "updated_at": normalized_time,
            }
        )
        for item in subscriptions
    )
    return updated_watch_item, updated_subscriptions
