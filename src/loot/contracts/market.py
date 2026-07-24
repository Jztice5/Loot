"""市场身份与价格区域契约。

业务描述:
    定义跨市场共享的标的身份和用户自定义价格区域，供自选、监控和信号链路引用。

业务原因:
    Crypto、美股和 A 股是独立 bounded context，但事件链中必须用统一身份引用标的。

调用链:
    Instrument Registry -> Instrument -> WatchItem/Position -> Candidate/Signal
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from loot.contracts.base import ContractModel, ensure_non_empty
from loot.contracts.enums import InstrumentStatus, InstrumentType, Market


class Instrument(ContractModel):
    """跨市场共享的标准标的身份。

    业务描述:
        表达一个可监控资产在某个市场、交易场所和报价体系下的唯一身份。

    业务场景:
        - 用户添加 Crypto、美股或 A 股自选。
        - Position 和 Signal 需要稳定引用同一标的。
        - Provider 返回不同 symbol 习惯时做统一映射。

    业务规则:
        venue、symbol、quote_currency、timezone 均不能为空；price_scale 不能为负。
    """

    instrument_id: UUID
    market: Market
    venue: str
    symbol: str
    instrument_type: InstrumentType
    quote_currency: str
    timezone: str
    price_scale: int = Field(ge=0)
    status: InstrumentStatus

    @field_validator("venue", "symbol", "quote_currency", "timezone")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        return ensure_non_empty(value)


class PriceZone(ContractModel):
    """用户定义的价格区域。

    业务描述:
        记录用户关心的支撑、压力、成本区或观察区，作为 PreFilter 和 Skill 的证据。

    业务原因:
        价格区域只能唤醒分析链路，不能绕过 Policy Gate 直接产生 Signal。

    调用链:
        User Input -> PriceZone -> WatchItem -> PreFilter -> CandidateEvent

    业务规则:
        lower_price 和 upper_price 必须为正数，且 upper_price 不能低于 lower_price。
    """

    lower_price: Decimal = Field(gt=0)
    upper_price: Decimal = Field(gt=0)
    label: str | None = None

    @field_validator("label")
    @classmethod
    def _optional_label(cls, value: str | None) -> str | None:
        return ensure_non_empty(value) if value is not None else None

    @model_validator(mode="after")
    def _zone_order_is_valid(self) -> "PriceZone":
        # 决策注释: 价格区间倒置会让接近/突破判断失去业务含义。
        if self.upper_price < self.lower_price:
            raise ValueError("upper_price must be greater than or equal to lower_price")
        return self
