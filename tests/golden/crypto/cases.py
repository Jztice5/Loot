"""Crypto Golden Case fixture loader.

业务描述:
    将版本化的可读行情固定输入转换为真实 ``MarketSnapshot``，并携带独立于
    PreFilter 实现的候选预期。

业务场景:
    - REQ-0006 在实现 PreFilter 前固定 LONG、SHORT 和未收盘过滤口径。
    - REQ-0005 直接复用同一批输入验证 CandidateEvent。
    - 后续 Replay 使用稳定 Snapshot identity 对比规则版本输出。

业务原因:
    Golden Case 必须先表达产品判断，不能由已经实现的算法反推预期。固定 JSON 保持
    输入可读，FakeCryptoProvider 提供确定性的 Provider 身份和时间窗口。

调用链:
    JSON fixture -> FakeCryptoProvider -> MarketBar facts -> MarketSnapshot
    -> Golden expectation -> PreFilter/Replay tests

业务规则:
    - 固定输入只包含 Crypto H1 K 线。
    - 第一版结构窗口为最新已收盘 K 线之前的 3 根已收盘 K 线。
    - 候选类型和方向必须同时存在或同时为空。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from loot.contracts import (
    CandidateType,
    Direction,
    Instrument,
    InstrumentStatus,
    InstrumentType,
    Market,
    MarketBar,
    MarketSnapshot,
    Timeframe,
)
from loot.contracts.base import ensure_non_empty, ensure_utc_datetime
from loot.domains.crypto import FakeCryptoProvider

_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "structure-breakout-v0.1.json"
)
_SUPPORTED_SCHEMA_VERSION = "crypto.structure-breakout.v1"


@dataclass(frozen=True, slots=True)
class CryptoGoldenExpectation:
    """独立于 PreFilter 实现的 Crypto 候选预期。"""

    candidate_type: CandidateType | None
    direction: Direction | None
    reason_code: str
    reference_high: Decimal | None
    reference_low: Decimal | None
    trigger_close: Decimal

    def __post_init__(self) -> None:
        """保证候选类型与方向不会形成半截预期。"""

        has_candidate_type = self.candidate_type is not None
        has_direction = self.direction is not None
        if has_candidate_type != has_direction:
            raise ValueError(
                "candidate_type and direction must both be set or both be empty"
            )
        ensure_non_empty(self.reason_code)


@dataclass(frozen=True, slots=True)
class CryptoGoldenCase:
    """一组可直接进入后续 PreFilter 或 Replay 的固定输入与预期。"""

    case_id: str
    description: str
    lookback_bars: int
    snapshot: MarketSnapshot
    expectation: CryptoGoldenExpectation

    def __post_init__(self) -> None:
        """校验 Golden Case 的最小可读性和窗口约束。"""

        ensure_non_empty(self.case_id)
        ensure_non_empty(self.description)
        if self.lookback_bars < 1:
            raise ValueError("lookback_bars must be at least 1")


def load_crypto_structure_golden_cases() -> tuple[CryptoGoldenCase, ...]:
    """加载第一版 Crypto 结构突破 Golden Cases。

    业务点:
        JSON 是业务预期的可读事实源；FakeCryptoProvider 只生成确定性的标的时间窗口和
        Provider identity，随后用 fixture 中的 OHLCV 与闭合状态重建并校验 MarketBar。

    调用链:
        read fixture -> validate schema -> build fake snapshot -> apply bar facts
        -> build canonical snapshot -> attach expectation
    """

    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    schema_version = payload.get("schema_version")
    if schema_version != _SUPPORTED_SCHEMA_VERSION:
        raise ValueError(f"unsupported Golden Case schema: {schema_version}")

    instrument = _build_instrument(payload["instrument"])
    timeframe = Timeframe(payload["timeframe"])
    lookback_bars = int(payload["lookback_bars"])

    cases = tuple(
        _build_case(
            case_payload,
            instrument=instrument,
            timeframe=timeframe,
            lookback_bars=lookback_bars,
        )
        for case_payload in payload["cases"]
    )
    case_ids = {case.case_id for case in cases}
    if len(case_ids) != len(cases):
        raise ValueError("Golden Case case_id must be unique")
    return cases


def _build_instrument(payload: dict[str, object]) -> Instrument:
    """从固定输入构造 Fake Crypto 标的。"""

    return Instrument(
        instrument_id=UUID(str(payload["instrument_id"])),
        market=Market.CRYPTO,
        venue=str(payload["venue"]),
        symbol=str(payload["symbol"]),
        instrument_type=InstrumentType(str(payload["instrument_type"])),
        quote_currency=str(payload["quote_currency"]),
        timezone=str(payload["timezone"]),
        price_scale=int(payload["price_scale"]),
        status=InstrumentStatus.ACTIVE,
    )


def _build_case(
    payload: dict[str, object],
    *,
    instrument: Instrument,
    timeframe: Timeframe,
    lookback_bars: int,
) -> CryptoGoldenCase:
    """使用 FakeProvider 骨架和固定行情事实构造单个案例。"""

    as_of = _parse_utc_datetime(str(payload["as_of"]))
    bar_payloads = payload["bars"]
    if not isinstance(bar_payloads, list):
        raise ValueError("Golden Case bars must be a list")

    baseline = FakeCryptoProvider(received_at=as_of).fetch_recent_bars(
        instrument,
        timeframe,
        limit=len(bar_payloads),
    )
    bars = tuple(
        _replace_bar_facts(base_bar, bar_payload)
        for base_bar, bar_payload in zip(
            baseline.bars,
            bar_payloads,
            strict=True,
        )
    )
    snapshot = MarketSnapshot.from_bars(
        market=instrument.market,
        instrument_id=instrument.instrument_id,
        timeframe=timeframe,
        source_provider=baseline.source_provider,
        as_of=as_of,
        bars=bars,
    )

    expectation_payload = payload["expectation"]
    if not isinstance(expectation_payload, dict):
        raise ValueError("Golden Case expectation must be an object")

    return CryptoGoldenCase(
        case_id=str(payload["case_id"]),
        description=str(payload["description"]),
        lookback_bars=lookback_bars,
        snapshot=snapshot,
        expectation=_build_expectation(expectation_payload),
    )


def _replace_bar_facts(
    base_bar: MarketBar,
    payload: object,
) -> MarketBar:
    """用 fixture OHLCV 重建 FakeProvider K 线并执行完整契约校验。"""

    if not isinstance(payload, dict):
        raise ValueError("Golden Case bar must be an object")

    close_price = Decimal(str(payload["close"]))
    volume = Decimal(str(payload["volume"]))
    is_closed = payload["is_closed"]
    if not isinstance(is_closed, bool):
        raise ValueError("Golden Case is_closed must be a boolean")

    return MarketBar.model_validate(
        {
            **base_bar.model_dump(),
            "open_price": Decimal(str(payload["open"])),
            "high_price": Decimal(str(payload["high"])),
            "low_price": Decimal(str(payload["low"])),
            "close_price": close_price,
            "volume": volume,
            "quote_volume": volume * close_price,
            "is_closed": is_closed,
        }
    )


def _build_expectation(payload: dict[str, object]) -> CryptoGoldenExpectation:
    """解析并校验候选预期。"""

    candidate_type = payload.get("candidate_type")
    direction = payload.get("direction")
    return CryptoGoldenExpectation(
        candidate_type=(
            CandidateType(str(candidate_type))
            if candidate_type is not None
            else None
        ),
        direction=Direction(str(direction)) if direction is not None else None,
        reason_code=str(payload["reason_code"]),
        reference_high=_optional_decimal(payload.get("reference_high")),
        reference_low=_optional_decimal(payload.get("reference_low")),
        trigger_close=Decimal(str(payload["trigger_close"])),
    )


def _parse_utc_datetime(value: str) -> datetime:
    """解析 fixture ISO-8601 时间并归一化为 UTC。"""

    return ensure_utc_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _optional_decimal(value: object) -> Decimal | None:
    """解析允许为空的 Golden Case 数值预期。"""

    return Decimal(str(value)) if value is not None else None
