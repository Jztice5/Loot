# 开发过程记忆

> 当前执行快照唯一入口，只保留项目状态、活跃约束、恢复点和当前验证基线。
> 稳定设计见 [architecture](../architecture/README.md)，过程证据见 [季度日志](log/README.md)。

## 当前状态

- 当前阶段：Phase 0 Architecture Foundation。
- 当前交付策略：Crypto First Vertical Slice；Crypto 初版闭环验收和复盘前不实现
  US Equity 或 A-Share 领域业务。
- 已建立核心 contracts、Signal State Machine v0.1、Crypto 行情 Provider v0.1、
  Golden Cases V0.1、Crypto Structure PreFilter V0.1、Candidate 到 Signal 授权链路，
  REQ-0008 PostgreSQL 持久化、REQ-0013 Crypto Run-Once 可执行闭环、REQ-0014 Crypto
  WatchItem 与 MonitoringSubscription 持久化基线、REQ-0015 Crypto H1 Worker，以及
  REQ-0017 Runtime Console 只读观察台。
- 正式单次运行入口为 `scripts/run_crypto_once.py`，Worker 入口为 `scripts/run_crypto_worker.py`；
  `main.py` 仍是示例。核心代码位于
  `src/loot/application`、`src/loot/contracts`、`src/loot/runtime`、`src/loot/signals` 和
  `src/loot/domains/crypto`。
- 需求状态与执行队列：[需求管理 2026-Q3](../planning/2026-Q3/需求管理-2026-Q3.md)。

## 当前执行与恢复点

- `REQ-0018` 已进入 In Progress，当前切片是 BTC H1 历史数据集与质量门禁：复用生产
  `MarketBar`，独立建设历史分页、确定性 manifest、质量报告和文件恢复；本阶段不修改生产
  PreFilter，也不把历史数据写入 Signal 链路。
- `REQ-0015` 已完成；0003 已在 `loot_test` 执行，常驻监控 Worker、Run/Attempt 账本、租约、
  恢复阶段、精确 H1 Provider 和 CLI 已通过真实 PostgreSQL 验收。阶段复核确认当前规则只证明
  工程链路正确，不证明分析有效性。
- `REQ-0014` 已完成 Crypto WatchItem、MonitoringSubscription 生命周期和 Run-Once 持久化
  身份接入；`loot_test` 保留一条 ACTIVE BTC-USDT H1 配置及其 LONG/ARMED demo 事实，详见
  [过程记录](log/2026-Q3/2026-07-27-req-0014-crypto-watchlist-monitoring.md)。
- `REQ-0017` 已完成本地只读 Runtime Console，入口为
  `scripts\run_runtime_console.py`，页面不会触发 Run-Once 或写入业务状态。
- `REQ-0013` 已完成 demo/live Run-Once 应用服务、CLI、单元测试和 PostgreSQL 集成测试。
  手工 demo 事实已保留在 `loot_test`，复核入口见
  [过程记录](log/2026-Q3/2026-07-21-req-0013-crypto-run-once.md)。
- `REQ-0008` 已在 `loot_test` 完成真实 PostgreSQL 验收。`loot_dev` 未被本需求触及，后续仅作为
  独立 rollout/deployment 工作处理，不阻塞本次完成。
- 本机集成测试凭据由 `%USERPROFILE%\.loot\database.env` 或环境变量提供；DBX 的
  `loot_app` 测试连接在口令轮换后需要由连接维护者更新。

## 当前实现差异

- PostgreSQL 持久化实现和三版 `loot_test` migration 已通过真实连接验收；`loot_app` 对
  15 张业务表具备所需 DML 权限且不能在 `loot` schema 建表。`loot` schema owner 为
  `loot_migrator`，既有表 owner 仍为 `postgres`，这是当前非阻塞的运维差异。
- Run-Once 使用持久化 ACTIVE WatchItem 和 H1 Subscription，但仍不保存原始 K 线、
  MarketSnapshot 或 Candidate payload；
  这部分需要后续独立数据留存设计。
- Skill Runtime 最小基线已实现；Agent、Alert 和最小 Replay 尚未实现。Agent 明确延后到
  事实留存、最小 Replay 和确定性基线评测之后，并先以
  Shadow Mode 引入。
- REQ-0015 已实现精确 H1 target、Run/Attempt、Snapshot 指纹绑定、lease reclaim、工作流版本
  隔离和 `--once/--loop`。当前未启动常驻进程；`--loop` 需要独立部署和进程守护配置。
- 已实现 Signal State Machine 内部的确定性到期收敛：初始化新 setup 前在同一监控身份锁内检查
  最新 Signal，若 immutable `expires_at` 已到则写入 `EXPIRED`、独立 expiry 事件和 Outbox，再分配
  下一 generation。Worker、Agent、Skill 和 Policy 仍不得直接写 Signal。`0004` 已在 `loot_test`
  执行，并已完成 PostgreSQL 集成与全量回归。

稳定边界、完整设计链和模块不变量只在 [AGENTS.md](../../AGENTS.md) 与
[架构索引](../architecture/README.md) 维护。

## 当前验证基线

代码验证日期：2026-07-28；需求队列与上下文复核日期：2026-08-04。

环境：

- Windows，PowerShell。
- Codex bundled Python 3.12.13。
- Git 基线：包含本条记录的当前分支 HEAD；具体提交以 `git log -1 --oneline` 实时结果为准。

本轮已实际执行：

- `& .\.venv\Scripts\python.exe -m pytest -q tests\unit\signals\test_state_machine.py tests\unit\application\test_crypto_run_once.py`：
  22 passed，覆盖到期收敛、重复检测、下一 generation 和 Run-Once 时钟透传。
- `& .\.venv\Scripts\python.exe -m pytest -q tests\integration\test_crypto_decision_persistence.py`：
  8 passed，确认 `0004` 后无 Ticket 到期账本、Outbox 和下一 generation 均可持久化。
- `& .\.venv\Scripts\python.exe -m pytest -q`：134 passed。
- `& .\.venv\Scripts\python.exe -m pytest -q tests\integration\test_crypto_monitoring_worker.py`：
  3 passed，覆盖重复物化、工作流版本隔离、双 Worker claim、lease reclaim、退避和暂停取消。
- `& .\.venv\Scripts\python.exe -m compileall -q src tests scripts`：通过。
- Demo Worker：Run `3325fbcb-40a0-575a-a5f1-63ce2e4aa803` 完成，结果
  `SIGNAL_TRANSITIONED / POLICY_APPROVED`；Proposal、Evaluation、Ticket、Signal、Transition
  各 1 条，Attempt 1 条，Run Outbox 2 条。
- OKX public REST 精确窗口复核：返回 4 根闭合 H1 K 线，目标与最新 `closed_at` 均为
  `2026-07-28T07:00:00Z`，Snapshot `310f64f6-0936-5448-b30c-75919d97604d`。

此前验证基线：

- `& .\.venv\Scripts\python.exe -m pytest -q`：114 passed，0 failed，0 skipped。
- `& .\.venv\Scripts\python.exe -m compileall -q src tests scripts migrations`：通过。
- `& .\.venv\Scripts\python.exe -m pytest -q tests\integration\test_crypto_watchlist.py`：5 passed。
- Runtime Console 真实 HTTP 复核：数据库为 `loot_test`，状态 `healthy`，Proposal 1、Signal 1、
  未发布 Outbox 5；API 不返回 `last_error`。
- 浏览器复核：桌面端与 390px 移动端无横向溢出；刷新按钮成功；控制台无 error/warning。
- PyCharm 集成终端创建 ACTIVE BTC-USDT H1 WatchItem `1fcb2d4b-15ac-4a7c-b1ee-2bdb668579f9`，
  随后运行 demo Run-Once：退出码 0，返回 `LONG / ARMED / POLICY_APPROVED`。
- 只读数据库复核：连接为 `loot_test / loot_app`；WatchItem 与 Subscription 均 ACTIVE，Inbox
  为 PROCESSED，创建产生 2 条未发布 Outbox；Proposal、Evaluation、Ticket 和 Signal 方向一致。
- `migrations/versions/20260716_0001_crypto_decision_persistence.sql`：已在 `loot_test` 真实执行；
  DBX 验证 10 张业务表、70 个显式业务约束、31 个索引（含 2 个 partial index）。
- `& .\.venv\Scripts\python.exe scripts\check_context.py`：2026-07-27 复验通过，最终文件与链接
  计数以本轮命令输出为准，项目 Skill 与本机镜像一致。

完整环境初始化和验证命令见 [本地运行说明](../runbooks/local-run.md)。旧 macOS 验证结果
保留在对应季度日志中，不再表述为当前机器已复验。
