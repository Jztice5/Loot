"""Fetch and publish a versioned BTC-USDT H1 historical dataset."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from loot.application import default_btc_usdt_instrument
from loot.contracts import Instrument, MarketBar, Timeframe
from loot.contracts.base import ensure_utc_datetime
from loot.domains.crypto import OkxRestCryptoProvider
from loot.replay import (
    HistoricalBarDataset,
    HistoricalDatasetQualityError,
    write_historical_dataset,
)

Clock = Callable[[], datetime]


class _HistoricalBarProvider(Protocol):
    """CLI 所需的最小只读历史行情端口。"""

    @property
    def provider_name(self) -> str:
        """返回会进入数据集 identity 的 Provider 名称。"""

        ...

    def fetch_historical_bars(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        *,
        start_bar_closed_at: datetime,
        end_bar_closed_at: datetime,
        page_limit: int,
    ) -> tuple[MarketBar, ...]:
        """读取包含首尾的连续历史 K 线区间。"""

        ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_parser() -> argparse.ArgumentParser:
    """构建显式、无账户能力的历史数据采集命令合同。"""

    parser = argparse.ArgumentParser(
        description="Fetch a versioned OKX BTC-USDT H1 dataset for Replay.",
    )
    parser.add_argument(
        "--start-closed-at",
        type=_utc_datetime_argument,
        required=True,
        help="inclusive first H1 close in ISO-8601 form",
    )
    parser.add_argument(
        "--end-closed-at",
        type=_utc_datetime_argument,
        required=True,
        help="inclusive last H1 close in ISO-8601 form",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/replay"))
    parser.add_argument("--page-limit", type=int, default=300)
    parser.add_argument("--okx-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--request-interval-seconds", type=float, default=0.11)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    provider: _HistoricalBarProvider | None = None,
    clock: Clock = _utc_now,
) -> int:
    """采集、校验并写入数据集，输出不含凭证的稳定 JSON 摘要。

    调用链:
        parse UTC range -> OKX historical pages -> quality gate -> artifact -> summary

    失败策略:
        质量失败返回可行动计数；Provider、网络和文件异常只暴露稳定类型，不打印原始响应。
    """

    args = build_parser().parse_args(argv)
    if not 1 <= args.page_limit <= 300:
        _print_error("INVALID_PAGE_LIMIT", "ConfigurationError")
        return 2
    if args.okx_timeout_seconds <= 0 or args.request_interval_seconds < 0:
        _print_error("INVALID_PROVIDER_CONFIGURATION", "ConfigurationError")
        return 2

    selected_provider = provider or OkxRestCryptoProvider(
        timeout_seconds=args.okx_timeout_seconds,
        history_request_interval_seconds=args.request_interval_seconds,
    )
    instrument = default_btc_usdt_instrument()
    try:
        # 1. Provider 只负责读取和标准化，不决定数据集是否具备研究资格。
        bars = selected_provider.fetch_historical_bars(
            instrument,
            Timeframe.H1,
            start_bar_closed_at=args.start_closed_at,
            end_bar_closed_at=args.end_closed_at,
            page_limit=args.page_limit,
        )

        # 2. Builder 统一运行连续性、闭合状态和 identity 门禁。
        dataset = HistoricalBarDataset.build(
            provider=selected_provider.provider_name,
            market=instrument.market,
            instrument_id=instrument.instrument_id,
            timeframe=Timeframe.H1,
            start_bar_closed_at=args.start_closed_at,
            end_bar_closed_at=args.end_closed_at,
            bars=bars,
            generated_at=clock(),
        )

        # 3. 只有门禁通过的数据才生成 manifest 和 bars 工件。
        dataset_directory = write_historical_dataset(dataset, args.output_dir)
        print(
            json.dumps(
                {
                    "status": "COMPLETED",
                    "dataset_id": str(dataset.manifest.dataset_id),
                    "content_hash": dataset.manifest.content_hash,
                    "provider": dataset.manifest.provider,
                    "symbol": instrument.symbol,
                    "timeframe": dataset.manifest.timeframe.value,
                    "bar_count": dataset.manifest.actual_bar_count,
                    "start_bar_closed_at": dataset.manifest.start_bar_closed_at.isoformat(),
                    "end_bar_closed_at": dataset.manifest.end_bar_closed_at.isoformat(),
                    "dataset_directory": str(dataset_directory),
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 0
    except HistoricalDatasetQualityError as error:
        report = error.report
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason": "DATASET_QUALITY_FAILED",
                    "error_type": type(error).__name__,
                    "expected_bar_count": report.expected_bar_count,
                    "actual_bar_count": report.actual_bar_count,
                    "missing_bar_count": len(report.missing_bar_closed_at),
                    "duplicate_event_count": len(report.duplicate_provider_event_ids),
                    "unclosed_bar_count": len(report.unclosed_provider_event_ids),
                    "identity_mismatch_count": len(
                        report.identity_mismatch_provider_event_ids
                    ),
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 1
    except Exception as error:  # noqa: BLE001 - process boundary redacts diagnostics.
        _print_error("HISTORICAL_DATASET_FAILED", type(error).__name__)
        return 1


def _utc_datetime_argument(value: str) -> datetime:
    """解析带时区 ISO-8601 时间并归一化为 UTC。"""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ensure_utc_datetime(parsed)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a timezone-aware ISO-8601 datetime") from error


def _print_error(reason: str, error_type: str) -> None:
    """输出不含 URL、payload 和本地异常文本的稳定错误。"""

    print(
        json.dumps(
            {
                "status": "FAILED",
                "reason": reason,
                "error_type": error_type,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
