"""行情数据契约。

业务描述:
    定义 Provider 标准化后的 K 线和行情快照，作为市场领域预筛选的输入事实。

业务场景:
    - Crypto Provider 拉取交易所 K 线后转换为统一 MarketBar。
    - PreFilter 基于 MarketSnapshot 判断是否产生 CandidateEvent。
    - Replay 使用相同快照复现候选、证据和 Signal 状态迁移。

业务原因:
    外部行情源字段格式、时区和完成状态不同，必须先进入强类型契约，再允许
    Market Domain、Skill 或 Replay 消费。

调用链:
    Provider -> MarketBar -> MarketSnapshot -> PreFilter -> CandidateEvent

业务规则:
    - 时间统一归一化为 UTC aware datetime。
    - OHLC 必须满足 high/low 包含 open/close。
    - 快照内所有 K 线必须属于同一市场、标的和周期。
    - provider_event_id 和 snapshot_key 是后续幂等与 replay 的关键输入。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from loot.contracts.base import ContractModel, ensure_non_empty, ensure_utc_datetime
from loot.contracts.enums import Market, Timeframe


class MarketBar(ContractModel):
    """标准化 K 线。

    业务描述:
        表达某个 Provider 在一个固定周期内给出的 OHLCV 事实。

    业务场景:
        - Crypto REST Provider 把交易所原始数组转换为统一 K 线。
        - FakeProvider 生成确定性 K 线，用于 Golden Case 和本地闭环。
        - PreFilter 判断突破、回踩、量能异常和结构变化。

    业务原因:
        只有先把外部数据压到稳定契约里，后续策略和 replay 才不会依赖交易所
        私有字段顺序。

    调用链:
        Raw Provider Payload -> MarketBar -> MarketSnapshot -> PreFilter

    业务规则:
        provider、provider_event_id、venue、symbol 不能为空；价格必须为正；
        成交量不能为负；closed_at 必须晚于 opened_at。
    """

    id: UUID
    provider: str
    provider_event_id: str
    market: Market
    instrument_id: UUID
    venue: str
    symbol: str
    timeframe: Timeframe
    opened_at: datetime
    closed_at: datetime
    open_price: Decimal = Field(gt=0)
    high_price: Decimal = Field(gt=0)
    low_price: Decimal = Field(gt=0)
    close_price: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    quote_volume: Decimal | None = Field(default=None, ge=0)
    is_closed: bool
    received_at: datetime

    @field_validator("provider", "provider_event_id", "venue", "symbol")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("opened_at", "closed_at", "received_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _bar_shape_is_valid(self) -> "MarketBar":
        # 决策: 零长度或倒置周期会让同一 K 线桶的幂等键失去意义。
        if self.closed_at <= self.opened_at:
            raise ValueError("closed_at must be later than opened_at")

        if self.received_at < self.opened_at:
            raise ValueError("received_at must not be earlier than opened_at")

        # 决策: high/low 不包住 open/close 时，突破和回踩判断会出现假信号。
        highest_observed = max(self.open_price, self.close_price, self.low_price)
        if self.high_price < highest_observed:
            raise ValueError("high_price must cover open_price, close_price, and low_price")

        lowest_observed = min(self.open_price, self.close_price, self.high_price)
        if self.low_price > lowest_observed:
            raise ValueError("low_price must cover open_price, close_price, and high_price")

        return self


class MarketSnapshot(ContractModel):
    """某个标的在一个周期上的行情快照。

    业务描述:
        聚合一组已经标准化的 K 线，作为一次预筛选、Skill 或 Replay 的输入快照。

    业务场景:
        - Provider 周期性拉取最近 N 根 K 线。
        - PreFilter 用最近窗口判断是否产生 CandidateEvent。
        - Replay 用 snapshot_key 对比规则变更前后的结果。

    业务原因:
        单根 K 线不足以表达结构变化，快照需要保证窗口内数据身份一致、顺序稳定。

    调用链:
        Provider.fetch_recent_bars -> MarketSnapshot -> PreFilter -> CandidateEvent

    业务规则:
        bars 必须按 opened_at 升序排列；同一快照内 provider_event_id 不能重复。
    """

    id: UUID
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    source_provider: str
    as_of: datetime
    bars: list[MarketBar] = Field(min_length=1)
    snapshot_key: str

    @field_validator("source_provider", "snapshot_key")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("as_of")
    @classmethod
    def _as_of_is_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _snapshot_is_consistent(self) -> "MarketSnapshot":
        previous_opened_at: datetime | None = None
        provider_event_ids: set[str] = set()

        for bar in self.bars:
            if (
                bar.market != self.market
                or bar.instrument_id != self.instrument_id
                or bar.timeframe != self.timeframe
            ):
                raise ValueError("all bars must match snapshot market, instrument, and timeframe")
            if bar.provider != self.source_provider:
                raise ValueError("all bars must match snapshot source_provider")

            # 决策: Provider 重复返回同一 K 线时必须在快照层被发现，避免重复候选。
            if bar.provider_event_id in provider_event_ids:
                raise ValueError("bar provider_event_id must be unique inside a snapshot")
            provider_event_ids.add(bar.provider_event_id)

            if previous_opened_at is not None and bar.opened_at <= previous_opened_at:
                raise ValueError("bars must be ordered by opened_at ascending")
            previous_opened_at = bar.opened_at

        if self.as_of < self.bars[-1].opened_at:
            raise ValueError("as_of must not be earlier than latest bar opened_at")

        return self


class MarketBarClosedEvent(ContractModel):
    """标准 K 线收盘事件。

    业务描述:
        表达 Provider 已确认的一根 K 线收盘事实，可进入事件总线或 replay 输入。

    业务场景:
        - 后续 Redis Streams 消费 market.bar_closed。
        - PreFilter 只对已收盘 K 线执行低成本筛选。
        - 重复投递时用 dedupe_key 抑制重复候选。

    业务原因:
        行情轮询和事件消费要按至少一次投递设计，收盘事件必须自带稳定幂等键。

    调用链:
        Provider -> MarketBarClosedEvent -> Consumer -> PreFilter

    业务规则:
        bar 必须是已确认收盘 K 线；事件身份必须与 bar 一致。
    """

    id: UUID
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    bar: MarketBar
    occurred_at: datetime
    dedupe_key: str

    @field_validator("dedupe_key")
    @classmethod
    def _dedupe_key_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _event_matches_bar(self) -> "MarketBarClosedEvent":
        if not self.bar.is_closed:
            raise ValueError("bar must be closed before publishing MarketBarClosedEvent")
        if (
            self.bar.market != self.market
            or self.bar.instrument_id != self.instrument_id
            or self.bar.timeframe != self.timeframe
        ):
            raise ValueError("bar identity must match event identity")
        if self.occurred_at < self.bar.closed_at:
            raise ValueError("occurred_at must not be earlier than bar closed_at")
        return self
