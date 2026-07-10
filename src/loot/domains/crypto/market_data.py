"""Crypto 行情数据 Provider。

业务描述:
    为 Crypto bounded context 提供只读 K 线数据输入，包括 FakeProvider 和 OKX
    public REST Provider。

业务场景:
    - Phase 0 使用 FakeCryptoProvider 生成确定性 K 线，搭建本地闭环和 Golden Case。
    - 本地 smoke 或 Shadow 模式使用 OkxRestCryptoProvider 拉取公共 K 线。
    - 后续 PreFilter 消费 MarketSnapshot，决定是否唤醒 Agent。

业务原因:
    Provider 是外部网络访问的唯一边界。先把公共行情接入封装起来，可以避免
    Skill、Agent 或状态机随意访问交易所接口。

调用链:
    Scheduler/Worker -> CryptoMarketDataProvider.fetch_recent_bars
    -> MarketSnapshot -> Crypto PreFilter -> CandidateEvent

业务规则:
    - 只读公共行情，不读取账户，不接私有 API，不下单。
    - Instrument 必须属于 CRYPTO；OKX Provider 只接受 venue=OKX。
    - 单测通过注入 http_get 固定响应，不依赖外网。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Callable, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, UUID, uuid5

from loot.contracts import Instrument, Market, Timeframe
from loot.contracts.base import ensure_utc_datetime
from loot.contracts.market_data import MarketBar, MarketSnapshot

HttpGet = Callable[[str, float], bytes]

_TIMEFRAME_DURATION: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
    Timeframe.W1: timedelta(weeks=1),
}

_OKX_BAR_CODE: dict[Timeframe, str] = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1H",
    Timeframe.H4: "4H",
    Timeframe.D1: "1D",
    Timeframe.W1: "1W",
}


class CryptoProviderError(RuntimeError):
    """Crypto 行情 Provider 错误。"""


class CryptoMarketDataProvider(Protocol):
    """Crypto 行情数据源接口。

    业务描述:
        约束 Crypto 市场领域内所有行情数据源，统一输出 MarketSnapshot。

    业务场景:
        - FakeProvider 用于本地确定性测试。
        - OKX public REST Provider 用于第一版真实 K 线读取。
        - 后续 Binance、Coinbase 或链上数据源可实现同一接口。

    业务原因:
        市场领域只依赖 Provider 抽象，避免 PreFilter、Agent 或 Skill 绑定具体交易所。

    调用链:
        Worker -> CryptoMarketDataProvider -> MarketSnapshot -> PreFilter

    业务规则:
        Provider 只允许读取公开行情；不得暴露账户、资金、订单或交易能力。
    """

    @property
    def provider_name(self) -> str:
        """返回 Provider 标识，用于审计、幂等键和 snapshot_key。"""

        ...

    def fetch_recent_bars(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        *,
        limit: int,
        include_unclosed: bool = False,
    ) -> MarketSnapshot:
        """拉取最近 K 线并返回标准行情快照。

        业务点:
            Provider 的唯一公开读取入口，负责把外部数据归一化为 MarketSnapshot。

        调用链:
            validate_instrument -> read_source -> normalize_bars -> build_snapshot
        """

        ...


@dataclass(frozen=True, slots=True)
class FakeCryptoProvider:
    """确定性 Crypto 假行情源。

    业务描述:
        生成固定递增的 Crypto K 线窗口，为预筛选、状态机和 replay 准备无外网输入。

    业务场景:
        - 本地单元测试验证 MarketSnapshot 契约。
        - Golden Case 固定输入，避免真实行情波动导致测试不可复现。
        - Worker 骨架尚未接入真实交易所时先跑通链路。

    业务原因:
        第一条端到端闭环应先验证幂等、路由和状态迁移，而不是被外部网络稳定性干扰。

    调用链:
        Test/Worker -> FakeCryptoProvider.fetch_recent_bars -> MarketSnapshot

    业务规则:
        仅支持 CRYPTO Instrument；每根 K 线 provider_event_id 稳定可复现。
    """

    received_at: datetime = datetime(2026, 7, 10, 0, 0, tzinfo=UTC)
    start_price: Decimal = Decimal("100")
    step: Decimal = Decimal("1")

    @property
    def provider_name(self) -> str:
        return "fake.crypto"

    def fetch_recent_bars(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        *,
        limit: int,
        include_unclosed: bool = False,
    ) -> MarketSnapshot:
        """生成最近 K 线窗口。

        业务点:
            固定窗口用于测试 Candidate 生成和 Signal 状态迁移，不表达真实市场价格。

        调用链:
            validate_crypto_instrument -> generate_bars -> build_snapshot
        """

        _ensure_crypto_instrument(instrument)
        _ensure_limit(limit, max_limit=500)

        duration = _timeframe_duration(timeframe)
        received_at = ensure_utc_datetime(self.received_at)
        first_opened_at = received_at - duration * limit
        bars: list[MarketBar] = []

        for index in range(limit):
            # 决策: 使用稳定递增价格，便于 Golden Case 明确预期走势。
            opened_at = first_opened_at + duration * index
            closed_at = opened_at + duration
            base_price = self.start_price + self.step * Decimal(index)
            close_price = base_price + self.step * Decimal("0.5")
            high_price = max(base_price, close_price) + abs(self.step)
            low_price = max(Decimal("0.00000001"), min(base_price, close_price) - abs(self.step))
            provider_event_id = _provider_event_id(
                self.provider_name,
                instrument,
                timeframe,
                opened_at,
            )
            bars.append(
                MarketBar(
                    id=_stable_uuid(provider_event_id),
                    provider=self.provider_name,
                    provider_event_id=provider_event_id,
                    market=instrument.market,
                    instrument_id=instrument.instrument_id,
                    venue=instrument.venue,
                    symbol=instrument.symbol,
                    timeframe=timeframe,
                    opened_at=opened_at,
                    closed_at=closed_at,
                    open_price=base_price,
                    high_price=high_price,
                    low_price=low_price,
                    close_price=close_price,
                    volume=Decimal("10") + Decimal(index),
                    quote_volume=(Decimal("10") + Decimal(index)) * close_price,
                    is_closed=True,
                    received_at=received_at,
                )
            )

        return _build_snapshot(
            provider_name=self.provider_name,
            instrument=instrument,
            timeframe=timeframe,
            bars=bars,
            as_of=received_at,
        )


@dataclass(frozen=True, slots=True)
class OkxRestCryptoProvider:
    """OKX 公共 REST K 线 Provider。

    业务描述:
        通过 OKX public market candles API 读取 Crypto K 线，并转换为 MarketSnapshot。

    业务场景:
        - 本地 smoke 验证真实 BTC-USDT 行情是否能标准化。
        - Shadow 模式持续拉取公共行情，不触碰账户和交易能力。
        - 后续 Crypto PreFilter 以该快照作为真实输入源。

    业务原因:
        第一版真实数据源应选择无认证、只读、易替换的公共 REST K 线，而不是直接
        接入私有 API、WebSocket 或交易能力。

    调用链:
        Worker -> OkxRestCryptoProvider.fetch_recent_bars
        -> OKX public REST -> MarketSnapshot

    业务规则:
        Instrument.venue 必须是 OKX；limit 不能超过 OKX recent candles 当前安全上限。
    """

    base_url: str = "https://www.okx.com"
    timeout_seconds: float = 5.0
    http_get: HttpGet | None = None

    @property
    def provider_name(self) -> str:
        return "okx.public_rest"

    def fetch_recent_bars(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        *,
        limit: int,
        include_unclosed: bool = False,
    ) -> MarketSnapshot:
        """读取 OKX 最近 K 线。

        业务点:
            默认只返回已收盘 K 线；需要盘中最新 K 线时必须显式传入
            include_unclosed=True。

        调用链:
            validate_okx_instrument -> call_public_rest -> parse_rows -> build_snapshot
        """

        _ensure_crypto_instrument(instrument)
        if instrument.venue.upper() != "OKX":
            raise ValueError("OkxRestCryptoProvider only accepts venue=OKX instruments")
        _ensure_limit(limit, max_limit=300)
        request_limit = _okx_request_limit(limit, include_unclosed=include_unclosed)

        query = urlencode(
            {
                "instId": instrument.symbol,
                "bar": _okx_bar_code(timeframe),
                "limit": str(request_limit),
            }
        )
        url = f"{self.base_url.rstrip('/')}/api/v5/market/candles?{query}"
        raw_payload = (self.http_get or _default_http_get)(url, self.timeout_seconds)
        payload = json.loads(raw_payload.decode("utf-8"))

        if payload.get("code") != "0":
            message = payload.get("msg") or "unknown OKX market data error"
            raise CryptoProviderError(f"OKX candles request failed: {message}")

        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            raise CryptoProviderError("OKX candles response did not include data rows")

        received_at = datetime.now(UTC)
        normalized_bars = [
            self._parse_candle_row(
                instrument,
                timeframe,
                row,
                received_at=received_at,
            )
            for row in reversed(rows)
        ]
        bars = _select_return_bars(
            normalized_bars,
            limit=limit,
            include_unclosed=include_unclosed,
        )
        if not bars:
            raise CryptoProviderError("OKX candles response did not include usable data rows")

        return _build_snapshot(
            provider_name=self.provider_name,
            instrument=instrument,
            timeframe=timeframe,
            bars=bars,
            as_of=received_at,
        )

    def _parse_candle_row(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        row: object,
        *,
        received_at: datetime,
    ) -> MarketBar:
        # 注意: OKX 返回数组字段，必须按版本化文档顺序解析，不能用猜测字段名。
        if not isinstance(row, list) or len(row) < 9:
            raise CryptoProviderError("OKX candle row must contain 9 fields")

        opened_at = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC)
        provider_event_id = f"okx:{instrument.symbol}:{timeframe}:{row[0]}"
        quote_volume = Decimal(str(row[7])) if str(row[7]) else None
        return MarketBar(
            id=_stable_uuid(provider_event_id),
            provider=self.provider_name,
            provider_event_id=provider_event_id,
            market=instrument.market,
            instrument_id=instrument.instrument_id,
            venue=instrument.venue,
            symbol=instrument.symbol,
            timeframe=timeframe,
            opened_at=opened_at,
            closed_at=opened_at + _timeframe_duration(timeframe),
            open_price=Decimal(str(row[1])),
            high_price=Decimal(str(row[2])),
            low_price=Decimal(str(row[3])),
            close_price=Decimal(str(row[4])),
            volume=Decimal(str(row[5])),
            quote_volume=quote_volume,
            is_closed=str(row[8]) == "1",
            received_at=received_at,
        )


def _default_http_get(url: str, timeout_seconds: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Loot/0.1 read-only-market-data",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _ensure_crypto_instrument(instrument: Instrument) -> None:
    if instrument.market != Market.CRYPTO:
        raise ValueError("crypto market data provider only accepts CRYPTO instruments")


def _ensure_limit(limit: int, *, max_limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if limit > max_limit:
        raise ValueError(f"limit must not exceed {max_limit}")


def _okx_request_limit(limit: int, *, include_unclosed: bool) -> int:
    if include_unclosed:
        return limit
    return min(limit + 1, 300)


def _select_return_bars(
    bars: list[MarketBar],
    *,
    limit: int,
    include_unclosed: bool,
) -> list[MarketBar]:
    # 决策: 默认丢弃未收盘 K 线，防止 PreFilter 被盘中噪声误唤醒。
    selected_bars = bars if include_unclosed else [bar for bar in bars if bar.is_closed]
    return selected_bars[-limit:]


def _timeframe_duration(timeframe: Timeframe) -> timedelta:
    try:
        return _TIMEFRAME_DURATION[timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported timeframe: {timeframe}") from exc


def _okx_bar_code(timeframe: Timeframe) -> str:
    try:
        return _OKX_BAR_CODE[timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported OKX timeframe: {timeframe}") from exc


def _provider_event_id(
    provider_name: str,
    instrument: Instrument,
    timeframe: Timeframe,
    opened_at: datetime,
) -> str:
    return (
        f"{provider_name}:"
        f"{instrument.venue}:"
        f"{instrument.symbol}:"
        f"{timeframe}:"
        f"{opened_at.isoformat()}"
    )


def _stable_uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, value)


def _build_snapshot(
    *,
    provider_name: str,
    instrument: Instrument,
    timeframe: Timeframe,
    bars: list[MarketBar],
    as_of: datetime,
) -> MarketSnapshot:
    latest_bar = bars[-1]
    snapshot_key = (
        f"{provider_name}:"
        f"{instrument.instrument_id}:"
        f"{timeframe}:"
        f"{latest_bar.provider_event_id}"
    )
    return MarketSnapshot(
        id=_stable_uuid(snapshot_key),
        market=instrument.market,
        instrument_id=instrument.instrument_id,
        timeframe=timeframe,
        source_provider=provider_name,
        as_of=as_of,
        bars=bars,
        snapshot_key=snapshot_key,
    )
