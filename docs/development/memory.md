# 开发过程记忆

> 当前执行快照唯一入口，只保留项目状态、活跃约束、恢复点和当前验证基线。
> 稳定设计见 [architecture](../architecture/README.md)，过程证据见 [季度日志](log/README.md)。

## 当前状态

- 当前阶段：Phase 0 Architecture Foundation。
- 当前交付策略：Crypto First Vertical Slice；Crypto 初版闭环验收和复盘前不实现
  US Equity 或 A-Share 领域业务。
- 已建立核心 contracts、Signal State Machine v0.1、Crypto 行情 Provider v0.1、
  Golden Cases V0.1、Crypto Structure PreFilter V0.1、Candidate 到 Signal 授权链路，
  REQ-0008 PostgreSQL 持久化，以及 REQ-0013 Crypto Run-Once 可执行闭环。
- 正式单次运行入口为 `scripts/run_crypto_once.py`；`main.py` 仍是示例。核心代码位于
  `src/loot/application`、`src/loot/contracts`、`src/loot/runtime`、`src/loot/signals` 和
  `src/loot/domains/crypto`。
- 需求状态与执行队列：[需求管理 2026-Q3](../planning/2026-Q3/需求管理-2026-Q3.md)。

## 当前执行与恢复点

- 当前没有 In Progress 需求；`REQ-0014` 至 `REQ-0016` 已进入 Planned 队列，下一恢复点是
  启动 `REQ-0014` 的组件设计与契约定义。
- `REQ-0013` 已完成 demo/live Run-Once 应用服务、CLI、单元测试和 PostgreSQL 集成测试。
  手工 demo 事实已保留在 `loot_test`，复核入口见
  [过程记录](log/2026-Q3/2026-07-21-req-0013-crypto-run-once.md)。
- `REQ-0008` 已在 `loot_test` 完成真实 PostgreSQL 验收。`loot_dev` 未被本需求触及，后续仅作为
  独立 rollout/deployment 工作处理，不阻塞本次完成。
- 本机集成测试凭据由 `%USERPROFILE%\.loot\database.env` 或环境变量提供；DBX 的
  `loot_app` 测试连接在口令轮换后需要由连接维护者更新。

## 当前实现差异

- PostgreSQL 持久化实现和 `loot_test` migration 已通过真实连接验收；`loot_app` 对
  10 张业务表具备 DML 权限且不能在 `loot` schema 建表。`loot` schema owner 为
  `loot_migrator`，10 张已建业务表 owner 仍为 `postgres`，这是当前非阻塞的运维差异。
- Run-Once 只复用现有 10 张决策链表，不保存原始 K 线、MarketSnapshot 或 Candidate payload；
  这部分需要后续独立数据留存设计。
- Skill Runtime 最小基线已实现；常驻 worker、跨事务恢复器、Agent、Alert 和最小 Replay
  尚未实现。Agent 明确延后到事实留存、最小 Replay 和确定性基线评测之后，并先以
  Shadow Mode 引入。

稳定边界、完整设计链和模块不变量只在 [AGENTS.md](../../AGENTS.md) 与
[架构索引](../architecture/README.md) 维护。

## 当前验证基线

代码验证日期：2026-07-21；上下文复验日期：2026-07-24。

环境：

- Windows，PowerShell。
- Codex bundled Python 3.12.13。
- Git 基线：包含本条记录的当前分支 HEAD；具体提交以 `git log -1 --oneline` 实时结果为准。

已实际执行：

- `& .\.venv\Scripts\python.exe -m pytest -q`：90 passed（包含 8 个真实 PostgreSQL 集成测试）。
- `& .\.venv\Scripts\python.exe -m compileall -q src tests scripts migrations`：通过。
- PyCharm 运行 `scripts\run_crypto_once.py --mode demo`：退出码 0，返回 LONG、ARMED 和完整
  Candidate/Proposal/Evaluation/Ticket/Signal ID。
- DBX 对手工 demo 做只读复核：9 张链路表各 1 条事实，`outbox_events` 5 条；Signal 为
  `LONG / ARMED / version=1`，Policy 为 `APPROVED`，迁移为 `OBSERVING -> ARMED`。
- `migrations/versions/20260716_0001_crypto_decision_persistence.sql`：已在 `loot_test` 真实执行；
  DBX 验证 10 张业务表、70 个显式业务约束、31 个索引（含 2 个 partial index）。
- `& .\.venv\Scripts\python.exe scripts\check_context.py`：2026-07-24 复验通过，68 个 Markdown、
  167 个本地链接，项目 Skill 与本机镜像一致。

完整环境初始化和验证命令见 [本地运行说明](../runbooks/local-run.md)。旧 macOS 验证结果
保留在对应季度日志中，不再表述为当前机器已复验。
