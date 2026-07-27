"""Crypto WatchItem 与 MonitoringSubscription 应用用例。

业务描述:
    接收显式创建和生命周期命令，构造平台监控事实并委托 Repository 原子持久化。

业务场景:
    本地管理 CLI 创建 BTC-USDT H1 自选，或暂停、恢复、归档已有监控项。

业务原因:
    用户意图、稳定业务身份和命令边界属于应用层；SQL、Inbox、Outbox 与并发锁属于适配器。

调用链:
    CLI -> CryptoWatchlistService -> Repository -> PostgreSQL/Outbox

业务规则:
    V0.1 只接受 ACTIVE Crypto Instrument 和 H1；创建与变更命令必须携带 request_id。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from loot.contracts import (
    Instrument,
    InstrumentStatus,
    Market,
    MonitoringSubscription,
    PriceZone,
    Priority,
    SignalType,
    Timeframe,
    WatchItem,
    WatchItemStatus,
)
from loot.contracts.base import ensure_non_empty, ensure_utc_datetime
from loot.watchlist import WatchItemAction, build_monitoring_subscriptions


@dataclass(frozen=True, slots=True)
class CreateCryptoWatchItemCommand:
    """创建一个 Crypto WatchItem 及其派生订阅。"""

    request_id: UUID
    watch_item_id: UUID
    user_id: UUID
    instrument: Instrument
    occurred_at: datetime
    timeframes: tuple[Timeframe, ...] = (Timeframe.H1,)
    monitoring_profile: str = "crypto.structure-breakout.v1"
    enabled_signal_types: tuple[SignalType, ...] = (SignalType.MARKET_STRUCTURE,)
    custom_zones: tuple[PriceZone, ...] = field(default_factory=tuple)
    priority: Priority = Priority.NORMAL

    def __post_init__(self) -> None:
        """拒绝跨市场、未激活标的和 V0.1 未授权周期。"""

        ensure_utc_datetime(self.occurred_at)
        ensure_non_empty(self.monitoring_profile)
        if self.instrument.market != Market.CRYPTO:
            raise ValueError("REQ-0014 only supports CRYPTO instruments")
        if self.instrument.status != InstrumentStatus.ACTIVE:
            raise ValueError("WatchItem requires an ACTIVE instrument")
        if not self.timeframes or set(self.timeframes) != {Timeframe.H1}:
            raise ValueError("REQ-0014 only supports the H1 timeframe")
        if len(set(self.enabled_signal_types)) != len(self.enabled_signal_types):
            raise ValueError("enabled_signal_types must not contain duplicates")

    def as_payload(self) -> dict[str, Any]:
        """返回 Inbox 指纹所需的完整命令 payload。"""

        return {
            "request_id": str(self.request_id),
            "watch_item_id": str(self.watch_item_id),
            "user_id": str(self.user_id),
            "instrument": self.instrument.model_dump(mode="json"),
            "occurred_at": ensure_utc_datetime(self.occurred_at).isoformat(),
            "timeframes": [item.value for item in self.timeframes],
            "monitoring_profile": self.monitoring_profile,
            "enabled_signal_types": [item.value for item in self.enabled_signal_types],
            "custom_zones": [item.model_dump(mode="json") for item in self.custom_zones],
            "priority": self.priority.value,
        }


@dataclass(frozen=True, slots=True)
class ChangeWatchItemStatusCommand:
    """按期望版本执行一次 WatchItem 生命周期动作。"""

    request_id: UUID
    watch_item_id: UUID
    expected_version: int
    action: WatchItemAction
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.expected_version < 0:
            raise ValueError("expected_version must be non-negative")
        ensure_utc_datetime(self.occurred_at)

    def as_payload(self) -> dict[str, Any]:
        """返回 Inbox 指纹所需的完整命令 payload。"""

        return {
            "request_id": str(self.request_id),
            "watch_item_id": str(self.watch_item_id),
            "expected_version": self.expected_version,
            "action": self.action.value,
            "occurred_at": ensure_utc_datetime(self.occurred_at).isoformat(),
        }


@dataclass(frozen=True, slots=True)
class WatchlistMutationResult:
    """一次创建或生命周期命令的完整持久化结果。"""

    instrument: Instrument
    watch_item: WatchItem
    subscriptions: tuple[MonitoringSubscription, ...]
    duplicate: bool


@dataclass(frozen=True, slots=True)
class CryptoRunConfiguration:
    """Run-Once 或 Worker 可消费的已授权监控配置。"""

    instrument: Instrument
    watch_item: WatchItem
    subscription: MonitoringSubscription


class WatchlistRepository(Protocol):
    """Crypto Watchlist 应用服务依赖的持久化端口。"""

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
        """原子保存创建事实。"""

        ...

    def record_transition(
            self,
            command: ChangeWatchItemStatusCommand,
    ) -> WatchlistMutationResult:
        """原子保存生命周期迁移。"""

        ...

    def load_run_configuration(
            self,
            watch_item_id: UUID,
            timeframe: Timeframe,
    ) -> CryptoRunConfiguration:
        """加载 ACTIVE 的 Run-Once 配置。"""

        ...


class CryptoWatchlistService:
    """编排 Crypto WatchItem 创建和生命周期命令。

    业务描述:
        将外部命令转换为不可变 WatchItem/Subscription 契约，并调用事务 Repository。

    调用链:
        command -> validate/build facts -> Repository -> mutation result

    业务规则:
        应用层不直接写数据库；Subscription 完全由 WatchItem 派生，不能由调用方单独编辑。
    """

    def __init__(self, repository: WatchlistRepository) -> None:
        self._repository = repository

    def create(self, command: CreateCryptoWatchItemCommand) -> WatchlistMutationResult:
        """构造并原子保存一个 ACTIVE Crypto WatchItem。"""

        occurred_at = ensure_utc_datetime(command.occurred_at)
        watch_item = WatchItem(
            id=command.watch_item_id,
            user_id=command.user_id,
            instrument_id=command.instrument.instrument_id,
            market=command.instrument.market,
            venue=command.instrument.venue,
            status=WatchItemStatus.ACTIVE,
            timeframes=command.timeframes,
            monitoring_profile=command.monitoring_profile,
            enabled_signal_types=command.enabled_signal_types,
            custom_zones=command.custom_zones,
            priority=command.priority,
            created_at=occurred_at,
            updated_at=occurred_at,
            version=0,
        )
        subscriptions = build_monitoring_subscriptions(watch_item, occurred_at)
        return self._repository.record_creation(
            request_id=command.request_id,
            message_payload=command.as_payload(),
            instrument=command.instrument,
            watch_item=watch_item,
            subscriptions=subscriptions,
            occurred_at=occurred_at,
        )

    def change_status(
            self,
            command: ChangeWatchItemStatusCommand,
    ) -> WatchlistMutationResult:
        """提交一次暂停、恢复或归档命令。"""

        return self._repository.record_transition(command)

    def load_run_configuration(
            self,
            watch_item_id: UUID,
            timeframe: Timeframe = Timeframe.H1,
    ) -> CryptoRunConfiguration:
        """加载可执行 Run-Once 的 ACTIVE 配置。"""

        return self._repository.load_run_configuration(watch_item_id, timeframe)
