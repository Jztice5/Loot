"""Manage the local Crypto WatchItem lifecycle in loot_test."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any, Sequence
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sqlalchemy as sa

from loot.application import (
    ChangeWatchItemStatusCommand,
    CreateCryptoWatchItemCommand,
    CryptoWatchlistService,
    WatchlistMutationResult,
    default_btc_usdt_instrument,
)
from loot.persistence import PostgresWatchlistRepository, create_postgres_engine
from loot.persistence.config import load_local_setting
from loot.watchlist import WatchItemAction

_LOCAL_USER_ID = uuid5(NAMESPACE_URL, "loot:local-user")


def build_parser() -> argparse.ArgumentParser:
    """Build explicit create and lifecycle subcommands."""

    parser = argparse.ArgumentParser(
        description="Manage Crypto WatchItems in loot_test.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create BTC-USDT H1 monitoring")
    create.add_argument("--request-id", type=UUID, default=None)
    create.add_argument("--watch-item-id", type=UUID, default=None)
    create.add_argument("--user-id", type=UUID, default=_LOCAL_USER_ID)
    create.add_argument(
        "--monitoring-profile",
        default="crypto.structure-breakout.v1",
    )

    for action in ("pause", "resume", "archive"):
        lifecycle = subparsers.add_parser(action)
        lifecycle.add_argument("--request-id", type=UUID, default=None)
        lifecycle.add_argument("--watch-item-id", type=UUID, required=True)
        lifecycle.add_argument("--expected-version", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one WatchItem command and print a credential-free result."""

    args = build_parser().parse_args(argv)
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
        if database_name != "loot_test":
            _print_error("TEST_DATABASE_REQUIRED", "DatabaseSafetyError")
            return 2

        service = CryptoWatchlistService(PostgresWatchlistRepository(engine))
        now = datetime.now(UTC)
        request_id = args.request_id or uuid4()
        if args.command == "create":
            result = service.create(
                CreateCryptoWatchItemCommand(
                    request_id=request_id,
                    watch_item_id=args.watch_item_id or uuid4(),
                    user_id=args.user_id,
                    instrument=default_btc_usdt_instrument(),
                    monitoring_profile=args.monitoring_profile,
                    occurred_at=now,
                )
            )
        else:
            result = service.change_status(
                ChangeWatchItemStatusCommand(
                    request_id=request_id,
                    watch_item_id=args.watch_item_id,
                    expected_version=args.expected_version,
                    action=WatchItemAction(args.command.upper()),
                    occurred_at=now,
                )
            )
        print(json.dumps(_result_dict(request_id, result), sort_keys=True))
        return 0
    except Exception as error:  # noqa: BLE001 - CLI exposes only stable error metadata.
        _print_error("WATCHLIST_COMMAND_FAILED", type(error).__name__)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


def _result_dict(
        request_id: UUID,
        result: WatchlistMutationResult,
) -> dict[str, Any]:
    """Build a compact result for subsequent lifecycle or Run-Once commands."""

    return {
        "request_id": str(request_id),
        "watch_item_id": str(result.watch_item.id),
        "watch_item_status": result.watch_item.status.value,
        "watch_item_version": result.watch_item.version,
        "instrument_id": str(result.instrument.instrument_id),
        "subscriptions": [
            {
                "subscription_id": str(item.id),
                "timeframe": item.timeframe.value,
                "status": item.status.value,
                "config_version": item.config_version,
                "route_key": item.route_key,
            }
            for item in result.subscriptions
        ],
        "duplicate": result.duplicate,
    }


def _print_error(reason: str, error_type: str) -> None:
    """Print stable failure metadata without database diagnostics."""

    print(
        json.dumps(
            {"status": "FAILED", "reason": reason, "error_type": error_type},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
