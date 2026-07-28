"""Materialize and execute Crypto H1 monitoring runs in loot_test."""

from __future__ import annotations

import argparse
import json
import os
import socket
import time
from datetime import UTC, datetime
from typing import Sequence

import sqlalchemy as sa

from loot.application import (
    CryptoMonitoringWorker,
    CryptoRunMode,
    CryptoRunOnceService,
    DemoBreakoutCryptoProvider,
    MonitoringWorkerTickStatus,
)
from loot.domains.crypto import CryptoPolicyGate, OkxRestCryptoProvider
from loot.persistence import (
    PostgresAnalysisRepository,
    PostgresAuthorizationRepository,
    PostgresMonitoringRepository,
    PostgresSignalWorkflow,
    create_postgres_engine,
)
from loot.persistence.config import load_local_setting


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit Worker process contract."""

    parser = argparse.ArgumentParser(
        description="Run the Crypto H1 monitoring worker against loot_test.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="execute at most one due run")
    mode.add_argument("--loop", action="store_true", help="poll continuously")
    parser.add_argument(
        "--provider",
        choices=("live", "demo"),
        default="live",
        help="live uses OKX public REST; demo is allowed only with --once",
    )
    parser.add_argument("--worker-id", default=_default_worker_id())
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--okx-timeout-seconds", type=float, default=10.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one tick or a stoppable polling loop with credential-free output."""

    args = build_parser().parse_args(argv)
    if args.poll_seconds <= 0 or args.okx_timeout_seconds <= 0:
        _print_error("INVALID_RUNTIME_ARGUMENT", "ConfigurationError")
        return 2
    if args.loop and args.provider == "demo":
        _print_error("DEMO_LOOP_NOT_ALLOWED", "ConfigurationError")
        return 2

    database_url = load_local_setting("LOOT_TEST_DATABASE_URL")
    if database_url is None:
        _print_error("DATABASE_NOT_CONFIGURED", "ConfigurationError")
        return 2

    engine = None
    try:
        engine = create_postgres_engine(database_url)
        with engine.connect() as connection:
            database_name = connection.execute(
                sa.text("SELECT current_database()")
            ).scalar_one()
            monitoring_tables_exist = all(
                sa.inspect(connection).has_table(table_name, schema="loot")
                for table_name in ("monitoring_runs", "monitoring_run_attempts")
            )
        if database_name != "loot_test":
            _print_error("TEST_DATABASE_REQUIRED", "DatabaseSafetyError")
            return 2
        if not monitoring_tables_exist:
            _print_error("MIGRATION_0003_REQUIRED", "DatabaseSchemaError")
            return 2

        provider = (
            DemoBreakoutCryptoProvider(received_at=datetime.now(UTC))
            if args.provider == "demo"
            else OkxRestCryptoProvider(timeout_seconds=args.okx_timeout_seconds)
        )
        authorization_repository = PostgresAuthorizationRepository(engine)
        worker = CryptoMonitoringWorker(
            repository=PostgresMonitoringRepository(engine),
            provider=provider,
            run_once_service=CryptoRunOnceService(
                provider=provider,
                signal_workflow=PostgresSignalWorkflow(engine),
                analysis_repository=PostgresAnalysisRepository(engine),
                policy_gate=CryptoPolicyGate(authorization_repository),
            ),
            worker_id=args.worker_id,
            run_mode=(
                CryptoRunMode.DEMO if args.provider == "demo" else CryptoRunMode.LIVE
            ),
        )

        if not args.loop:
            result = worker.tick()
            print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
            return 1 if result.status == MonitoringWorkerTickStatus.FAILED else 0

        while True:
            result = worker.tick()
            print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True), flush=True)
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        return 0
    except Exception as error:  # noqa: BLE001 - process boundary returns redacted diagnostics.
        _print_error("WORKER_FAILED", type(error).__name__)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


def _default_worker_id() -> str:
    """Build a process-local owner label without network or credential data."""

    return f"{socket.gethostname()}:{os.getpid()}"


def _print_error(reason: str, error_type: str) -> None:
    """Print stable error metadata without DSN, SQL or provider payloads."""

    print(
        json.dumps(
            {"status": "FAILED", "reason": reason, "error_type": error_type},
            ensure_ascii=True,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
