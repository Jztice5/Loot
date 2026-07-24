"""Loot 契约模型基础设施。

业务描述:
    为所有跨模块契约提供统一的不可变 Pydantic 基类和共享字段校验器。

业务原因:
    Loot 后续会有 Provider、PreFilter、Skill、Policy Gate、Signal State Machine
    等多个生产者和消费者。契约层必须先阻止字段漂移、时间歧义和静默修改。

调用链:
    业务契约类 -> ContractModel -> Pydantic 校验 -> 事件/数据库/测试消费者

业务规则:
    - 契约默认不可变，消费者不能在内存中悄悄改写事实。
    - 禁止额外字段，避免生产者和消费者对同一事件理解不一致。
    - 跨模块时间必须是 timezone-aware，并归一化为 UTC。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """跨模块契约基类。

    业务描述:
        所有跨模块 payload、事件和投影都继承该基类，获得统一校验策略。

    业务规则:
        `frozen=True` 保证契约实例不可变；`extra="forbid"` 保证新字段必须先进入
        契约设计，而不是由某个生产者私自添加。
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
    )


def ensure_non_empty(value: str) -> str:
    """校验业务标识文本不能为空。"""

    if not value or not value.strip():
        raise ValueError("must not be empty")
    return value.strip()


def ensure_utc_datetime(value: datetime) -> datetime:
    """校验并归一化跨模块时间。"""

    # 注意: tzinfo 存在但 utcoffset 为 None 时仍是无效业务时间。
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value.astimezone(UTC)


def ensure_positive_decimal(value: Decimal | None, field_name: str) -> Decimal | None:
    """校验价格、数量、风控倍数等 Decimal 字段必须为正数。"""

    if value is not None and value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


JsonObject = dict[str, Any]
