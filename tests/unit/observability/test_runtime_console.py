"""Verify the read-only Runtime Console HTTP boundary."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from loot.observability.runtime_console import (
    RuntimeConsoleApplication,
    RuntimeConsoleDatabaseError,
    RuntimeConsoleDatabaseNameError,
)


class _FakeReader:
    """Return deterministic read models without opening a database connection."""

    def read_overview(self) -> dict[str, Any]:
        return {
            "database": {"name": "loot_test", "status": "healthy"},
            "facts": {"decision_proposals": 1, "signals": 1, "unpublished_outbox": 0},
            "latest_activity_at": None,
            "capabilities": {"run_once": "available"},
        }

    def read_decision_chains(self, limit: int) -> list[dict[str, Any]]:
        return [{"limit_received": limit}]

    def read_signals(self, limit: int) -> list[dict[str, Any]]:
        return [{"limit_received": limit}]

    def read_unpublished_outbox(self, limit: int) -> list[dict[str, Any]]:
        return [{"limit_received": limit}]


class _EmptyReader(_FakeReader):
    """Represent a healthy database before the first persisted decision chain."""

    def read_overview(self) -> dict[str, Any]:
        return {
            "database": {"name": "loot_test", "status": "healthy"},
            "facts": {"decision_proposals": 0, "signals": 0, "unpublished_outbox": 0},
            "latest_activity_at": None,
            "capabilities": {"run_once": "available"},
        }

    def read_decision_chains(self, limit: int) -> list[dict[str, Any]]:
        return []


class _UnavailableReader(_FakeReader):
    """Simulate a connection or read-only query failure."""

    def read_overview(self) -> dict[str, Any]:
        raise RuntimeConsoleDatabaseError("test database is unavailable")


class _WrongDatabaseReader(_FakeReader):
    """Simulate a configured connection that points outside loot_test."""

    def read_overview(self) -> dict[str, Any]:
        raise RuntimeConsoleDatabaseNameError("wrong database")


class RuntimeConsoleHttpTest(unittest.TestCase):
    """Ensure the local console exposes only bounded read operations."""

    def setUp(self) -> None:
        self.index_path = (
            Path(__file__).parents[3]
            / "src"
            / "loot"
            / "observability"
            / "static"
            / "index.html"
        )
        self.application = RuntimeConsoleApplication(
            _FakeReader(),  # type: ignore[arg-type]
            index_path=self.index_path,
        )

    def _request(
            self,
            path: str,
            method: str = "GET",
    ) -> tuple[str, dict[str, str], bytes]:
        response: dict[str, Any] = {}
        path_info, _, query_string = path.partition("?")

        def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> None:
            response["status"] = status
            response["headers"] = dict(headers)

        body = b"".join(
            self.application(
                {
                    "REQUEST_METHOD": method,
                    "PATH_INFO": path_info,
                    "QUERY_STRING": query_string,
                },
                start_response,
            )
        )
        return response["status"], response["headers"], body

    def test_index_is_available(self) -> None:
        status, headers, body = self._request("/")

        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn(b"Loot Runtime Console", body)

    def test_overview_is_read_only_json(self) -> None:
        status, headers, body = self._request("/api/overview")

        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body)["database"]["name"], "loot_test")

    def test_non_get_is_rejected(self) -> None:
        status, headers, body = self._request("/api/overview", method="POST")

        self.assertEqual(status, "405 Method Not Allowed")
        self.assertEqual(headers["Allow"], "GET")
        self.assertEqual(json.loads(body)["error"], "READ_ONLY")

    def test_limit_is_forwarded_to_reader(self) -> None:
        status, _, body = self._request("/api/chains?limit=7")

        self.assertEqual(status, "200 OK")
        self.assertEqual(json.loads(body)["items"][0]["limit_received"], 7)

    def test_limit_must_be_bounded(self) -> None:
        status, _, body = self._request("/api/chains?limit=101")

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(json.loads(body)["error"], "INVALID_REQUEST")

    def test_database_failure_is_redacted(self) -> None:
        self.application = RuntimeConsoleApplication(
            _UnavailableReader(),  # type: ignore[arg-type]
            index_path=self.index_path,
        )

        status, _, body = self._request("/api/overview")

        payload = json.loads(body)
        self.assertEqual(status, "503 Service Unavailable")
        self.assertEqual(payload["error"], "DATABASE_UNAVAILABLE")
        self.assertNotIn("test database", payload["message"])

    def test_wrong_database_is_rejected(self) -> None:
        self.application = RuntimeConsoleApplication(
            _WrongDatabaseReader(),  # type: ignore[arg-type]
            index_path=self.index_path,
        )

        status, _, body = self._request("/api/overview")

        payload = json.loads(body)
        self.assertEqual(status, "503 Service Unavailable")
        self.assertEqual(payload["error"], "DATABASE_NOT_ALLOWED")
        self.assertEqual(payload["message"], "only loot_test is allowed")

    def test_empty_decision_chain_returns_an_empty_collection(self) -> None:
        self.application = RuntimeConsoleApplication(
            _EmptyReader(),  # type: ignore[arg-type]
            index_path=self.index_path,
        )

        status, _, body = self._request("/api/chains")

        self.assertEqual(status, "200 OK")
        self.assertEqual(json.loads(body), {"items": []})


if __name__ == "__main__":
    unittest.main()
