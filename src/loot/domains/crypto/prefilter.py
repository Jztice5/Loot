"""Crypto 确定性结构突破 PreFilter。

业务描述:
    消费标准 ``MarketSnapshot``，以最新已收盘 K 线和前 3 根已收盘 K 线判断结构突破，
    只在满足 Golden Case 规则时生成 direction-aware ``CandidateEvent``。

业务场景:
    - Scheduler 或 Worker 获取 Crypto 行情快照后执行低成本预筛选。
    - 无候选时记录明确原因，不唤醒 Agent 或 Skill Runtime。
    - LONG 或 SHORT 收盘突破时生成稳定 Candidate，交给后续分析链路。

业务原因:
    PreFilter 是 Agent 前的确定性成本闸门。规则必须可解释、可 replay，并与
    ``crypto.structure-breakout.v1`` Golden Cases 保持一致。

调用链:
    MarketSnapshot -> CryptoStructurePreFilter.evaluate
    -> CryptoPreFilterResult -> [有候选] CandidateEvent -> Analyzer/Agent

业务规则:
    - 只接受 Crypto MarketSnapshot。
    - 只使用已收盘 K 线产生市场判断。
    - 前 3 根已收盘 K 线构成参考窗口，最新已收盘 K 线构成触发 K 线。
    - 严格收盘上破为 LONG，严格收盘下破为 SHORT，等于边界不算突破。
    - dedupe_key 绑定规则版本、WatchItem、完整 Snapshot、触发 K 线和 direction。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from loot.contracts import (
    CandidateEvent,
    CandidateType,
    Direction,
    Market,
    MarketBar,
    MarketSnapshot,
    Priority,
)

_LOOKBACK_BARS = 3
_RULE_VERSION = "crypto.structure-breakout.v1"
_SKILL_GROUP = "crypto.market_structure_assessment"


class CryptoPreFilterReason(StrEnum):
    """Crypto 结构预筛选的稳定原因码。"""

    INSUFFICIENT_CLOSED_HISTORY = "INSUFFICIENT_CLOSED_HISTORY"
    NO_CLOSED_STRUCTURE_BREAK = "NO_CLOSED_STRUCTURE_BREAK"
    UNCLOSED_BAR_IGNORED = "UNCLOSED_BAR_IGNORED"
    CLOSED_ABOVE_REFERENCE_HIGH = "CLOSED_ABOVE_REFERENCE_HIGH"
    CLOSED_BELOW_REFERENCE_LOW = "CLOSED_BELOW_REFERENCE_LOW"


@dataclass(frozen=True, slots=True)
class CryptoPreFilterInput:
    """Crypto PreFilter 的显式输入上下文。

    业务描述:
        绑定本次行情 Snapshot 和用户监控身份；可选 position_id 只用于 Candidate 关联，
        不参与市场结构真假的判断。

    调用链:
        Worker -> CryptoPreFilterInput -> CryptoStructurePreFilter.evaluate
    """

    snapshot: MarketSnapshot
    watch_item_id: UUID
    position_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CryptoPreFilterResult:
    """可审计的 Crypto PreFilter 输出。

    业务描述:
        同时表达 Candidate 或明确的 no-candidate 原因，并保留本次使用的结构边界和
        触发 K 线，便于测试、Replay 和后续观测。

    业务规则:
        成功突破原因必须带 Candidate；其他原因不能伪造 Candidate。
    """

    rule_version: str
    reason: CryptoPreFilterReason
    candidate: CandidateEvent | None
    reference_high: Decimal | None
    reference_low: Decimal | None
    trigger_bar_id: UUID | None

    def __post_init__(self) -> None:
        """校验原因码与 Candidate 是否一致。"""

        candidate_reasons = {
            CryptoPreFilterReason.CLOSED_ABOVE_REFERENCE_HIGH,
            CryptoPreFilterReason.CLOSED_BELOW_REFERENCE_LOW,
        }
        if (self.reason in candidate_reasons) != (self.candidate is not None):
            raise ValueError("candidate must match the PreFilter reason")
        if (self.reference_high is None) != (self.reference_low is None):
            raise ValueError("reference_high and reference_low must be set together")
        if self.candidate is not None and self.trigger_bar_id is None:
            raise ValueError("candidate result requires trigger_bar_id")
        if self.candidate is not None and self.reference_high is None:
            raise ValueError("candidate result requires reference boundaries")


class CryptoStructurePreFilter:
    """Crypto V0.1 结构突破确定性筛选器。

    业务描述:
        按固定 3 根参考窗口识别收盘确认的 LONG/SHORT 结构突破。

    业务场景:
        Crypto 行情快照到达后，在调用昂贵分析能力前先执行本筛选器。

    业务原因:
        第一版只实现 Golden Case 已确认的最小规则，不加入成交量、ATR 或自适应参数。

    调用链:
        CryptoPreFilterInput -> closed bars -> structure boundaries
        -> CandidateEvent/no-candidate -> CryptoPreFilterResult

    业务规则:
        算法版本固定为 ``crypto.structure-breakout.v1``；规则变化必须新增版本。
    """

    @property
    def rule_version(self) -> str:
        """返回参与 Candidate identity 的规则版本。"""

        return _RULE_VERSION

    @property
    def lookback_bars(self) -> int:
        """返回 Golden Case 固定的参考窗口长度。"""

        return _LOOKBACK_BARS

    def evaluate(self, input_context: CryptoPreFilterInput) -> CryptoPreFilterResult:
        """评估行情快照并返回确定性候选结果。

        业务点:
            使用完整 Snapshot 作为输入身份，但只使用 ``closed_bars`` 计算结构真假。

        调用链:
            validate market -> select closed bars -> calculate boundaries
            -> classify direction -> build stable Candidate/no-candidate result
        """

        snapshot = input_context.snapshot
        if snapshot.market != Market.CRYPTO:
            raise ValueError("CryptoStructurePreFilter only accepts CRYPTO snapshots")

        closed_bars = snapshot.closed_bars
        if len(closed_bars) < self.lookback_bars + 1:
            return CryptoPreFilterResult(
                rule_version=self.rule_version,
                reason=CryptoPreFilterReason.INSUFFICIENT_CLOSED_HISTORY,
                candidate=None,
                reference_high=None,
                reference_low=None,
                trigger_bar_id=(closed_bars[-1].id if closed_bars else None),
            )

        trigger_bar = closed_bars[-1]
        reference_bars = closed_bars[-(self.lookback_bars + 1) : -1]
        reference_high = max(bar.high_price for bar in reference_bars)
        reference_low = min(bar.low_price for bar in reference_bars)

        if trigger_bar.close_price > reference_high:
            direction = Direction.LONG
            reason = CryptoPreFilterReason.CLOSED_ABOVE_REFERENCE_HIGH
            boundary = reference_high
        elif trigger_bar.close_price < reference_low:
            direction = Direction.SHORT
            reason = CryptoPreFilterReason.CLOSED_BELOW_REFERENCE_LOW
            boundary = reference_low
        else:
            return CryptoPreFilterResult(
                rule_version=self.rule_version,
                reason=self._no_candidate_reason(
                    snapshot,
                    reference_high=reference_high,
                    reference_low=reference_low,
                ),
                candidate=None,
                reference_high=reference_high,
                reference_low=reference_low,
                trigger_bar_id=trigger_bar.id,
            )

        candidate = self._build_candidate(
            input_context,
            trigger_bar=trigger_bar,
            direction=direction,
            reason=reason,
            boundary=boundary,
        )
        return CryptoPreFilterResult(
            rule_version=self.rule_version,
            reason=reason,
            candidate=candidate,
            reference_high=reference_high,
            reference_low=reference_low,
            trigger_bar_id=trigger_bar.id,
        )

    def _no_candidate_reason(
        self,
        snapshot: MarketSnapshot,
        *,
        reference_high: Decimal,
        reference_low: Decimal,
    ) -> CryptoPreFilterReason:
        """区分普通无突破与最新未收盘 K 线越界。"""

        latest_bar = snapshot.latest_bar
        if not latest_bar.is_closed and (
            latest_bar.close_price > reference_high
            or latest_bar.close_price < reference_low
        ):
            return CryptoPreFilterReason.UNCLOSED_BAR_IGNORED
        return CryptoPreFilterReason.NO_CLOSED_STRUCTURE_BREAK

    def _build_candidate(
        self,
        input_context: CryptoPreFilterInput,
        *,
        trigger_bar: MarketBar,
        direction: Direction,
        reason: CryptoPreFilterReason,
        boundary: Decimal,
    ) -> CandidateEvent:
        """构造绑定完整输入和方向的稳定 CandidateEvent。"""

        snapshot = input_context.snapshot
        candidate_type = CandidateType.STRUCTURE_BREAKOUT
        position_identity = (
            str(input_context.position_id)
            if input_context.position_id is not None
            else "none"
        )
        dedupe_key = ":".join(
            (
                "crypto.prefilter",
                self.rule_version,
                str(input_context.watch_item_id),
                position_identity,
                str(snapshot.instrument_id),
                snapshot.timeframe.value,
                str(snapshot.id),
                candidate_type.value,
                direction.value,
                trigger_bar.provider_event_id,
            )
        )
        bar_duration = trigger_bar.closed_at - trigger_bar.opened_at
        trigger_reason = (
            f"{reason.value}: close={_decimal_text(trigger_bar.close_price)} "
            f"boundary={_decimal_text(boundary)}"
        )
        return CandidateEvent(
            id=uuid5(NAMESPACE_URL, dedupe_key),
            candidate_type=candidate_type,
            direction=direction,
            trigger_reason=trigger_reason,
            snapshot_id=snapshot.id,
            watch_item_id=input_context.watch_item_id,
            position_id=input_context.position_id,
            suggested_skill_group=_SKILL_GROUP,
            urgency=Priority.NORMAL,
            occurred_at=trigger_bar.closed_at,
            expires_at=snapshot.as_of + bar_duration,
            dedupe_key=dedupe_key,
        )


def _decimal_text(value: Decimal) -> str:
    """将价格转换为不受 Decimal 尾零影响的稳定文本。"""

    if value == 0:
        return "0"
    return format(value.normalize(), "f")
