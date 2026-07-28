# Loot Runtime Console 只读观察台 V0.1

| 属性 | 值 |
|---|---|
| 状态 | Accepted for REQ-0017 |
| 版本 | 0.1 |
| 适用范围 | 本地开发与 `loot_test` 决策事实观察 |
| 写权限 | 无；页面和 API 只允许 GET |
| 数据范围 | 现有决策链、Signal、Outbox 和数据库健康摘要 |

## 1. 目标与非目标

Runtime Console 为开发者提供一个本地只读页面，用于观察已经持久化的 Crypto Run-Once
决策事实：

```text
PostgreSQL loot_test
    -> RuntimeSnapshotReader
    -> GET-only WSGI API
    -> Runtime Console HTML
```

目标：

- 查看 Proposal、Evidence、Policy、Ticket、Signal Transition 的关联链路。
- 查看 Signal 当前投影、未发布 Outbox 数量和数据库连接状态。
- 明确区分已实现能力与尚未实现的 Worker、Alert、Replay 能力。
- 使用现有 SQLAlchemy Core 和标准库 WSGI，不引入前端框架或新的运行时服务依赖。

非目标：

- 不实现 WatchItem、MonitoringSubscription、常驻 Worker、Run ledger 或 Alert Center。
- 不提供任何业务写入、重试、ACK、IGNORE、状态迁移或自动交易操作。
- 不展示完整 payload、数据库连接字符串、口令或未脱敏敏感信息。

## 2. 查询边界

页面使用 `RuntimeSnapshotReader` 读取以下事实表：

- `inbox_messages`
- `evidence_sets`
- `decision_proposals`
- `decision_proposal_evidence`
- `policy_evaluations`
- `decision_tickets`
- `signal_instances`
- `signal_transitions`
- `outbox_events`

每个请求都执行：

1. 创建 PostgreSQL 连接和事务。
2. 执行 `SET TRANSACTION READ ONLY`。
3. 校验 `SELECT current_database()` 必须为 `loot_test`。
4. 执行固定 SQLAlchemy Core 查询，不把用户参数拼接为 SQL。
5. 返回脱敏摘要；不返回 JSONB payload。

数据库不可用时 API 返回 `503` 和稳定错误码；数据库名不是 `loot_test` 时拒绝返回业务数据。

## 3. API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/` | 返回只读观察台页面 |
| GET | `/api/overview` | 数据库、事实数量、最近活动和能力状态 |
| GET | `/api/chains?limit=20` | 最近 Proposal 聚合决策链 |
| GET | `/api/signals?limit=20` | 最新 Signal 投影摘要 |
| GET | `/api/outbox?limit=20` | 未发布 Outbox 摘要 |

`limit` 只允许 `1..100`。非 GET 请求返回 `405`，未知路径返回 `404`。API 响应使用
`Cache-Control: no-store`，避免开发者看到缓存的运行状态。

## 4. 页面信息架构

- 顶部：数据库连接状态、只读标识和手动刷新。
- 概览指标：决策链数量、Signal 数量、未发布 Outbox 数量、最近活动时间。
- 能力状态：Run-Once、决策持久化、常驻 Worker、Alert Center、Replay。
- 决策链路：Proposal、方向、Policy、Ticket、Signal 和状态迁移。
- Signal：状态、方向、周期、版本和 generation。
- Outbox：事件类型、聚合类型、尝试次数和发生时间。

页面不展示当前不存在的运行数据；Worker、Alert 和 Replay 显示为 `not_implemented`，不使用
静态成功数据填充。

## 5. 运行与安全

启动入口：`scripts/run_runtime_console.py`。

- 数据库 DSN 只从 `LOOT_TEST_DATABASE_URL` 或用户级配置读取。
- 页面启动日志只输出本地 URL，不输出 DSN 或口令。
- 默认监听 `127.0.0.1:8765`，只用于本机开发观察。
- 查询适配器只实现 SELECT；页面不依赖 Run-Once 应用服务，不会重复触发分析。

## 6. 演进边界

后续接入 Worker、Run ledger、Alert 或 Replay 时，应新增对应读模型和需求，不把这些能力
直接伪装进当前页面。页面可以扩展只读查询，但必须保持：

- 写入仍只能通过对应领域命令和状态机。
- 读模型必须标明事实来源、更新时间和是否为推导结果。
- 新增能力需要在 API、页面、架构、Runbook、需求和验证记录中同步收尾。
