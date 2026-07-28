"""Run one Crypto analysis chain and persist its decision facts to loot_test."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Sequence
from uuid import UUID

import sqlalchemy as sa

from loot.application import (
    CryptoRunMode,
    CryptoRunOnceCommand,
    CryptoRunOnceService,
    DemoBreakoutCryptoProvider,
)
from loot.contracts import Timeframe
from loot.domains.crypto import CryptoPolicyGate, OkxRestCryptoProvider
from loot.persistence import (
    PostgresAnalysisRepository,
    PostgresAuthorizationRepository,
    PostgresSignalWorkflow,
    PostgresWatchlistRepository,
    create_postgres_engine,
)
from loot.persistence.config import load_local_setting


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit, non-interactive Run-Once CLI contract."""

    parser = argparse.ArgumentParser(
        description="Run one Crypto decision chain against loot_test.",
    )
    parser.add_argument(
        "--mode",
        choices=tuple(mode.value for mode in CryptoRunMode),
        default=CryptoRunMode.DEMO.value,
    )
    parser.add_argument("--watch-item-id", type=UUID, required=True)
    parser.add_argument("--context-digest", default="crypto-run-once.cli.v1")
    parser.add_argument("--okx-timeout-seconds", type=float, default=10.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute Run-Once and print a credential-free JSON summary."""

    args = build_parser().parse_args(argv)
    database_url = load_local_setting("LOOT_TEST_DATABASE_URL")
    if database_url is None:
        _print_error("DATABASE_NOT_CONFIGURED", "ConfigurationError")
        return 2

    engine = None
    try:
        engine = create_postgres_engine(database_url)
        # 1. 在任何写入前确认实际数据库名，防止本地配置误指向非测试库。
        with engine.connect() as connection:
            database_name = connection.execute(
                sa.text("SELECT current_database()")
            ).scalar_one()
        if database_name != "loot_test":
            _print_error("TEST_DATABASE_REQUIRED", "DatabaseSafetyError")
            return 2

        # 2. 先加载 ACTIVE 的持久化监控身份，任何无效配置都在访问 Provider 前拒绝。
        run_configuration = PostgresWatchlistRepository(
            engine
        ).load_run_configuration(args.watch_item_id, Timeframe.H1)

        # 3. 按运行模式装配只读行情 Provider；其余授权和持久化边界保持一致。
        mode = CryptoRunMode(args.mode)
        provider = (
            DemoBreakoutCryptoProvider(received_at=datetime.now(UTC))
            if mode == CryptoRunMode.DEMO
            else OkxRestCryptoProvider(timeout_seconds=args.okx_timeout_seconds)
        )
        authorization_repository = PostgresAuthorizationRepository(engine)
        service = CryptoRunOnceService(
            provider=provider,
            signal_workflow=PostgresSignalWorkflow(engine),
            analysis_repository=PostgresAnalysisRepository(engine),
            policy_gate=CryptoPolicyGate(authorization_repository),
        )

        # 4. Run-Once 使用数据库中的 Instrument、WatchItem 版本和 Subscription 周期。
        result = service.run(
            CryptoRunOnceCommand(
                mode=mode,
                instrument=run_configuration.instrument,
                watch_item_id=run_configuration.watch_item.id,
                timeframe=run_configuration.subscription.timeframe,
                watch_item_version=run_configuration.watch_item.version,
                context_digest=args.context_digest,
            )
        )
        print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as error:  # noqa: BLE001 - CLI converts failures to safe output.
        _print_error("RUN_FAILED", type(error).__name__)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


def _print_error(reason: str, error_type: str) -> None:
    """Print a stable error without echoing DSNs or driver diagnostics."""

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
