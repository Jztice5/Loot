"""Replay 数据集契约。

业务描述:
    定义历史行情数据集的质量报告和内容寻址 manifest，作为采集器与 Replay Engine
    之间的稳定边界。

业务场景:
    - 历史 Provider 分页拉取 MarketBar 后生成完整性报告。
    - 质量门禁通过后发布确定性 manifest。
    - 后续 Replay 在新设备加载数据时重新校验身份和内容摘要。

业务原因:
    历史数据缺失、重复或被 Provider 修正都会改变统计结论，必须先成为可审计事实，
    不能依赖某台开发机上的临时文件状态。

调用链:
    Historical Provider -> Quality Report -> Dataset Manifest -> Replay Engine

业务规则:
    时间统一使用 UTC；质量问题字段使用不可变 tuple；数据集 identity 不包含采集时钟。
"""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, field_validator, model_validator

from loot.contracts.base import ContractModel, ensure_non_empty, ensure_utc_datetime
from loot.contracts.enums import Market, Timeframe

HISTORICAL_DATASET_SCHEMA_VERSION = "crypto.market-bars.v1"


class HistoricalDatasetQualityReport(ContractModel):
    """历史行情数据集完整性报告。

    业务描述:
        汇总目标区间的数量、连续性、闭合状态和身份问题，并给出是否允许发布 manifest。

    调用链:
        assess_historical_dataset_quality -> HistoricalDatasetQualityReport
        -> HistoricalBarDataset.build

    业务规则:
        `passed=True` 只允许在数量完整且所有问题集合为空时出现。
    """

    provider: str
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    start_bar_closed_at: datetime
    end_bar_closed_at: datetime
    expected_bar_count: int = Field(ge=1)
    actual_bar_count: int = Field(ge=0)
    first_bar_closed_at: datetime | None = None
    last_bar_closed_at: datetime | None = None
    missing_bar_closed_at: tuple[datetime, ...] = ()
    duplicate_provider_event_ids: tuple[str, ...] = ()
    duplicate_bar_closed_at: tuple[datetime, ...] = ()
    unclosed_provider_event_ids: tuple[str, ...] = ()
    identity_mismatch_provider_event_ids: tuple[str, ...] = ()
    out_of_range_provider_event_ids: tuple[str, ...] = ()
    out_of_order_provider_event_ids: tuple[str, ...] = ()
    passed: bool

    @field_validator("provider")
    @classmethod
    def _provider_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator(
        "start_bar_closed_at",
        "end_bar_closed_at",
        "first_bar_closed_at",
        "last_bar_closed_at",
    )
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc_datetime(value) if value is not None else None

    @field_validator("missing_bar_closed_at", "duplicate_bar_closed_at")
    @classmethod
    def _timestamp_collections_are_utc(
        cls,
        values: tuple[datetime, ...],
    ) -> tuple[datetime, ...]:
        return tuple(ensure_utc_datetime(value) for value in values)

    @field_validator(
        "duplicate_provider_event_ids",
        "unclosed_provider_event_ids",
        "identity_mismatch_provider_event_ids",
        "out_of_range_provider_event_ids",
        "out_of_order_provider_event_ids",
    )
    @classmethod
    def _event_ids_are_present(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(ensure_non_empty(value) for value in values)

    @model_validator(mode="after")
    def _report_is_consistent(self) -> "HistoricalDatasetQualityReport":
        if self.end_bar_closed_at < self.start_bar_closed_at:
            raise ValueError("end_bar_closed_at must not be earlier than start_bar_closed_at")
        if (self.first_bar_closed_at is None) != (self.last_bar_closed_at is None):
            raise ValueError("first and last bar timestamps must be present together")
        if (
            self.first_bar_closed_at is not None
            and self.last_bar_closed_at is not None
            and self.last_bar_closed_at < self.first_bar_closed_at
        ):
            raise ValueError("last_bar_closed_at must not be earlier than first_bar_closed_at")

        has_quality_issue = any(
            (
                self.missing_bar_closed_at,
                self.duplicate_provider_event_ids,
                self.duplicate_bar_closed_at,
                self.unclosed_provider_event_ids,
                self.identity_mismatch_provider_event_ids,
                self.out_of_range_provider_event_ids,
                self.out_of_order_provider_event_ids,
            )
        )
        expected_passed = (
            self.actual_bar_count == self.expected_bar_count and not has_quality_issue
        )
        if self.passed != expected_passed:
            raise ValueError("passed must match dataset quality facts")
        return self


class HistoricalDatasetManifest(ContractModel):
    """内容寻址的历史行情数据集清单。

    业务描述:
        固定一个已经通过质量门禁的数据版本，供文件工件和 ReplayRun 引用。

    调用链:
        HistoricalBarDataset.build -> HistoricalDatasetManifest -> artifact/Replay

    业务规则:
        dataset_id、dataset_key 和 content_hash 绑定完整行情内容；generated_at 只用于审计。
    """

    dataset_id: UUID
    dataset_key: str
    schema_version: str
    provider: str
    market: Market
    instrument_id: UUID
    timeframe: Timeframe
    start_bar_closed_at: datetime
    end_bar_closed_at: datetime
    first_bar_closed_at: datetime
    last_bar_closed_at: datetime
    expected_bar_count: int = Field(ge=1)
    actual_bar_count: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime

    @field_validator("dataset_key", "schema_version", "provider")
    @classmethod
    def _text_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator(
        "start_bar_closed_at",
        "end_bar_closed_at",
        "first_bar_closed_at",
        "last_bar_closed_at",
        "generated_at",
    )
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _manifest_range_is_consistent(self) -> "HistoricalDatasetManifest":
        if self.end_bar_closed_at < self.start_bar_closed_at:
            raise ValueError("end_bar_closed_at must not be earlier than start_bar_closed_at")
        if self.first_bar_closed_at != self.start_bar_closed_at:
            raise ValueError("first_bar_closed_at must match requested start")
        if self.last_bar_closed_at != self.end_bar_closed_at:
            raise ValueError("last_bar_closed_at must match requested end")
        if self.actual_bar_count != self.expected_bar_count:
            raise ValueError("published dataset counts must match")
        expected_key = ":".join(
            (
                self.schema_version,
                self.provider,
                str(self.instrument_id),
                self.timeframe.value,
                self.start_bar_closed_at.isoformat(timespec="microseconds"),
                self.end_bar_closed_at.isoformat(timespec="microseconds"),
                self.content_hash,
            )
        )
        if self.dataset_key != expected_key:
            raise ValueError("dataset_key must match manifest identity and content")
        if self.dataset_id != uuid5(NAMESPACE_URL, expected_key):
            raise ValueError("dataset_id must match dataset_key")
        return self
