"""Read-only Runtime Console application and PostgreSQL query adapter.

业务描述:
    为本地开发者提供现有 Crypto 决策事实的只读观察入口，聚合决策链、Signal、Outbox
    和数据库健康状态，不创建或修改任何业务状态。
业务场景:
    开发者运行 Runtime Console 后，通过浏览器查看 loot_test 中已经持久化的 Run-Once
    决策链，定位 Proposal、Policy、Ticket、Signal 和 Outbox 的关联关系。
业务原因:
    当前系统还没有常驻 Worker、Run ledger 或 Alert Center，因此观察台必须展示真实已有事实，
    并明确标识尚未实现的能力，避免使用静态假数据制造“系统正在运行”的错觉。
调用链:
    WSGI GET -> RuntimeSnapshotReader -> PostgreSQL read-only transaction -> JSON / HTML

业务规则:
    - 只允许 GET 请求；页面和 API 不提供业务写操作。
    - 只允许连接 loot_test；当前数据库名不匹配时拒绝返回业务数据。
    - 查询结果只包含脱敏摘要和关联 ID，不返回 DSN、密码或完整 JSON payload。
    - 数据库错误由 API 转换为可识别的降级响应，不把异常堆栈暴露给浏览器。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Connection

from loot.persistence.schema import (
    decision_proposal_evidence,
    decision_proposals,
    decision_tickets,
    evidence_sets,
    inbox_messages,
    outbox_events,
    policy_evaluations,
    signal_instances,
    signal_transitions,
)

_STATIC_INDEX = Path(__file__).with_name("static") / "index.html"
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


class RuntimeConsoleDatabaseError(RuntimeError):
    """数据库不可用或只读查询失败。"""


class RuntimeConsoleDatabaseNameError(RuntimeConsoleDatabaseError):
    """数据库不是 Runtime Console 允许读取的 loot_test。"""


def _iso_datetime(value: datetime | None) -> str | None:
    """将数据库 UTC 时间转换为前端稳定使用的 ISO-8601 字符串。"""

    return value.isoformat() if value is not None else None


def _uuid(value: Any) -> str | None:
    """将 UUID 或空值转换为 API 可序列化的摘要值。"""

    return str(value) if value is not None else None


class RuntimeSnapshotReader:
    """读取 Runtime Console 所需的 PostgreSQL 事实摘要。

    业务描述:
        将现有决策持久化表转换为观察台所需的概览、决策链、Signal 和 Outbox 读模型。
    业务场景:
        本地开发者通过浏览器查询 loot_test，快速判断 Run-Once 决策链是否完整、Outbox
        是否存在未发布事实，以及当前 Signal 投影处于什么状态。
    业务原因:
        观察台不能依赖领域应用服务重新运行决策，也不能因查看页面而写入 inbox、outbox
        或 Signal；所有查询必须在只读事务内完成。
    调用链:
        read_* -> _read -> SET TRANSACTION READ ONLY -> SQLAlchemy Core SELECT

    业务规则:
        - 每次请求都检查实际数据库名，只允许 ``loot_test``。
        - 只读取已定义的 SQLAlchemy Core 表，不拼接用户输入为 SQL。
        - limit 由 HTTP 层限制在 1 到 100，避免观察台查询无限扩大。
    """

    allowed_database = "loot_test"

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _read(self, callback: Callable[[Connection], Any]) -> Any:
        """在只读事务中校验目标库并执行一个查询聚合。

        调用链:
            read_* -> _read -> current_database -> callback SELECT -> commit/rollback
        """

        try:
            with self._engine.connect() as connection:
                with connection.begin():
                    connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                    database_name = connection.execute(
                        sa.text("SELECT current_database()")
                    ).scalar_one()
                    if database_name != self.allowed_database:
                        raise RuntimeConsoleDatabaseNameError(
                            f"Runtime Console only allows {self.allowed_database}"
                        )
                    return callback(connection)
        except RuntimeConsoleDatabaseError:
            raise
        except SQLAlchemyError as exc:
            raise RuntimeConsoleDatabaseError("read-only database query failed") from exc

    @staticmethod
    def _count(connection: Connection, table: sa.Table, condition: Any = None) -> int:
        query = sa.select(sa.func.count()).select_from(table)
        if condition is not None:
            query = query.where(condition)
        return int(connection.execute(query).scalar_one())

    @staticmethod
    def _latest_timestamp(
            connection: Connection,
            table: sa.Table,
            column: sa.Column,
    ) -> datetime | None:
        return connection.execute(sa.select(sa.func.max(column)).select_from(table)).scalar_one()

    def read_overview(self) -> dict[str, Any]:
        """读取数据库健康、事实数量和当前版本能力摘要。"""

        def query(connection: Connection) -> dict[str, Any]:
            timestamps = (
                self._latest_timestamp(connection, decision_proposals, decision_proposals.c.created_at),
                self._latest_timestamp(connection, signal_instances, signal_instances.c.updated_at),
                self._latest_timestamp(connection, outbox_events, outbox_events.c.occurred_at),
            )
            latest_activity = max((value for value in timestamps if value is not None), default=None)
            return {
                "database": {"name": self.allowed_database, "status": "healthy"},
                "facts": {
                    "inbox_messages": self._count(connection, inbox_messages),
                    "evidence_sets": self._count(connection, evidence_sets),
                    "decision_proposals": self._count(connection, decision_proposals),
                    "policy_evaluations": self._count(connection, policy_evaluations),
                    "decision_tickets": self._count(connection, decision_tickets),
                    "signals": self._count(connection, signal_instances),
                    "signal_transitions": self._count(connection, signal_transitions),
                    "unpublished_outbox": self._count(
                        connection,
                        outbox_events,
                        outbox_events.c.published_at.is_(None),
                    ),
                },
                "latest_activity_at": _iso_datetime(latest_activity),
                "capabilities": {
                    "run_once": "available",
                    "decision_persistence": "available",
                    "monitoring_worker": "not_implemented",
                    "alert_center": "not_implemented",
                    "replay": "not_implemented",
                },
            }

        return self._read(query)

    def read_decision_chains(self, limit: int = _DEFAULT_LIMIT) -> list[dict[str, Any]]:
        """读取最近 Proposal 及其 Evidence、Policy、Ticket、Signal 关联事实。"""

        def query(connection: Connection) -> list[dict[str, Any]]:
            proposals = connection.execute(
                sa.select(
                    decision_proposals.c.id,
                    decision_proposals.c.candidate_event_id,
                    decision_proposals.c.market,
                    decision_proposals.c.instrument_id,
                    decision_proposals.c.timeframe,
                    decision_proposals.c.signal_type,
                    decision_proposals.c.direction,
                    decision_proposals.c.signal_id,
                    decision_proposals.c.suggested_transition,
                    decision_proposals.c.rule_version,
                    decision_proposals.c.context_digest,
                    decision_proposals.c.created_at,
                )
                .order_by(decision_proposals.c.created_at.desc())
                .limit(limit)
            ).mappings().all()
            if not proposals:
                return []

            proposal_ids = [row["id"] for row in proposals]
            signal_ids = [row["signal_id"] for row in proposals]
            evaluation_rows = connection.execute(
                sa.select(
                    policy_evaluations.c.id,
                    policy_evaluations.c.proposal_id,
                    policy_evaluations.c.outcome,
                    policy_evaluations.c.policy_version,
                    policy_evaluations.c.evaluated_at,
                )
                .where(policy_evaluations.c.proposal_id.in_(proposal_ids))
                .order_by(policy_evaluations.c.evaluated_at.desc())
            ).mappings().all()
            evaluations = _latest_by(evaluation_rows, "proposal_id")

            ticket_rows = connection.execute(
                sa.select(
                    decision_tickets.c.id,
                    decision_tickets.c.proposal_id,
                    decision_tickets.c.issued_at,
                    decision_tickets.c.expires_at,
                )
                .where(decision_tickets.c.proposal_id.in_(proposal_ids))
            ).mappings().all()
            tickets = {row["proposal_id"]: row for row in ticket_rows}

            signal_rows = connection.execute(
                sa.select(
                    signal_instances.c.id,
                    signal_instances.c.state,
                    signal_instances.c.direction,
                    signal_instances.c.generation,
                    signal_instances.c.version,
                    signal_instances.c.last_transition_at,
                )
                .where(signal_instances.c.id.in_(signal_ids))
            ).mappings().all()
            signals = {row["id"]: row for row in signal_rows}

            ticket_ids = [row["id"] for row in ticket_rows]
            transition_rows = []
            if ticket_ids:
                transition_rows = connection.execute(
                    sa.select(
                        signal_transitions.c.decision_ticket_id,
                        signal_transitions.c.from_state,
                        signal_transitions.c.to_state,
                        signal_transitions.c.occurred_at,
                    )
                    .where(signal_transitions.c.decision_ticket_id.in_(ticket_ids))
                ).mappings().all()
            transitions = {row["decision_ticket_id"]: row for row in transition_rows}

            evidence_rows = connection.execute(
                sa.select(
                    decision_proposal_evidence.c.proposal_id,
                    sa.func.count().label("count"),
                )
                .where(decision_proposal_evidence.c.proposal_id.in_(proposal_ids))
                .group_by(decision_proposal_evidence.c.proposal_id)
            ).all()
            evidence_counts = {row.proposal_id: int(row.count) for row in evidence_rows}

            return [
                _chain_payload(
                    proposal,
                    evaluations.get(proposal["id"]),
                    tickets.get(proposal["id"]),
                    signals.get(proposal["signal_id"]),
                    transitions.get(
                        tickets[proposal["id"]]["id"]
                    ) if proposal["id"] in tickets else None,
                    evidence_counts.get(proposal["id"], 0),
                )
                for proposal in proposals
            ]

        return self._read(query)

    def read_signals(self, limit: int = _DEFAULT_LIMIT) -> list[dict[str, Any]]:
        """读取最新 Signal 投影摘要，不返回完整 payload。"""

        def query(connection: Connection) -> list[dict[str, Any]]:
            rows = connection.execute(
                sa.select(
                    signal_instances.c.id,
                    signal_instances.c.watch_item_id,
                    signal_instances.c.market,
                    signal_instances.c.instrument_id,
                    signal_instances.c.timeframe,
                    signal_instances.c.signal_type,
                    signal_instances.c.direction,
                    signal_instances.c.state,
                    signal_instances.c.priority,
                    signal_instances.c.actionability,
                    signal_instances.c.generation,
                    signal_instances.c.version,
                    signal_instances.c.last_transition_at,
                    signal_instances.c.expires_at,
                )
                .order_by(signal_instances.c.updated_at.desc())
                .limit(limit)
            ).mappings().all()
            return [
                {
                    "id": _uuid(row["id"]),
                    "watch_item_id": _uuid(row["watch_item_id"]),
                    "market": row["market"],
                    "instrument_id": _uuid(row["instrument_id"]),
                    "timeframe": row["timeframe"],
                    "signal_type": row["signal_type"],
                    "direction": row["direction"],
                    "state": row["state"],
                    "priority": row["priority"],
                    "actionability": row["actionability"],
                    "generation": row["generation"],
                    "version": row["version"],
                    "last_transition_at": _iso_datetime(row["last_transition_at"]),
                    "expires_at": _iso_datetime(row["expires_at"]),
                }
                for row in rows
            ]

        return self._read(query)

    def read_unpublished_outbox(self, limit: int = _DEFAULT_LIMIT) -> list[dict[str, Any]]:
        """读取尚未发布的 Outbox 摘要，不返回事件 payload。"""

        def query(connection: Connection) -> list[dict[str, Any]]:
            rows = connection.execute(
                sa.select(
                    outbox_events.c.event_id,
                    outbox_events.c.event_type,
                    outbox_events.c.aggregate_type,
                    outbox_events.c.aggregate_id,
                    outbox_events.c.correlation_id,
                    outbox_events.c.occurred_at,
                    outbox_events.c.available_at,
                    outbox_events.c.attempt_count,
                )
                .where(outbox_events.c.published_at.is_(None))
                .order_by(outbox_events.c.available_at, outbox_events.c.occurred_at)
                .limit(limit)
            ).mappings().all()
            return [
                {
                    "event_id": _uuid(row["event_id"]),
                    "event_type": row["event_type"],
                    "aggregate_type": row["aggregate_type"],
                    "aggregate_id": _uuid(row["aggregate_id"]),
                    "correlation_id": _uuid(row["correlation_id"]),
                    "occurred_at": _iso_datetime(row["occurred_at"]),
                    "available_at": _iso_datetime(row["available_at"]),
                    "attempt_count": row["attempt_count"],
                }
                for row in rows
            ]

        return self._read(query)


def _latest_by(rows: Iterable[Mapping[str, Any]], key: str) -> dict[Any, Mapping[str, Any]]:
    """按时间倒序结果保留每个业务键的最新记录。"""

    latest: dict[Any, Mapping[str, Any]] = {}
    for row in rows:
        latest.setdefault(row[key], row)
    return latest


def _chain_payload(
        proposal: Mapping[str, Any],
        evaluation: Mapping[str, Any] | None,
        ticket: Mapping[str, Any] | None,
        signal: Mapping[str, Any] | None,
        transition: Mapping[str, Any] | None,
        evidence_count: int,
) -> dict[str, Any]:
    """将多张决策事实表聚合成页面可读的单条链路摘要。"""

    return {
        "proposal": {
            "id": _uuid(proposal["id"]),
            "candidate_event_id": _uuid(proposal["candidate_event_id"]),
            "market": proposal["market"],
            "instrument_id": _uuid(proposal["instrument_id"]),
            "timeframe": proposal["timeframe"],
            "signal_type": proposal["signal_type"],
            "direction": proposal["direction"],
            "suggested_transition": proposal["suggested_transition"],
            "rule_version": proposal["rule_version"],
            "context_digest": proposal["context_digest"],
            "created_at": _iso_datetime(proposal["created_at"]),
            "evidence_count": evidence_count,
        },
        "policy": (
            {
                "id": _uuid(evaluation["id"]),
                "outcome": evaluation["outcome"],
                "policy_version": evaluation["policy_version"],
                "evaluated_at": _iso_datetime(evaluation["evaluated_at"]),
            }
            if evaluation
            else None
        ),
        "ticket": (
            {
                "id": _uuid(ticket["id"]),
                "issued_at": _iso_datetime(ticket["issued_at"]),
                "expires_at": _iso_datetime(ticket["expires_at"]),
            }
            if ticket
            else None
        ),
        "signal": (
            {
                "id": _uuid(signal["id"]),
                "state": signal["state"],
                "direction": signal["direction"],
                "generation": signal["generation"],
                "version": signal["version"],
                "last_transition_at": _iso_datetime(signal["last_transition_at"]),
            }
            if signal
            else None
        ),
        "transition": (
            {
                "from_state": transition["from_state"],
                "to_state": transition["to_state"],
                "occurred_at": _iso_datetime(transition["occurred_at"]),
            }
            if transition
            else None
        ),
    }


class RuntimeConsoleApplication:
    """为 Runtime Console 提供只读 HTML 和 JSON GET 路由。

    业务描述:
        将 RuntimeSnapshotReader 的事实摘要暴露为本地开发者页面和稳定 JSON 接口。
    业务场景:
        页面加载概览、决策链、Signal 和未发布 Outbox；开发者可以在浏览器中观察当前
        Run-Once 持久化结果，而不需要访问写接口。
    业务原因:
        观察台必须与业务写入链路隔离，任何非 GET 请求都不能进入领域服务或数据库写事务。
    调用链:
        WSGI request -> route -> reader.read_* -> JSON response / static HTML

    业务规则:
        - 仅支持 GET。
        - API 错误只返回稳定错误码和脱敏消息。
        - 所有响应使用 no-store，避免本地观察结果被浏览器缓存成过期状态。
    """

    def __init__(
            self,
            reader: RuntimeSnapshotReader,
            *,
            index_path: Path = _STATIC_INDEX,
    ) -> None:
        self._reader = reader
        self._index_html = index_path.read_text(encoding="utf-8")

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        """处理一个 WSGI 请求并返回 HTML 或 JSON 响应。"""

        method = environ.get("REQUEST_METHOD", "GET").upper()
        if method != "GET":
            return self._respond_json(
                start_response,
                "405 Method Not Allowed",
                {"error": "READ_ONLY", "message": "Runtime Console is read-only"},
                allow="GET",
            )

        path = environ.get("PATH_INFO", "/")
        query_string = environ.get("QUERY_STRING", "")
        try:
            if path == "/":
                return self._respond_html(start_response, self._index_html)
            if path == "/api/overview":
                return self._respond_json(start_response, "200 OK", self._reader.read_overview())
            if path == "/api/chains":
                return self._respond_json(
                    start_response,
                    "200 OK",
                    {"items": self._reader.read_decision_chains(_limit(query_string))},
                )
            if path == "/api/signals":
                return self._respond_json(
                    start_response,
                    "200 OK",
                    {"items": self._reader.read_signals(_limit(query_string))},
                )
            if path == "/api/outbox":
                return self._respond_json(
                    start_response,
                    "200 OK",
                    {"items": self._reader.read_unpublished_outbox(_limit(query_string))},
                )
            return self._respond_json(
                start_response,
                "404 Not Found",
                {"error": "NOT_FOUND", "message": "resource not found"},
            )
        except ValueError as exc:
            return self._respond_json(
                start_response,
                "400 Bad Request",
                {"error": "INVALID_REQUEST", "message": str(exc)},
            )
        except RuntimeConsoleDatabaseNameError:
            return self._respond_json(
                start_response,
                "503 Service Unavailable",
                {"error": "DATABASE_NOT_ALLOWED", "message": "only loot_test is allowed"},
            )
        except RuntimeConsoleDatabaseError:
            return self._respond_json(
                start_response,
                "503 Service Unavailable",
                {"error": "DATABASE_UNAVAILABLE", "message": "read-only database query failed"},
            )

    @staticmethod
    def _respond_html(start_response: Callable[..., Any], content: str) -> list[bytes]:
        body = content.encode("utf-8")
        start_response(
            "200 OK",
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [body]

    @staticmethod
    def _respond_json(
            start_response: Callable[..., Any],
            status: str,
            payload: Mapping[str, Any],
            *,
            allow: str | None = None,
    ) -> list[bytes]:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ]
        if allow:
            headers.append(("Allow", allow))
        start_response(status, headers)
        return [body]


def _limit(query_string: str) -> int:
    """解析并限制列表 API 的 limit 参数。"""

    values = parse_qs(query_string).get("limit", [str(_DEFAULT_LIMIT)])
    try:
        limit = int(values[0])
    except ValueError as exc:
        raise ValueError("limit must be an integer") from exc
    if not 1 <= limit <= _MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_LIMIT}")
    return limit


def create_runtime_console_app(engine: Engine) -> RuntimeConsoleApplication:
    """创建绑定只读查询适配器的 Runtime Console WSGI 应用。"""

    return RuntimeConsoleApplication(RuntimeSnapshotReader(engine))
