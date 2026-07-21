"""Run one Crypto analysis chain and persist its decision facts to loot_test."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Sequence
from uuid import UUID, uuid4

import sqlalchemy as sa

from loot.application import (
    CryptoRunMode,
    CryptoRunOnceCommand,
    CryptoRunOnceService,
    DemoBreakoutCryptoProvider,
    default_btc_usdt_instrument,
)
from loot.domains.crypto import CryptoPolicyGate, OkxRestCryptoProvider
from loot.persistence import (
    PostgresAnalysisRepository,
    PostgresAuthorizationRepository,
    PostgresSignalWorkflow,
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
    parser.add_argument("--watch-item-id", type=UUID, default=None)
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

        # 2. 按运行模式装配只读行情 Provider；其余授权和持久化边界保持一致。
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

        # 3. 每次默认使用新的 WatchItem 身份，允许重复 demo 且不碰已有活跃 Signal。
        result = service.run(
            CryptoRunOnceCommand(
                mode=mode,
                instrument=default_btc_usdt_instrument(),
                watch_item_id=args.watch_item_id or uuid4(),
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
