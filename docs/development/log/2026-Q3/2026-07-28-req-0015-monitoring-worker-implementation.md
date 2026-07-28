# REQ-0015 Crypto 常驻监控 Worker 实现

## 背景

REQ-0013 只能手工运行一次决策链，REQ-0014 只提供持久化 WatchItem 和 Subscription。系统需要
把每个已收盘 H1 周期变成可恢复的数据库 Run，再由 Worker 按租约执行。

## 本轮实现

- 新增 MonitoringRun、MonitoringRunAttempt 强类型契约及确定性 UUIDv5 身份。
- 新增精确 `target_bar_closed_at` Provider 能力，OKX 使用历史 K 线端点并拒绝错位窗口。
- 修正 Snapshot 身份：市场输入变化影响指纹，单纯 as_of/received_at 采集时钟变化不影响重试身份。
- Run-Once 新增预加载 Snapshot 入口和阶段 checkpoint 回调，保留原 CLI 兼容入口。
- 新增 `monitoring_runs`、`monitoring_run_attempts` SQLAlchemy metadata 和 0003 SQL。
- 新增到期物化、SKIP LOCKED claim、lease reclaim、输入绑定、阶段推进、完成/重试/失败 Repository。
- 新增 `CryptoMonitoringWorker` 和 `scripts/run_crypto_worker.py` 的 `--once/--loop` 入口。

## 实现中修正

原 MarketSnapshot 指纹包含 as_of 和 received_at，导致同一历史窗口稍后重抓必然改变 snapshot_id，
与 Worker 的稳定重试要求冲突。现将采集审计时间从业务输入指纹中移除；价格、成交量、Provider
事件身份、窗口和闭合状态仍完整参与指纹。

真实 PostgreSQL 验收还修正了两个仅在驱动和共享数据库环境中暴露的问题：

- `INSERT ... ON CONFLICT DO NOTHING` 不再依赖 psycopg 的 `rowcount` 判断是否实际插入，改用
  `RETURNING id`，避免 Run 已落库但 Scheduler 错报 0 且漏写 Outbox。
- materialize 与 claim 显式绑定同一个 workflow_version；claim 查询按版本过滤，防止未来 v2
  Worker 或集成测试误消费 v1 Run。
- 集成测试 teardown 按测试 WatchItem 反查全部 Run，外部 Worker 抢先物化时仍能按外键顺序清理。

## 验证

- `loot_test` 已执行 0003；全量测试 131 passed。
- PostgreSQL Worker 集成测试 3 passed，覆盖重复物化、版本隔离、并发 claim、租约接管、退避和
  暂停取消。
- Demo Worker 完成 1 个 Run，结果为 `SIGNAL_TRANSITIONED / POLICY_APPROVED`；Run、Attempt、
  Proposal、Evaluation、Ticket、Signal、Transition 和 Outbox 事实均已只读复核。
- OKX public REST 返回精确目标 H1 窗口；4 根 K 线全部闭合，最后 `closed_at` 与目标一致。
- compileall、PyCharm build/problem inspection 和 context check 通过。

## 验收中发现的后续风险

既有 Signal 的 `expires_at` 已过但状态仍为 OBSERVING/ARMED 时，Signal workflow 仍按活跃
generation 拒绝新 setup。Worker 将该冲突作为可观测失败保留，不能绕过 Policy 和 Signal State
Machine 直接终态化旧 Signal。到期收敛或持续评估需要后续独立设计。

## 2026-07-28 后续修复：确定性到期收敛

该风险已通过 Signal State Machine 内部的受限时间型迁移修复。PostgreSQL workflow 在同一监控
身份锁内，先对最新非终态 Signal 的 immutable `expires_at` 执行 `EXPIRED` 收敛，再创建下一
generation。收敛使用独立 `SignalExpiryEvent`、无 Ticket 的 `signal_transitions` 账本记录和
`loot.crypto.SignalExpired` Outbox，不伪造、复用或消费 `DecisionTicket`，也不改变市场方向、
Policy、持仓或 Actionability。

需要由 `loot_migrator` 在 `loot_test` 先执行 `20260728_0004_signal_expiry_reconciliation.sql`，
再运行 PostgreSQL 集成测试；该数据库验证尚未在本次记录时执行。
