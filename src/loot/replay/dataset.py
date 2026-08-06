"""历史行情数据集质量门禁与确定性身份。

业务描述:
    对指定闭合区间的 MarketBar 运行完整性检查，并只为通过门禁的数据生成内容寻址
    manifest。

业务场景:
    - OKX 历史分页完成后发布可供 Replay 使用的数据集。
    - 相同区间重抓时识别相同事实或 Provider 历史修正。
    - 缺失、重复和未闭合数据进入质量报告而不是统计样本。

业务原因:
    Replay 结果首先取决于输入事实是否完整稳定；没有确定性数据身份时，规则对比和
    未见样本验收都无法复现。

调用链:
    Historical Provider -> assess_historical_dataset_quality
    -> HistoricalBarDataset.build -> Manifest -> Replay

业务规则:
    V0.1 只支持连续 H1；manifest 生成时间和 MarketBar.received_at 不进入数据身份。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from loot.contracts.base import ensure_non_empty, ensure_utc_datetime
from loot.contracts.enums import Market, Timeframe
from loot.contracts.market_data import MarketBar, MarketSnapshot
from loot.contracts.replay import (
    HISTORICAL_DATASET_SCHEMA_VERSION,
    HistoricalDatasetManifest,
    HistoricalDatasetQualityReport,
)
from loot.contracts.serialization import canonical_json

_H1_DURATION = timedelta(hours=1)


class HistoricalDatasetQualityError(ValueError):
    """历史数据未通过发布门禁。

    业务点:
        异常保留完整 report，CLI 可以输出稳定诊断而不重新猜测失败原因。
    """

    def __init__(self, report: HistoricalDatasetQualityReport) -> None:
        super().__init__("historical dataset did not pass quality gate")
        self.report = report


class HistoricalDatasetArtifactError(ValueError):
    """历史数据集文件缺失、损坏或与 manifest 不一致。"""


@dataclass(frozen=True, slots=True)
class HistoricalBarDataset:
    """已经通过质量门禁的历史 K 线数据集。

    业务描述:
        把不可变 MarketBar、质量证据和内容寻址 manifest 绑定为一个 Replay 输入版本。

    调用链:
        HistoricalBarDataset.build -> quality gate -> MarketSnapshot hash -> manifest

    业务规则:
        bars 按 opened_at 升序；quality_report 必须通过；manifest 必须覆盖同一首尾区间。
    """

    manifest: HistoricalDatasetManifest
    quality_report: HistoricalDatasetQualityReport
    bars: tuple[MarketBar, ...]

    @classmethod
    def build(
        cls,
        *,
        provider: str,
        market: Market,
        instrument_id: UUID,
        timeframe: Timeframe,
        start_bar_closed_at: datetime,
        end_bar_closed_at: datetime,
        bars: Iterable[MarketBar],
        generated_at: datetime,
    ) -> "HistoricalBarDataset":
        """校验历史输入并生成确定性数据集。

        调用链:
            normalize input -> quality report -> canonical content hash -> manifest

        幂等逻辑:
            相同区间和行情事实得到相同 dataset_id；采集/生成时钟变化不影响 identity。
        """

        normalized_provider = ensure_non_empty(provider)
        normalized_start = ensure_utc_datetime(start_bar_closed_at)
        normalized_end = ensure_utc_datetime(end_bar_closed_at)
        normalized_generated_at = ensure_utc_datetime(generated_at)
        input_bars = tuple(bars)

        quality_report = assess_historical_dataset_quality(
            provider=normalized_provider,
            market=market,
            instrument_id=instrument_id,
            timeframe=timeframe,
            start_bar_closed_at=normalized_start,
            end_bar_closed_at=normalized_end,
            bars=input_bars,
        )
        if not quality_report.passed:
            raise HistoricalDatasetQualityError(quality_report)

        ordered_bars = tuple(sorted(input_bars, key=lambda bar: bar.opened_at))
        # 质量门禁已保证非空和闭合；使用最晚接收时钟只满足 Snapshot 审计约束。
        snapshot = MarketSnapshot.from_bars(
            market=market,
            instrument_id=instrument_id,
            timeframe=timeframe,
            source_provider=normalized_provider,
            as_of=max(bar.received_at for bar in ordered_bars),
            bars=ordered_bars,
        )
        dataset_key = _dataset_key(
            provider=normalized_provider,
            instrument_id=instrument_id,
            timeframe=timeframe,
            start_bar_closed_at=normalized_start,
            end_bar_closed_at=normalized_end,
            content_hash=snapshot.snapshot_content_hash,
        )
        manifest = HistoricalDatasetManifest(
            dataset_id=uuid5(NAMESPACE_URL, dataset_key),
            dataset_key=dataset_key,
            schema_version=HISTORICAL_DATASET_SCHEMA_VERSION,
            provider=normalized_provider,
            market=market,
            instrument_id=instrument_id,
            timeframe=timeframe,
            start_bar_closed_at=normalized_start,
            end_bar_closed_at=normalized_end,
            first_bar_closed_at=ordered_bars[0].closed_at,
            last_bar_closed_at=ordered_bars[-1].closed_at,
            expected_bar_count=quality_report.expected_bar_count,
            actual_bar_count=quality_report.actual_bar_count,
            content_hash=snapshot.snapshot_content_hash,
            generated_at=normalized_generated_at,
        )
        return cls(
            manifest=manifest,
            quality_report=quality_report,
            bars=ordered_bars,
        )


def assess_historical_dataset_quality(
    *,
    provider: str,
    market: Market,
    instrument_id: UUID,
    timeframe: Timeframe,
    start_bar_closed_at: datetime,
    end_bar_closed_at: datetime,
    bars: Iterable[MarketBar],
) -> HistoricalDatasetQualityReport:
    """收集历史 K 线完整性问题并返回不可变报告。

    业务点:
        校验器一次收集全部机械问题，让人工和 CLI 能看到完整缺口，而不是修一个再失败一个。

    调用链:
        Historical Provider/Artifact -> quality assessment -> report -> publication gate
    """

    normalized_provider = ensure_non_empty(provider)
    normalized_start = ensure_utc_datetime(start_bar_closed_at)
    normalized_end = ensure_utc_datetime(end_bar_closed_at)
    duration = _dataset_duration(timeframe)
    if normalized_end < normalized_start:
        raise ValueError("end_bar_closed_at must not be earlier than start_bar_closed_at")
    if not _is_h1_boundary(normalized_start) or not _is_h1_boundary(normalized_end):
        raise ValueError("historical H1 dataset boundaries must be exact UTC hours")

    input_bars = tuple(bars)
    expected_timestamps = _expected_closed_timestamps(
        normalized_start,
        normalized_end,
        duration,
    )
    provider_event_counts = Counter(bar.provider_event_id for bar in input_bars)
    closed_at_counts = Counter(bar.closed_at for bar in input_bars)

    valid_closed_timestamps = {
        bar.closed_at
        for bar in input_bars
        if bar.provider == normalized_provider
        and bar.market == market
        and bar.instrument_id == instrument_id
        and bar.timeframe == timeframe
        and bar.is_closed
        and normalized_start <= bar.closed_at <= normalized_end
    }
    identity_mismatches = tuple(
        sorted(
            {
                bar.provider_event_id
                for bar in input_bars
                if bar.provider != normalized_provider
                or bar.market != market
                or bar.instrument_id != instrument_id
                or bar.timeframe != timeframe
            }
        )
    )
    out_of_range = tuple(
        sorted(
            {
                bar.provider_event_id
                for bar in input_bars
                if bar.closed_at < normalized_start or bar.closed_at > normalized_end
            }
        )
    )
    out_of_order = _out_of_order_event_ids(input_bars)
    invalid_duration = tuple(
        sorted(
            {
                bar.provider_event_id
                for bar in input_bars
                if bar.closed_at - bar.opened_at != duration
            }
        )
    )
    misaligned_opened_at = tuple(
        sorted(
            {
                bar.provider_event_id
                for bar in input_bars
                if not _is_h1_boundary(bar.opened_at)
            }
        )
    )
    observed_timestamps = sorted(bar.closed_at for bar in input_bars)
    has_quality_issue = any(
        (
            set(expected_timestamps) - valid_closed_timestamps,
            [key for key, count in provider_event_counts.items() if count > 1],
            [key for key, count in closed_at_counts.items() if count > 1],
            [bar for bar in input_bars if not bar.is_closed],
            identity_mismatches,
            out_of_range,
            out_of_order,
            invalid_duration,
            misaligned_opened_at,
        )
    )
    passed = len(input_bars) == len(expected_timestamps) and not has_quality_issue

    return HistoricalDatasetQualityReport(
        provider=normalized_provider,
        market=market,
        instrument_id=instrument_id,
        timeframe=timeframe,
        start_bar_closed_at=normalized_start,
        end_bar_closed_at=normalized_end,
        expected_bar_count=len(expected_timestamps),
        actual_bar_count=len(input_bars),
        first_bar_closed_at=observed_timestamps[0] if observed_timestamps else None,
        last_bar_closed_at=observed_timestamps[-1] if observed_timestamps else None,
        missing_bar_closed_at=tuple(
            sorted(set(expected_timestamps) - valid_closed_timestamps)
        ),
        duplicate_provider_event_ids=tuple(
            sorted(key for key, count in provider_event_counts.items() if count > 1)
        ),
        duplicate_bar_closed_at=tuple(
            sorted(key for key, count in closed_at_counts.items() if count > 1)
        ),
        unclosed_provider_event_ids=tuple(
            sorted({bar.provider_event_id for bar in input_bars if not bar.is_closed})
        ),
        identity_mismatch_provider_event_ids=identity_mismatches,
        out_of_range_provider_event_ids=out_of_range,
        out_of_order_provider_event_ids=out_of_order,
        invalid_bar_duration_provider_event_ids=invalid_duration,
        misaligned_bar_opened_at_provider_event_ids=misaligned_opened_at,
        passed=passed,
    )


def write_historical_dataset(
    dataset: HistoricalBarDataset,
    output_root: str | Path,
) -> Path:
    """原子写入 manifest、质量报告和有序 MarketBar JSONL。

    业务点:
        每个 dataset_id 使用独立目录；同内容重试覆盖同名文件，不覆盖其他内容版本。

    调用链:
        HistoricalBarDataset -> canonical JSON -> atomic replace -> artifact directory
    """

    _assert_dataset_object_is_consistent(dataset)
    dataset_directory = Path(output_root) / str(dataset.manifest.dataset_id)
    dataset_directory.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        dataset_directory / "manifest.json",
        canonical_json(dataset.manifest) + "\n",
    )
    _atomic_write_text(
        dataset_directory / "quality-report.json",
        canonical_json(dataset.quality_report) + "\n",
    )
    bars_payload = "".join(f"{canonical_json(bar)}\n" for bar in dataset.bars)
    _atomic_write_text(dataset_directory / "bars.jsonl", bars_payload)
    return dataset_directory


def load_historical_dataset(dataset_directory: str | Path) -> HistoricalBarDataset:
    """加载文件工件并重新验证完整质量与内容 identity。

    业务点:
        文件只是一种传输形式，不能绕过强类型契约；任何手工修改或不完整复制都会在
        Replay 消费前失败。

    调用链:
        artifact files -> contract validation -> quality gate -> rebuilt manifest -> Replay
    """

    directory = Path(dataset_directory)
    try:
        stored_manifest = HistoricalDatasetManifest.model_validate_json(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        if directory.name != str(stored_manifest.dataset_id):
            raise HistoricalDatasetArtifactError(
                "historical dataset directory identity does not match manifest"
            )
        stored_quality_report = HistoricalDatasetQualityReport.model_validate_json(
            (directory / "quality-report.json").read_text(encoding="utf-8")
        )
        bars_text = (directory / "bars.jsonl").read_text(encoding="utf-8")
        lines = bars_text.splitlines()
        if not lines or any(not line.strip() for line in lines):
            raise HistoricalDatasetArtifactError(
                "bars.jsonl must contain one non-empty MarketBar per line"
            )
        bars = tuple(MarketBar.model_validate_json(line) for line in lines)
        rebuilt = HistoricalBarDataset.build(
            provider=stored_manifest.provider,
            market=stored_manifest.market,
            instrument_id=stored_manifest.instrument_id,
            timeframe=stored_manifest.timeframe,
            start_bar_closed_at=stored_manifest.start_bar_closed_at,
            end_bar_closed_at=stored_manifest.end_bar_closed_at,
            bars=bars,
            generated_at=stored_manifest.generated_at,
        )
    except HistoricalDatasetArtifactError:
        raise
    except (OSError, ValueError) as error:
        raise HistoricalDatasetArtifactError(
            "historical dataset artifact is missing or invalid"
        ) from error

    if rebuilt.manifest != stored_manifest:
        raise HistoricalDatasetArtifactError(
            "historical dataset manifest does not match bar content"
        )
    if rebuilt.quality_report != stored_quality_report:
        raise HistoricalDatasetArtifactError(
            "historical dataset quality report does not match bar content"
        )
    return rebuilt


def _assert_dataset_object_is_consistent(dataset: HistoricalBarDataset) -> None:
    """重新推导公开数据对象，防止直接 dataclass 构造绕过发布门禁。"""

    try:
        rebuilt = HistoricalBarDataset.build(
            provider=dataset.manifest.provider,
            market=dataset.manifest.market,
            instrument_id=dataset.manifest.instrument_id,
            timeframe=dataset.manifest.timeframe,
            start_bar_closed_at=dataset.manifest.start_bar_closed_at,
            end_bar_closed_at=dataset.manifest.end_bar_closed_at,
            bars=dataset.bars,
            generated_at=dataset.manifest.generated_at,
        )
    except ValueError as error:
        raise HistoricalDatasetArtifactError(
            "historical dataset object does not match its manifest"
        ) from error
    if rebuilt != dataset:
        raise HistoricalDatasetArtifactError(
            "historical dataset object does not match its manifest"
        )


def _dataset_duration(timeframe: Timeframe) -> timedelta:
    if timeframe != Timeframe.H1:
        raise ValueError("historical dataset v0.1 only supports H1")
    return _H1_DURATION


def _atomic_write_text(path: Path, content: str) -> None:
    """在目标目录内写临时文件并原子替换正式工件。"""

    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(content, encoding="utf-8", newline="\n")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _is_h1_boundary(value: datetime) -> bool:
    return value.minute == 0 and value.second == 0 and value.microsecond == 0


def _expected_closed_timestamps(
    start: datetime,
    end: datetime,
    duration: timedelta,
) -> tuple[datetime, ...]:
    count = int((end - start) / duration) + 1
    return tuple(start + duration * index for index in range(count))


def _out_of_order_event_ids(bars: tuple[MarketBar, ...]) -> tuple[str, ...]:
    out_of_order: set[str] = set()
    previous_opened_at: datetime | None = None
    for bar in bars:
        if previous_opened_at is not None and bar.opened_at <= previous_opened_at:
            out_of_order.add(bar.provider_event_id)
        previous_opened_at = bar.opened_at
    return tuple(sorted(out_of_order))


def _dataset_key(
    *,
    provider: str,
    instrument_id: UUID,
    timeframe: Timeframe,
    start_bar_closed_at: datetime,
    end_bar_closed_at: datetime,
    content_hash: str,
) -> str:
    return ":".join(
        (
            HISTORICAL_DATASET_SCHEMA_VERSION,
            provider,
            str(instrument_id),
            timeframe.value,
            start_bar_closed_at.isoformat(timespec="microseconds"),
            end_bar_closed_at.isoformat(timespec="microseconds"),
            content_hash,
        )
    )
