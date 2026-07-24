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
    - 快照内所有 K 线必须属于同一市场、标的、周期和 Provider。
    - 快照 bars 使用 tuple 保存，避免消费者在内存中追加或重排行情事实。
    - provider_event_id 用于单根 K 线去重；Snapshot 身份绑定完整规范化窗口内容。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

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

        # 决策: Provider 只有在真实闭合时间到达后，才能把 K 线声明为已收盘。
        if self.is_closed and self.received_at < self.closed_at:
            raise ValueError("closed bar received_at must not be earlier than closed_at")

        # 决策: high/low 不包住 open/close 时，突破和回踩判断会出现假信号。
        highest_observed = max(self.open_price, self.close_price, self.low_price)
        if self.high_price < highest_observed:
            raise ValueError("high_price must cover open_price, close_price, and low_price")

        lowest_observed = min(self.open_price, self.close_price, self.high_price)
        if self.low_price > lowest_observed:
            raise ValueError("low_price must cover open_price, close_price, and high_price")

        return self


def _canonical_datetime(value: datetime) -> str:
    """将 Snapshot 身份中的时间统一为稳定 UTC 文本。"""

    return ensure_utc_datetime(value).isoformat(timespec="microseconds")


def _canonical_decimal(value: Decimal | None) -> str | None:
    """将数值事实转为不受 Decimal 尾随零影响的稳定文本。"""

    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _calculate_snapshot_content_hash(
    *,
    source_provider: str,
    market: Market,
    instrument_id: UUID,
    timeframe: Timeframe,
    as_of: datetime,
    bars: Iterable[MarketBar],
) -> str:
    """根据完整规范化行情窗口计算 SHA-256 内容指纹。

    业务点:
        排除派生 UUID，保留 Provider、标的、周期、as_of 和全部 K 线事实；数值先消除
        Decimal 尾随零差异，时间先归一化为 UTC。

    调用链:
        MarketSnapshot.from_bars/model_validator -> canonical JSON -> SHA-256

    幂等逻辑:
        相同事实得到相同指纹；窗口长度、历史内容、闭合状态或接收时间变化都会改变指纹。
    """

    ordered_bars = sorted(bars, key=lambda bar: bar.opened_at)
    canonical_payload = {
        "provider": source_provider,
        "market": market.value,
        "instrument_id": str(instrument_id),
        "timeframe": timeframe.value,
        "as_of": _canonical_datetime(as_of),
        "bars": [
            {
                "provider": bar.provider,
                "provider_event_id": bar.provider_event_id,
                "market": bar.market.value,
                "instrument_id": str(bar.instrument_id),
                "venue": bar.venue,
                "symbol": bar.symbol,
                "timeframe": bar.timeframe.value,
                "opened_at": _canonical_datetime(bar.opened_at),
                "closed_at": _canonical_datetime(bar.closed_at),
                "open_price": _canonical_decimal(bar.open_price),
                "high_price": _canonical_decimal(bar.high_price),
                "low_price": _canonical_decimal(bar.low_price),
                "close_price": _canonical_decimal(bar.close_price),
                "volume": _canonical_decimal(bar.volume),
                "quote_volume": _canonical_decimal(bar.quote_volume),
                "is_closed": bar.is_closed,
                "received_at": _canonical_datetime(bar.received_at),
            }
            for bar in ordered_bars
        ],
    }
    canonical_json = json.dumps(
        canonical_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _build_snapshot_key(
    source_provider: str,
    instrument_id: UUID,
    timeframe: Timeframe,
    snapshot_content_hash: str,
) -> str:
    """构建绑定 Provider、标的、周期和完整内容的 Snapshot 幂等键。"""

    return (
        f"{source_provider}:"
        f"{instrument_id}:"
        f"{timeframe.value}:"
        f"{snapshot_content_hash}"
    )


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
        bars 必须按 opened_at 升序排列；同一快照内 provider_event_id 不能重复；
        PreFilter 应优先使用 latest_closed_bar，避免未收盘 K 线制造假信号；
        snapshot_content_hash、snapshot_key 和 id 必须与完整 canonical 内容一致。
    """

    id: UUID
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    source_provider: str
    as_of: datetime
    bars: tuple[MarketBar, ...] = Field(min_length=1)
    snapshot_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_key: str

    @classmethod
    def from_bars(
        cls,
        *,
        market: Market,
        instrument_id: UUID,
        timeframe: Timeframe,
        source_provider: str,
        as_of: datetime,
        bars: Iterable[MarketBar],
    ) -> "MarketSnapshot":
        """从完整行情窗口构造内容寻址的 Snapshot。

        业务点:
            生产者只提供标准化事实，Snapshot 统一负责排序、内容指纹、幂等键和稳定 ID。

        调用链:
            Provider -> MarketSnapshot.from_bars -> PreFilter/Replay
        """

        normalized_provider = ensure_non_empty(source_provider)
        normalized_as_of = ensure_utc_datetime(as_of)
        ordered_bars = tuple(sorted(bars, key=lambda bar: bar.opened_at))
        content_hash = _calculate_snapshot_content_hash(
            source_provider=normalized_provider,
            market=market,
            instrument_id=instrument_id,
            timeframe=timeframe,
            as_of=normalized_as_of,
            bars=ordered_bars,
        )
        snapshot_key = _build_snapshot_key(
            normalized_provider,
            instrument_id,
            timeframe,
            content_hash,
        )
        return cls(
            id=uuid5(NAMESPACE_URL, snapshot_key),
            market=market,
            instrument_id=instrument_id,
            timeframe=timeframe,
            source_provider=normalized_provider,
            as_of=normalized_as_of,
            bars=ordered_bars,
            snapshot_content_hash=content_hash,
            snapshot_key=snapshot_key,
        )

    @property
    def latest_bar(self) -> MarketBar:
        """返回快照中的最新 K 线，可能是未收盘 K 线。"""

        return self.bars[-1]

    @property
    def closed_bars(self) -> tuple[MarketBar, ...]:
        """返回快照中已确认收盘的 K 线。"""

        return tuple(bar for bar in self.bars if bar.is_closed)

    @property
    def latest_closed_bar(self) -> MarketBar | None:
        """返回最新已收盘 K 线。

        业务点:
            PreFilter 的默认入口应使用已收盘 K 线，除非策略明确声明支持盘中更新。

        调用链:
            MarketSnapshot -> latest_closed_bar -> PreFilter -> CandidateEvent
        """

        for bar in reversed(self.bars):
            if bar.is_closed:
                return bar
        return None

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

        if self.as_of < self.latest_bar.opened_at:
            raise ValueError("as_of must not be earlier than latest bar opened_at")

        closed_bars = tuple(bar for bar in self.bars if bar.is_closed)
        if closed_bars and self.as_of < max(bar.closed_at for bar in closed_bars):
            raise ValueError("as_of must not be earlier than any closed bar closed_at")

        expected_hash = _calculate_snapshot_content_hash(
            source_provider=self.source_provider,
            market=self.market,
            instrument_id=self.instrument_id,
            timeframe=self.timeframe,
            as_of=self.as_of,
            bars=self.bars,
        )
        if self.snapshot_content_hash != expected_hash:
            raise ValueError("snapshot_content_hash must match canonical snapshot content")

        expected_key = _build_snapshot_key(
            self.source_provider,
            self.instrument_id,
            self.timeframe,
            expected_hash,
        )
        if self.snapshot_key != expected_key:
            raise ValueError("snapshot_key must match snapshot identity and content hash")
        if self.id != uuid5(NAMESPACE_URL, expected_key):
            raise ValueError("snapshot id must be the stable UUID of snapshot_key")

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
