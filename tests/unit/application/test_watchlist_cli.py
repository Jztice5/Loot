"""REQ-0014 本地管理与 Run-Once CLI 合同测试。"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from uuid import uuid4

from scripts import manage_crypto_watch, run_crypto_once
from loot.application import CreateCryptoWatchItemCommand, CryptoWatchlistService

from tests.unit.application.test_watchlist import _MemoryWatchlistRepository


class CryptoWatchlistCliTest(unittest.TestCase):
    """固定管理命令输出与 Run-Once 监控身份入口。"""

    def test_manage_parser_builds_explicit_lifecycle_command(self) -> None:
        """生命周期命令必须显式携带 WatchItem 身份和期望版本。"""

        watch_item_id = uuid4()

        args = manage_crypto_watch.build_parser().parse_args(
            [
                "pause",
                "--watch-item-id",
                str(watch_item_id),
                "--expected-version",
                "3",
            ]
        )

        self.assertEqual(args.command, "pause")
        self.assertEqual(args.watch_item_id, watch_item_id)
        self.assertEqual(args.expected_version, 3)

    def test_manage_result_contains_follow_up_identity_without_credentials(self) -> None:
        """创建输出提供后续命令所需身份，且不暴露数据库配置。"""

        request_id = uuid4()
        repository = _MemoryWatchlistRepository()
        service = CryptoWatchlistService(repository)
        result = service.create(
            CreateCryptoWatchItemCommand(
                request_id=request_id,
                watch_item_id=uuid4(),
                user_id=uuid4(),
                instrument=manage_crypto_watch.default_btc_usdt_instrument(),
                occurred_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
            )
        )

        payload = manage_crypto_watch._result_dict(request_id, result)

        self.assertEqual(payload["request_id"], str(request_id))
        self.assertEqual(payload["watch_item_status"], "ACTIVE")
        self.assertEqual(payload["watch_item_version"], 0)
        self.assertEqual(payload["subscriptions"][0]["timeframe"], "1h")
        self.assertNotIn("database_url", payload)

    def test_run_once_parser_requires_persisted_watch_item_id(self) -> None:
        """Run-Once 不再允许临时生成 WatchItem 身份。"""

        with self.assertRaises(SystemExit):
            run_crypto_once.build_parser().parse_args(["--mode", "demo"])

        watch_item_id = uuid4()
        args = run_crypto_once.build_parser().parse_args(
            ["--mode", "demo", "--watch-item-id", str(watch_item_id)]
        )

        self.assertEqual(args.watch_item_id, watch_item_id)

    def test_cli_error_output_is_stable_and_credential_free(self) -> None:
        """CLI 错误只输出稳定元数据，不拼接底层异常或 DSN。"""

        output = io.StringIO()
        with redirect_stdout(output):
            manage_crypto_watch._print_error(
                "WATCHLIST_COMMAND_FAILED",
                "OperationalError",
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["reason"], "WATCHLIST_COMMAND_FAILED")
        self.assertEqual(payload["error_type"], "OperationalError")
        self.assertNotIn("database_url", payload)


if __name__ == "__main__":
    unittest.main()
